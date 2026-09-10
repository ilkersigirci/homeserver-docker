import asyncio
import os
import time
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
import litellm
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, Request
from litellm.proxy._types import (
    LiteLLM_UserTable,
    LitellmUserRoles,
    ProxyException,
    UserAPIKeyAuth,
)
from litellm.proxy.auth.user_api_key_auth import (
    RouteChecks,
    _request_used_user_custom_auth,
    _require_custom_auth_common_checks,
    _should_run_user_custom_auth,
)
from litellm.proxy.types_utils.utils import get_instance_fn

_CONFIG_PATH = "/app/litellm-config/config.yaml"
_ISSUER = "https://issuer.invalid"
_AUDIENCE = "https://llm.invalid"


def _request(
    *headers: tuple[str, str],
    method: str = "GET",
    path: str = "/v1/models",
    query_string: bytes = b"",
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "http",
            "server": ("litellm", 4000),
            "client": ("127.0.0.1", 12345),
            "path": path,
            "query_string": query_string,
            "headers": [
                (name.lower().encode(), value.encode()) for name, value in headers
            ],
        }
    )


def _expect_proxy_error(code: str, fn: Callable[[], object]) -> None:
    try:
        fn()
    except ProxyException as exc:
        assert exc.code == code
    else:
        raise AssertionError(f"expected ProxyException code {code}")


def _verify_dispatcher() -> None:
    async def custom_auth(*_args, **_kwargs):
        return None

    custom_request = _request(("X-LiteLLM-Auth-Lane", "custom"))
    assert _should_run_user_custom_auth(custom_request, custom_auth) is True
    assert _request_used_user_custom_auth(custom_request) is True
    _require_custom_auth_common_checks(
        custom_request,
        {"custom_auth_run_common_checks": True},
    )
    _expect_proxy_error(
        "500",
        lambda: _require_custom_auth_common_checks(custom_request, {}),
    )

    native_request = _request(("X-LiteLLM-Auth-Lane", "native"))
    assert _should_run_user_custom_auth(native_request, custom_auth) is False
    assert _request_used_user_custom_auth(native_request) is False
    _require_custom_auth_common_checks(native_request, {})

    _expect_proxy_error(
        "401",
        lambda: _should_run_user_custom_auth(_request(), custom_auth),
    )
    _expect_proxy_error(
        "400",
        lambda: _should_run_user_custom_auth(
            _request(("X-LiteLLM-Auth-Lane", "unknown")),
            custom_auth,
        ),
    )
    assert (
        _should_run_user_custom_auth(
            _request(path="/health/liveliness"),
            custom_auth,
        )
        is True
    )

    for disabled in (False, None, "true"):
        with patch.object(litellm, "enable_post_custom_auth_checks", disabled):
            _expect_proxy_error(
                "500",
                lambda: _require_custom_auth_common_checks(
                    custom_request, {"custom_auth_run_common_checks": True}
                ),
            )
            _require_custom_auth_common_checks(native_request, {})


def _configure_hook() -> None:
    os.environ.update(
        {
            "OIDC_ISSUER": _ISSUER,
            "OIDC_JWKS_URL": f"{_ISSUER}/jwks",
            "OIDC_USERINFO_URL": f"{_ISSUER}/userinfo",
            "OIDC_AUDIENCE": _AUDIENCE,
            "OIDC_REQUIRED_SCOPE": "llm:invoke",
            "OIDC_SIGNING_ALGORITHM": "RS256",
            "OIDC_REQUIRE_VERIFIED_EMAIL": "true",
        }
    )
    os.environ.pop("OIDC_TOKEN_PROFILE", None)


async def _verify_sso_without_license() -> None:
    from fastapi.responses import RedirectResponse
    from litellm.proxy import proxy_server
    from litellm.proxy.management_endpoints import ui_sso

    redirect = RedirectResponse("https://issuer.invalid/authorize")
    users = SimpleNamespace(count_billable_users=AsyncMock(return_value=100))
    with (
        patch.dict(os.environ, {"GENERIC_CLIENT_ID": "build-test"}, clear=True),
        patch.object(proxy_server, "premium_user", False),
        patch.object(proxy_server, "prisma_client", object()),
        patch.object(proxy_server, "user_custom_ui_sso_sign_in_handler", None),
        patch.object(ui_sso, "UserRepository", return_value=users),
        patch.object(ui_sso, "show_missing_vars_in_env", return_value=None),
        patch.object(
            ui_sso.SSOAuthenticationHandler,
            "get_redirect_url_for_sso",
            return_value="https://litellm.invalid/sso/callback",
        ),
        patch.object(
            ui_sso.SSOAuthenticationHandler,
            "get_sso_login_redirect",
            new=AsyncMock(return_value=redirect),
        ),
    ):
        assert await ui_sso.google_login(_request()) is redirect
        assert await ui_sso.debug_sso_login(_request()) is redirect
        users.count_billable_users.assert_not_awaited()


async def _verify_shared_authorization() -> None:
    import importlib

    from litellm.proxy import proxy_server

    auth = importlib.import_module("litellm.proxy.auth.user_api_key_auth")
    user = LiteLLM_UserTable(
        user_id="build-test-user",
        user_role=LitellmUserRoles.INTERNAL_USER,
        models=["allowed-model"],
        max_budget=10,
        metadata={},
    )
    # Stop at the shared authorization boundary; prove both ingress lanes
    # load the database user and propagate an authorization denial.
    denial = RuntimeError("shared authorization denied")
    common_checks = AsyncMock(side_effect=denial)
    with (
        patch.object(proxy_server, "master_key", "sk-build-test"),
        patch.object(
            proxy_server, "general_settings", {"custom_auth_run_common_checks": True}
        ),
        patch.object(proxy_server, "llm_router", None),
        patch.object(auth, "get_user_object", AsyncMock(return_value=user)),
        patch.object(auth, "get_global_proxy_spend", AsyncMock(return_value=0)),
        patch.object(auth, "common_checks", common_checks),
    ):
        for lane in ("native", "custom"):
            request = _request(
                ("X-LiteLLM-Auth-Lane", lane),
                method="POST",
                path="/v1/chat/completions",
            )
            _should_run_user_custom_auth(request, AsyncMock())
            for active in (True, False):
                user.metadata = {"scim_active": active}
                common_checks.reset_mock()
                try:
                    await auth._run_centralized_common_checks(
                        user_api_key_auth_obj=UserAPIKeyAuth(
                            user_id=user.user_id,
                            user_role=LitellmUserRoles.INTERNAL_USER,
                            end_user_id="",
                        ),
                        request=request,
                        request_data={"model": "allowed-model"},
                        route="/v1/chat/completions",
                    )
                except Exception as exc:
                    if active:
                        assert exc is denial
                        common_checks.assert_awaited_once()
                        assert common_checks.call_args.kwargs["user_object"] is user
                        assert (
                            common_checks.call_args.kwargs["skip_budget_checks"]
                            is False
                        )
                    else:
                        assert "deactivated via SCIM" in str(exc)
                        common_checks.assert_not_awaited()
                else:
                    raise AssertionError(f"{lane} authorization denial was bypassed")


def _token(
    private_key,
    *,
    profile: str,
    claims_override: dict | None = None,
    headers_override: dict | None = None,
) -> str:
    now = int(time.time())
    if profile == "pocket-id":
        profile_claims = {"scp": ["llm:invoke"]}
    elif profile == "keycloak":
        profile_claims = {
            "scope": "openid llm:invoke",
            "typ": "Bearer",
            "preferred_username": "person",
        }
    else:
        profile_claims = {
            "scope": "openid llm:invoke",
            "client_id": "web-client",
            "jti": "access-token-id",
        }
    return jwt.encode(
        {
            "sub": "oidc-user",
            "iss": _ISSUER,
            "aud": [_AUDIENCE],
            "iat": now,
            "exp": now + 300,
            **profile_claims,
            **(claims_override or {}),
        },
        private_key,
        algorithm="RS256",
        headers={
            "kid": "build-test",
            "typ": "at+jwt" if profile == "rfc9068" else "JWT",
            **(headers_override or {}),
        },
    )


async def _verify_hook() -> None:
    _configure_hook()
    custom_auth = get_instance_fn(
        "oidc_delegated_auth.user_api_key_auth",
        config_file_path=_CONFIG_PATH,
    )
    assert callable(custom_auth)
    hook_globals = custom_auth.__globals__
    assert hook_globals["_TOKEN_PROFILE"] == "rfc9068"
    validate_user_profile = hook_globals["_validate_user_profile"]

    assert hook_globals["_REQUIRE_VERIFIED_EMAIL"] is True
    hook_globals["_REQUIRE_VERIFIED_EMAIL"] = True
    verified_profile = validate_user_profile(
        {
            "sub": "oidc-user",
            "email": "Person@Example.com",
            "email_verified": True,
        },
        "oidc-user",
    )
    assert verified_profile["email"] == "person@example.com"
    _expect_proxy_error(
        "403",
        lambda: validate_user_profile(
            {
                "sub": "oidc-user",
                "email": "person@example.com",
                "email_verified": False,
            },
            "oidc-user",
        ),
    )
    for invalid_email in ("not-an-email", {"unexpected": "value"}):
        _expect_proxy_error(
            "401",
            lambda invalid_email=invalid_email: validate_user_profile(
                {
                    "sub": "oidc-user",
                    "email": invalid_email,
                    "email_verified": True,
                },
                "oidc-user",
            ),
        )

    hook_globals["_REQUIRE_VERIFIED_EMAIL"] = False
    for unverified_email in (
        "person@example.com",
        "not-an-email",
        {"unexpected": "value"},
    ):
        unverified_profile = validate_user_profile(
            {
                "sub": "oidc-user",
                "email": unverified_email,
                "email_verified": False,
            },
            "oidc-user",
        )
        assert "email" not in unverified_profile
    hook_globals["_REQUIRE_VERIFIED_EMAIL"] = True

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    user = SimpleNamespace(
        user_id="litellm-user",
        user_email="person@example.com",
        models=["allowed-model"],
        spend=1.25,
        max_budget=10,
        tpm_limit=1000,
        rpm_limit=10,
    )

    async def get_signing_key(_encoded_token: str):
        return public_key

    async def resolve_user(_subject: str, _encoded_token: str):
        return user

    hook_globals["_get_signing_key"] = get_signing_key
    hook_globals["_resolve_user"] = resolve_user

    for profile in ("rfc9068", "pocket-id", "keycloak"):
        hook_globals["_TOKEN_PROFILE"] = profile
        result = await custom_auth(
            _request(("Authorization", "Bearer token")),
            _token(private_key, profile=profile),
        )
        assert result.user_id == "litellm-user"
        assert result.models == ["allowed-model"]
        assert result.user_max_budget == 10

        invalid_claims = [
            ({"aud": "web-client"}, "401"),
            ({"iss": _ISSUER + "/"}, "401"),
            ({"exp": 0}, "401"),
            ({"sub": None}, "401"),
            ({"scp": [], "scope": ""}, "403"),
        ]
        if profile == "rfc9068":
            for name in ("client_id", "jti"):
                for value in (None, "", 123):
                    invalid_claims.append(({name: value}, "401"))
            invalid_claims.extend(
                [
                    ({"sub": "web-client"}, "403"),
                    ({"scope": ["llm:invoke"]}, "403"),
                ]
            )
            for header_type in ("application/at+jwt", "at+JWT"):
                token = _token(
                    private_key, profile=profile, headers_override={"typ": header_type}
                )
                assert (await custom_auth(_request(), token)).user_id == user.user_id
        elif profile == "pocket-id":
            invalid_claims.extend(
                [
                    ({"sub": "client-web-client"}, "403"),
                    ({"type": "id-token"}, "401"),
                    ({"scp": None, "scope": "llm:invoke"}, "403"),
                ]
            )
        else:
            invalid_claims.extend(
                [
                    ({"preferred_username": "service-account-client"}, "403"),
                    ({"typ": "ID"}, "401"),
                ]
            )
        if profile != "pocket-id":
            invalid_claims.append(({"scope": None, "scp": ["llm:invoke"]}, "403"))
        invalid_tokens = [
            (_token(private_key, profile=profile, claims_override=claims), code)
            for claims, code in invalid_claims
        ]
        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        invalid_tokens.append((_token(wrong_key, profile=profile), "401"))
        if profile == "rfc9068":
            invalid_tokens.extend(
                (
                    _token(
                        private_key, profile=profile, headers_override={"typ": value}
                    ),
                    "401",
                )
                for value in (None, "JWT", "id+jwt", 123)
            )
        for token, code in invalid_tokens:
            try:
                await custom_auth(_request(), token)
            except ProxyException as exc:
                assert exc.code == code, (profile, exc)
            else:
                raise AssertionError(f"Invalid {profile} token was accepted")

        for path in (
            "/v1/responses",
            "/v1/models",
            "/v1/models/allowed-model",
            "/models/allowed-model",
            "/v1/fine_tuning/jobs/job-1",
            "/fine_tuning/jobs/job-1",
            "/model/info",
            "/v1/model/info",
        ):
            assert RouteChecks.is_virtual_key_allowed_to_call_route(
                route=path, valid_token=result, request=_request(path=path)
            )
        for method, path in (
            ("GET", "/catalog/items"),
            ("POST", "/model/new"),
            ("POST", "/model/update"),
            ("PATCH", "/model/deployment-id/update"),
            ("POST", "/model/delete"),
            ("POST", "/config/update"),
        ):
            try:
                RouteChecks.is_virtual_key_allowed_to_call_route(
                    route=path,
                    valid_token=result,
                    request=_request(method=method, path=path),
                )
            except HTTPException as exc:
                assert exc.status_code == 403, (method, path)
            else:
                raise AssertionError(f"Delegated token granted access to {path}")


async def _verify_gateway_authorization() -> None:
    """Exercise real auth and metadata handlers; mock only identity/DB reads."""
    import importlib

    import httpx
    from fastapi import Depends, FastAPI, WebSocket
    from fastapi.responses import JSONResponse
    from litellm.caching.caching import DualCache
    from litellm.proxy import proxy_server
    from litellm.proxy.hooks.model_max_budget_limiter import (
        _PROXY_VirtualKeyModelMaxBudgetLimiter,
    )

    auth = importlib.import_module("litellm.proxy.auth.user_api_key_auth")
    _configure_hook()
    custom_auth = get_instance_fn(
        "oidc_delegated_auth.user_api_key_auth", config_file_path=_CONFIG_PATH
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    user = LiteLLM_UserTable(
        user_id="gateway-test-user",
        user_role=LitellmUserRoles.INTERNAL_USER,
        models=["allowed"],
        spend=0,
        max_budget=10,
        tpm_limit=1000,
        rpm_limit=10,
    )
    models = [
        {
            "model_name": name,
            "litellm_params": {"model": "openai/gpt-4o", "api_key": "DUMMY"},
            "model_info": {
                "id": model_id,
                "project_metadata": {"description": "client-owned metadata"},
                **extra,
            },
        }
        for name, model_id, extra in (
            ("allowed", "allowed-id", {}),
            ("denied", "denied-id", {}),
            ("allowed", "other-team-id", {"team_id": "other-team"}),
        )
    ]
    router = litellm.Router(model_list=models)
    app = FastAPI()

    @app.exception_handler(ProxyException)
    async def proxy_error(_request, exc):
        return JSONResponse({"error": exc.message}, status_code=int(exc.code))

    @app.post("/v1/chat/completions")
    @app.post("/v1/responses")
    async def inference_probe(key=Depends(auth.user_api_key_auth)):
        # Stop after authorization without calling an external model provider.
        return {"user_id": key.user_id, "model_budget": key.user_model_max_budget}

    for path in ("/model/info", "/v1/model/info"):
        app.add_api_route(path, proxy_server.model_info_v1, methods=["GET"])
    app.add_api_route(
        "/v1/models/{model_id}", proxy_server.model_info, methods=["GET"]
    )

    async def user_model_budget(**_kwargs):
        return user.model_max_budget

    async def current_spend(**_kwargs):
        return user.spend

    token = _token(private_key, profile="rfc9068")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-LiteLLM-Auth-Lane": "custom",
    }
    limiter = _PROXY_VirtualKeyModelMaxBudgetLimiter(DualCache())
    with (
        patch.dict(
            custom_auth.__globals__,
            {
                "_TOKEN_PROFILE": "rfc9068",
                "_get_signing_key": AsyncMock(return_value=private_key.public_key()),
                "_resolve_user": AsyncMock(return_value=user),
            },
        ),
        patch.object(proxy_server, "user_custom_auth", custom_auth),
        patch.object(proxy_server, "master_key", "sk-gateway-test"),
        patch.object(
            proxy_server, "general_settings", {"custom_auth_run_common_checks": True}
        ),
        patch.object(proxy_server, "llm_router", router),
        patch.object(proxy_server, "llm_model_list", models),
        patch.object(proxy_server, "user_model", None),
        patch.object(proxy_server, "prisma_client", None),
        patch.object(proxy_server, "get_current_spend", current_spend),
        patch.object(proxy_server, "model_max_budget_limiter", limiter),
        patch.object(auth, "get_user_object", AsyncMock(return_value=user)),
        patch.object(auth, "_read_user_model_max_budget", user_model_budget),
        patch.object(auth, "get_global_proxy_spend", AsyncMock(return_value=0)),
        patch.object(
            proxy_server, "_get_caller_byok_team_scope", AsyncMock(return_value=set())
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway.invalid"
        ) as client:
            for path in ("/model/info", "/v1/model/info"):
                for suffix in ("", "?litellm_model_id=allowed-id"):
                    response = await client.get(path + suffix, headers=headers)
                    assert response.status_code == 200, response.text
                    data = response.json()["data"]
                    assert [row["model_info"]["id"] for row in data] == ["allowed-id"]
                    assert data[0]["model_info"]["project_metadata"] == {
                        "description": "client-owned metadata"
                    }
                    assert "api_key" not in data[0]["litellm_params"]
                for model_id in ("denied-id", "other-team-id"):
                    response = await client.get(
                        path, params={"litellm_model_id": model_id}, headers=headers
                    )
                    assert response.status_code == 200, response.text
                    assert response.json()["data"] == [], response.text

            response = await client.get("/v1/models/allowed", headers=headers)
            assert response.status_code == 200, response.text
            response = await client.get("/v1/models/denied", headers=headers)
            assert response.status_code in (403, 404), response.text

            # The native master-key lane still uses upstream authorization.
            response = await client.get(
                "/model/info?litellm_model_id=denied-id",
                headers={
                    "Authorization": "Bearer sk-gateway-test",
                    "X-LiteLLM-Auth-Lane": "native",
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["data"][0]["model_name"] == "denied"

            for path in ("/v1/chat/completions", "/v1/responses"):
                body = {"model": "allowed", "messages": [], "input": "test"}
                response = await client.post(path, json=body, headers=headers)
                assert response.status_code == 200, response.text
                for override in (
                    {"model": "denied"},
                    {"fallbacks": ["denied"]},
                    {"fallbacks": [{"model": "denied"}]},
                ):
                    response = await client.post(
                        path, json={**body, **override}, headers=headers
                    )
                    assert response.status_code == 403, response.text

                user.model_max_budget = {
                    "allowed": {"max_budget": 0, "budget_duration": "1d"}
                }
                response = await client.post(path, json=body, headers=headers)
                assert response.status_code == 429, response.text
                user.model_max_budget = {}
                user.max_budget = 0
                response = await client.post(path, json=body, headers=headers)
                assert response.status_code == 429, response.text
                user.max_budget = 10

            # Never fall back to native key validation on the delegated lane.
            response = await client.get(
                "/model/info",
                headers={**headers, "Authorization": "Bearer sk-gateway-test"},
            )
            assert response.status_code == 401, response.text

        # Run the actual upstream WebSocket credential extractor and auth chain.
        for lane, credential in (("custom", token), ("native", "sk-gateway-test")):
            for name, value in (
                ("authorization", f"Bearer {credential}"),
                ("sec-websocket-protocol", f"openai-insecure-api-key.{credential}"),
                ("api-key", credential),
            ):
                websocket = WebSocket(
                    {
                        "type": "websocket",
                        "scheme": "ws",
                        "server": ("gateway.invalid", 80),
                        "path": "/v1/realtime",
                        "query_string": b"model=allowed",
                        "headers": [
                            (b"x-litellm-auth-lane", lane.encode()),
                            (name.encode(), value.encode()),
                        ],
                    },
                    receive=AsyncMock(),
                    send=AsyncMock(),
                )
                result = await auth.user_api_key_auth_websocket(websocket)
                if lane == "custom":
                    assert result.user_id == user.user_id
                    assert result.user_tpm_limit == 1000
                    assert result.user_rpm_limit == 10
                else:
                    assert result.user_role == LitellmUserRoles.PROXY_ADMIN

        # Responses may identify the model only after an authenticated handshake.
        from litellm.proxy.response_api_endpoints.endpoints import (
            _enforce_responses_ws_first_frame_model_auth,
        )

        for max_budget in (0, 10):
            user.model_max_budget = {
                "allowed": {"max_budget": max_budget, "budget_duration": "1d"}
            }
            websocket = WebSocket(
                {
                    "type": "websocket",
                    "scheme": "ws",
                    "server": ("gateway.invalid", 80),
                    "path": "/v1/responses",
                    "query_string": b"",
                    "headers": [
                        (name.lower().encode(), value.encode())
                        for name, value in headers.items()
                    ],
                },
                receive=AsyncMock(),
                send=AsyncMock(),
            )
            result = await auth.user_api_key_auth_websocket(websocket)
            assert result.user_model_max_budget == user.model_max_budget
            request = _request(method="POST", path="/v1/responses")
            try:
                await _enforce_responses_ws_first_frame_model_auth(
                    request=request,
                    model="allowed",
                    user_api_key_dict=result,
                    llm_router=router,
                )
            except litellm.BudgetExceededError:
                assert max_budget == 0
            else:
                assert max_budget > 0, "Responses first frame bypassed the user model budget"
    print("Gateway authorization, model metadata, and WebSocket checks passed")


def main() -> None:
    with patch.object(litellm, "enable_post_custom_auth_checks", True, create=True):
        _verify_dispatcher()
        asyncio.run(_verify_sso_without_license())
        asyncio.run(_verify_shared_authorization())
        asyncio.run(_verify_hook())
        asyncio.run(_verify_gateway_authorization())


if __name__ == "__main__":
    main()

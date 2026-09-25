"""Build-time checks for OIDC access-token Internal User authorization."""

import asyncio
import inspect
import json
import os
import ssl
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import litellm
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from jwt import PyJWKClient
from litellm.proxy._types import LiteLLM_UserTable, ProxyException, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import (
    RouteChecks,
    _user_api_key_auth_builder,
)
from litellm.proxy.types_utils.utils import get_instance_fn

_CONFIG_PATH = "/app/litellm-config/config.yaml"
_SUBJECT = "subject"
_ISSUER = "https://pocketid.example.test"
_AUDIENCE = "https://llm.example.test"
_KID = "oidc-test-key"


def _request(*headers: tuple[str, str], path: str = "/v1/chat/completions", method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "http",
            "server": ("litellm", 4000),
            "client": ("127.0.0.1", 12345),
            "path": path,
            "query_string": b"",
            "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
        }
    )


def _user(**overrides):
    values = {
        "user_id": _SUBJECT,
        "user_email": "person@example.com",
        "user_role": "internal_user",
        "models": ["allowed-model"],
        "spend": 1.5,
        "max_budget": 10.0,
        "tpm_limit": 1000,
        "rpm_limit": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def _expect_denied(awaitable, code: str) -> None:
    try:
        await awaitable
    except ProxyException as exc:
        assert str(exc.code) == code, (exc.code, exc.message)
    else:
        raise AssertionError("authorization unexpectedly succeeded")


def _token_fixture():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = _KID
    jwks_client = PyJWKClient("https://issuer.example.test/jwks", cache_jwk_set=False)
    jwks_client.fetch_data = lambda: {"keys": [public_jwk]}

    def token(*, header_typ="at+jwt", key=private_key, kid=_KID, **overrides):
        claims = {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": _SUBJECT,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "scope": "openid llm:invoke",
        }
        claims.update(overrides)
        claims = {name: value for name, value in claims.items() if value is not None}
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid, "typ": header_typ})

    return token, jwks_client


def _auth():
    return get_instance_fn("user_auth.user_api_key_auth", config_file_path=_CONFIG_PATH)


def _assert_user_auth(authorized: UserAPIKeyAuth) -> None:
    assert authorized.user_id == _SUBJECT
    assert authorized.end_user_id == _SUBJECT
    assert authorized.user_role == "internal_user"
    assert authorized.models == ["allowed-model"]
    assert authorized.user_max_budget == 10.0
    assert authorized.user_tpm_limit == 1000
    assert authorized.user_rpm_limit == 10
    assert authorized.token is None


def _verify_jwks_tls() -> None:
    """The JWKS client follows LiteLLM's native SSL_VERIFY."""
    from litellm.llms.custom_httpx.http_handler import get_ssl_configuration

    for verify, verified in ((None, True), ("true", True), ("false", False)):
        env = {name: value for name, value in os.environ.items() if name != "SSL_VERIFY"}
        if verify is not None:
            env["SSL_VERIFY"] = verify
        with patch.dict(os.environ, env, clear=True):
            context = _auth().__globals__["_JWKS_CLIENT"].ssl_context
            assert context.check_hostname is verified, verify
            assert (context.verify_mode == ssl.CERT_REQUIRED) is verified, verify
    # The insecure context must not weaken LiteLLM's cached shared context.
    assert get_ssl_configuration().verify_mode == ssl.CERT_REQUIRED


async def _verify_tokens() -> None:
    auth = _auth()
    token, jwks_client = _token_fixture()
    get_user = AsyncMock(return_value=_user())
    with patch.dict(auth.__globals__, {"_JWKS_CLIENT": jwks_client, "get_user_object": get_user}):
        _assert_user_auth(await auth(request=_request(), api_key=token()))
        assert get_user.await_args.kwargs["user_id"] == _SUBJECT
        assert get_user.await_args.kwargs["user_id_upsert"] is True

        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for invalid, code in (
            (token(aud="https://other.example.test"), "401"),
            (token(iss="https://other.example.test"), "401"),
            (token(exp=int(time.time()) - 60), "401"),
            (token(sub=None), "401"),
            (token(sub=""), "401"),
            (token(scope="openid other:scope"), "403"),
            (token(scope=None, scp=["llm:invoke"]), "403"),
            (token(header_typ="JWT"), "401"),
            (token(key=other_key), "401"),
            (token(kid="unknown-key"), "401"),
        ):
            await _expect_denied(auth(request=_request(), api_key=invalid), code)

        with patch.dict(auth.__globals__, {"get_user_object": AsyncMock(return_value=_user(models=[]))}):
            authorized = await auth(request=_request(), api_key=token())
            assert authorized.models == []
            assert authorized.user_id == _SUBJECT
        with patch.dict(auth.__globals__, {"get_user_object": AsyncMock(return_value=None)}):
            await _expect_denied(auth(request=_request(), api_key=token()), "503")
        with patch.dict(auth.__globals__, {"get_user_object": AsyncMock(side_effect=ValueError("db"))}):
            await _expect_denied(auth(request=_request(), api_key=token()), "503")

        with patch.object(
            jwks_client,
            "get_signing_key_from_jwt",
            side_effect=jwt.PyJWKClientConnectionError("offline"),
        ):
            await _expect_denied(auth(request=_request(), api_key=token()), "503")

    # Anything that is not a JWT, including every virtual key, is left to LiteLLM.
    for native in (None, "", "not.a.jwt", "master.key.with.dots", "sk-personal-virtual-key"):
        assert await auth(request=_request(), api_key=native) is None, native


async def _verify_routes() -> None:
    auth = _auth()
    token, jwks_client = _token_fixture()
    with patch.dict(
        auth.__globals__,
        {"_JWKS_CLIENT": jwks_client, "get_user_object": AsyncMock(return_value=_user())},
    ):
        authorized = await auth(request=_request(), api_key=token())

    for path in (
        "/v1/chat/completions",
        "/v1/responses",
        "/v1/models",
        "/v1/models/allowed-model",
        "/models/allowed-model",
        "/model/info",
        "/v1/model/info",
    ):
        assert RouteChecks.should_call_route(route=path, valid_token=authorized, request=_request(path=path))
    for path in ("/key/generate", "/user/new", "/model/new", "/spend/logs"):
        try:
            RouteChecks.should_call_route(route=path, valid_token=authorized, request=_request(path=path))
        except HTTPException as exc:
            assert exc.status_code == 403, path
        else:
            raise AssertionError(f"user token was allowed to call {path}")


async def _verify_model_info_scope() -> None:
    """Expose custom metadata without leaking denied or cross-team models."""

    from litellm.proxy import proxy_server

    models = [
        {
            "model_name": name,
            "litellm_params": {"model": "openai/gpt-4o", "api_key": "DUMMY"},
            "model_info": {
                "id": model_id,
                "project_metadata": {"description": description},
                **extra,
            },
        }
        for name, model_id, description, extra in (
            ("allowed", "allowed-id", "visible", {}),
            ("denied", "denied-id", "hidden", {}),
            ("allowed", "other-team-id", "cross-team", {"team_id": "other-team"}),
        )
    ]
    router = litellm.Router(model_list=models)
    auth = _auth()
    token, jwks_client = _token_fixture()
    user = _user(models=["allowed"])

    async def model_info(model_id: str | None = None):
        return await proxy_server.model_info_v1(
            user_api_key_dict=authorized,
            litellm_model_id=model_id,
            include_team_models=False,
            teamId=None,
            healthy_only=False,
        )

    with (
        patch.dict(
            auth.__globals__,
            {"_JWKS_CLIENT": jwks_client, "get_user_object": AsyncMock(return_value=user)},
        ),
        patch.object(proxy_server, "llm_router", router),
        patch.object(proxy_server, "llm_model_list", models),
        patch.object(proxy_server, "user_model", None),
        patch.object(proxy_server, "prisma_client", None),
        patch.object(proxy_server, "_get_caller_byok_team_scope", AsyncMock(return_value=set())),
    ):
        for user_models, expected_ids in (
            (["allowed"], {"allowed-id"}),
            ([], {"allowed-id", "denied-id"}),
        ):
            user.models = user_models
            authorized = await auth(request=_request(), api_key=token())
            listing = (await model_info())["data"]
            assert {row["model_info"]["id"] for row in listing} == expected_ids
            assert all("api_key" not in row["litellm_params"] for row in listing)

            allowed = (await model_info("allowed-id"))["data"]
            assert allowed[0]["model_info"]["project_metadata"] == {"description": "visible"}
            denied = (await model_info("denied-id"))["data"]
            assert {row["model_info"]["id"] for row in denied} == expected_ids & {"denied-id"}
            assert (await model_info("other-team-id"))["data"] == []


async def _verify_enforcement() -> None:
    """Run the installed auth chain; mock only identity, database, and spend reads."""

    import litellm.proxy.auth.user_api_key_auth as auth_module
    from litellm.caching.caching import DualCache
    from litellm.proxy import proxy_server
    from litellm.proxy.hooks.model_max_budget_limiter import _PROXY_VirtualKeyModelMaxBudgetLimiter
    from litellm.proxy.response_api_endpoints.endpoints import _enforce_responses_ws_first_frame_model_auth

    assert "if response is not None:" in inspect.getsource(_user_api_key_auth_builder)

    custom_auth = _auth()
    token, jwks_client = _token_fixture()
    oidc = {"Authorization": f"Bearer {token()}"}
    native = {"Authorization": "Bearer sk-native-test"}
    user = LiteLLM_UserTable(
        user_id=_SUBJECT, user_role="internal_user", models=["allowed"], spend=0, max_budget=10
    )
    models = [
        {
            "model_name": name,
            "litellm_params": {"model": "openai/gpt-4o", "api_key": "DUMMY"},
            "model_info": {"id": name},
        }
        for name in ("allowed", "denied")
    ]
    router = litellm.Router(model_list=models)
    app = FastAPI()

    @app.exception_handler(ProxyException)
    async def proxy_error(_request, exc):
        return JSONResponse({"error": exc.message}, status_code=int(exc.code))

    @app.post("/v1/responses")
    async def auth_probe(key=Depends(auth_module.user_api_key_auth)):  # noqa: B008
        # Stop after authorization without calling a model provider.
        return {"user_id": key.user_id, "user_role": key.user_role}

    app.add_api_route("/v1/models", proxy_server.model_list, methods=["GET"])
    app.add_api_route("/v1/models/{model_id}", proxy_server.model_info, methods=["GET"])

    async def user_spend(**_kwargs):
        return user.spend

    async def user_model_budget(**_kwargs):
        return user.model_max_budget

    async def first_frame_allowed() -> bool:
        """Authorize a Responses WebSocket that names its model in the first frame."""
        websocket = WebSocket(
            {
                "type": "websocket",
                "scheme": "ws",
                "server": ("litellm", 4000),
                "path": "/v1/responses",
                "query_string": b"",
                "headers": [(b"authorization", oidc["Authorization"].encode())],
            },
            receive=AsyncMock(),
            send=AsyncMock(),
        )
        handshake = await auth_module.user_api_key_auth_websocket(websocket)
        try:
            await _enforce_responses_ws_first_frame_model_auth(
                request=_request(("Authorization", oidc["Authorization"]), path="/v1/responses"),
                model="allowed",
                user_api_key_dict=handshake,
                llm_router=router,
            )
        except litellm.BudgetExceededError:
            return False
        return True

    with (
        patch.dict(
            custom_auth.__globals__,
            {"_JWKS_CLIENT": jwks_client, "get_user_object": AsyncMock(return_value=user)},
        ),
        patch.object(proxy_server, "user_custom_auth", custom_auth),
        patch.object(proxy_server, "master_key", "sk-native-test"),
        patch.object(proxy_server, "llm_router", router),
        patch.object(proxy_server, "llm_model_list", models),
        patch.object(proxy_server, "user_model", None),
        patch.object(proxy_server, "prisma_client", None),
        patch.object(proxy_server, "get_current_spend", user_spend),
        patch.object(
            proxy_server, "model_max_budget_limiter", _PROXY_VirtualKeyModelMaxBudgetLimiter(DualCache())
        ),
        patch.object(proxy_server, "_get_caller_byok_team_scope", AsyncMock(return_value=set())),
        patch.object(auth_module, "get_user_object", AsyncMock(return_value=user)),
        patch.object(auth_module, "_read_user_model_max_budget", user_model_budget),
        patch.object(auth_module, "get_global_proxy_spend", AsyncMock(return_value=0)),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://litellm.invalid",
        ) as client:

            async def call(headers=oidc, model="allowed"):
                body = {"model": model, "input": "hi"}
                return await client.post("/v1/responses", headers=headers, json=body)

            response = await call()
            assert response.json() == {"user_id": _SUBJECT, "user_role": "internal_user"}, response.text
            response = await call(headers=native, model="denied")
            assert response.json()["user_role"] == "proxy_admin", response.text
            response = await call(headers={"Authorization": f"Bearer {token(header_typ='JWT')}"})
            assert response.status_code == 401, response.text
            # The unrestricted case runs last so the budget checks below cover it.
            for user_models, visible_models in (
                (["allowed"], {"allowed"}),
                ([], {"allowed", "denied"}),
            ):
                user.models = user_models
                response = await client.get("/v1/models", headers=oidc)
                assert response.status_code == 200, response.text
                assert {row["id"] for row in response.json()["data"]} == visible_models, response.text
                for model in ("allowed", "denied"):
                    response = await call(model=model)
                    assert response.status_code == (200 if model in visible_models else 403), response.text
                    response = await client.get(f"/v1/models/{model}", headers=oidc)
                    assert response.status_code == (200 if model in visible_models else 404), response.text

            assert await first_frame_allowed()
            user.model_max_budget = {"allowed": {"max_budget": 0, "budget_duration": "1d"}}
            response = await call()
            assert response.status_code == 429, response.text
            assert not await first_frame_allowed(), "Responses WebSocket bypassed the user's model budget"
            user.model_max_budget = {}
            user.max_budget = 0
            response = await call()
            assert response.status_code == 429, response.text
            user.max_budget = 10

            # The hook refuses every credential unless both enforcement settings are on.
            for disabled in (
                patch.object(proxy_server, "general_settings", {}),
                patch.object(litellm, "enable_post_custom_auth_checks", False),
            ):
                with disabled:
                    for headers in (oidc, native):
                        response = await call(headers=headers)
                        assert response.status_code == 500, response.text


def main() -> None:
    os.environ["LITELLM_OIDC_ISSUER"] = _ISSUER
    os.environ["LITELLM_OIDC_JWKS_URL"] = "https://issuer.example.test/jwks"
    os.environ["LITELLM_OIDC_AUDIENCE"] = _AUDIENCE
    os.environ["LITELLM_OIDC_REQUIRED_SCOPE"] = "llm:invoke"
    os.environ["LITELLM_OIDC_SIGNING_ALGORITHM"] = "RS256"
    from litellm.proxy import proxy_server

    # Mirror configs/litellm/config.yaml: user_auth refuses to serve without both.
    proxy_server.general_settings["custom_auth_run_common_checks"] = True
    litellm.enable_post_custom_auth_checks = True
    _verify_jwks_tls()
    asyncio.run(_verify_tokens())
    asyncio.run(_verify_routes())
    asyncio.run(_verify_model_info_scope())
    asyncio.run(_verify_enforcement())
    print("Internal User authorization checks passed")


if __name__ == "__main__":
    main()

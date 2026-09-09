import asyncio
import os
import time
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request
from litellm.proxy._types import (
    LiteLLM_UserTable,
    LitellmUserRoles,
    ProxyException,
    UserAPIKeyAuth,
)
from litellm.proxy.auth.user_api_key_auth import (
    _reject_alternate_credential_surfaces,
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

    _expect_proxy_error(
        "400",
        lambda: _reject_alternate_credential_surfaces(
            _request(("api-key", "secret")),
            "/v1/models",
        ),
    )
    _expect_proxy_error(
        "400",
        lambda: _reject_alternate_credential_surfaces(
            _request(query_string=b"key=secret"),
            "/v1beta/models/example:generateContent",
        ),
    )


def _configure_hook() -> None:
    os.environ.update(
        {
            "OIDC_ISSUER": _ISSUER,
            "OIDC_JWKS_URL": f"{_ISSUER}/jwks",
            "OIDC_USERINFO_URL": f"{_ISSUER}/userinfo",
            "OIDC_AUDIENCE": _AUDIENCE,
            "OIDC_REQUIRED_SCOPE": "llm:invoke",
            "OIDC_TOKEN_PROFILE": "pocket-id",
            "OIDC_SIGNING_ALGORITHM": "RS256",
            "OIDC_REQUIRE_VERIFIED_EMAIL": "true",
        }
    )


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
                        assert common_checks.call_args.kwargs["skip_budget_checks"] is False
                    else:
                        assert "deactivated via SCIM" in str(exc)
                        common_checks.assert_not_awaited()
                else:
                    raise AssertionError(f"{lane} authorization denial was bypassed")


def _token(
    private_key,
    *,
    profile: str,
    scopes: list[str] | None = None,
    subject: str = "oidc-user",
    preferred_username: str = "person",
) -> str:
    now = int(time.time())
    granted_scopes = scopes if scopes is not None else ["llm:invoke"]
    profile_claims = (
        {"scp": granted_scopes}
        if profile == "pocket-id"
        else {
            "scope": " ".join(granted_scopes),
            "typ": "Bearer",
            "preferred_username": preferred_username,
        }
    )
    return jwt.encode(
        {
            "sub": subject,
            "iss": _ISSUER,
            "aud": [_AUDIENCE],
            "iat": now,
            "exp": now + 300,
            **profile_claims,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "build-test"},
    )


async def _verify_hook() -> None:
    _configure_hook()
    custom_auth = get_instance_fn(
        "oidc_delegated_auth.user_api_key_auth",
        config_file_path=_CONFIG_PATH,
    )
    assert callable(custom_auth)
    hook_globals = custom_auth.__globals__
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

    for profile in ("pocket-id", "keycloak"):
        hook_globals["_TOKEN_PROFILE"] = profile
        result = await custom_auth(
            _request(("Authorization", "Bearer token")),
            _token(private_key, profile=profile),
        )
        assert result.user_id == "litellm-user"
        assert result.allowed_routes == ["openai_routes"]
        assert result.models == ["allowed-model"]
        assert result.user_max_budget == 10

    hook_globals["_TOKEN_PROFILE"] = "pocket-id"
    assert hook_globals["_get_scopes"]({"scp": ["llm:invoke"]}) == {"llm:invoke"}
    assert hook_globals["_get_scopes"]({"scope": "llm:invoke"}) == set()

    hook_globals["_TOKEN_PROFILE"] = "keycloak"
    assert hook_globals["_get_scopes"]({"scope": "openid llm:invoke"}) == {
        "openid",
        "llm:invoke",
    }
    assert hook_globals["_get_scopes"]({"scp": ["llm:invoke"]}) == set()

    try:
        await custom_auth(
            _request(),
            _token(
                private_key,
                profile="keycloak",
                preferred_username="service-account-client",
            ),
        )
    except ProxyException as exc:
        assert exc.code == "403"
    else:
        raise AssertionError("Keycloak service-account token was accepted")


def main() -> None:
    _verify_dispatcher()
    asyncio.run(_verify_sso_without_license())
    asyncio.run(_verify_shared_authorization())
    asyncio.run(_verify_hook())


if __name__ == "__main__":
    main()

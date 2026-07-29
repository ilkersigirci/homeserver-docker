import asyncio
import os
import time
from collections.abc import Callable
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request
from litellm.proxy._types import ProxyException
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
        }
    )


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
    asyncio.run(_verify_hook())


if __name__ == "__main__":
    main()

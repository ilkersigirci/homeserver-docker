import asyncio
import os
from typing import Any, NoReturn

import httpx
import jwt
from fastapi import Request, status
from jwt import PyJWKClient
from litellm.proxy._types import (
    LiteLLMRoutes,
    LitellmUserRoles,
    ProxyErrorTypes,
    ProxyException,
    UserAPIKeyAuth,
)
from litellm.proxy.auth.auth_checks import get_user_object

_ISSUER = os.environ.get("OIDC_ISSUER", "").rstrip("/")
_JWKS_URL = os.environ.get("OIDC_JWKS_URL", "")
_USERINFO_URL = os.environ.get("OIDC_USERINFO_URL", "")
_AUDIENCE = os.environ.get("OIDC_AUDIENCE", "")
_REQUIRED_SCOPE = os.environ.get("OIDC_REQUIRED_SCOPE", "")
_TOKEN_PROFILE = os.environ.get("OIDC_TOKEN_PROFILE", "")
_SIGNING_ALGORITHM = os.environ.get("OIDC_SIGNING_ALGORITHM", "")

_POCKET_ID_PROFILE = "pocket-id"
_KEYCLOAK_PROFILE = "keycloak"
_TOKEN_PROFILES = frozenset({_POCKET_ID_PROFILE, _KEYCLOAK_PROFILE})
_ALLOWED_SIGNING_ALGORITHMS = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "ES256",
        "ES384",
        "ES512",
        "EdDSA",
    }
)

_LIVELINESS_ROUTE = ("GET", "/health/liveliness")

if not all(
    (
        _ISSUER,
        _JWKS_URL,
        _USERINFO_URL,
        _AUDIENCE,
        _REQUIRED_SCOPE,
        _TOKEN_PROFILE,
        _SIGNING_ALGORITHM,
    )
):
    raise RuntimeError("OIDC delegated authentication settings are incomplete")
if _TOKEN_PROFILE not in _TOKEN_PROFILES:
    raise RuntimeError("OIDC_TOKEN_PROFILE must be pocket-id or keycloak")
if _SIGNING_ALGORITHM not in _ALLOWED_SIGNING_ALGORITHMS:
    raise RuntimeError("OIDC_SIGNING_ALGORITHM must be an asymmetric JWT algorithm")

_JWKS_CLIENT = PyJWKClient(
    _JWKS_URL,
    cache_keys=False,
    cache_jwk_set=True,
    lifespan=300,
    timeout=5,
)


def _deny(message: str, code: int = status.HTTP_401_UNAUTHORIZED) -> NoReturn:
    raise ProxyException(
        message=f"Authentication Error - {message}",
        type=ProxyErrorTypes.auth_error,
        param="Authorization",
        code=code,
    )


def _unavailable(message: str) -> NoReturn:
    raise ProxyException(
        message=message,
        type=ProxyErrorTypes.internal_server_error,
        param=None,
        code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _require_access_token(api_key: str | None) -> str:
    if api_key is None:
        _deny("missing OIDC access token")
    token = api_key.strip()
    if not token:
        _deny("missing OIDC access token")
    return token


def _get_scopes(claims: dict[str, Any]) -> set[str]:
    if _TOKEN_PROFILE == _POCKET_ID_PROFILE:
        raw_scopes = claims.get("scp")
        if not isinstance(raw_scopes, list) or not all(
            isinstance(scope, str) for scope in raw_scopes
        ):
            return set()
        return set(raw_scopes)

    raw_scope = claims.get("scope")
    return set(raw_scope.split()) if isinstance(raw_scope, str) else set()


def _validate_profile_claims(claims: dict[str, Any], subject: str) -> None:
    if _TOKEN_PROFILE == _POCKET_ID_PROFILE:
        if claims.get("type") == "id-token":
            _deny("OIDC ID tokens are not accepted")
        machine_identity = subject
        machine_prefix = "client-"
    else:
        if claims.get("typ") != "Bearer":
            _deny("OIDC access token has an invalid token type")
        machine_identity = claims.get("preferred_username")
        machine_prefix = "service-account-"

    if (
        not isinstance(machine_identity, str)
        or not machine_identity
        or machine_identity.startswith(machine_prefix)
    ):
        _deny(
            "a user-delegated OIDC access token is required",
            code=status.HTTP_403_FORBIDDEN,
        )


async def _get_signing_key(encoded_token: str):
    try:
        signing_key = await asyncio.to_thread(
            _JWKS_CLIENT.get_signing_key_from_jwt,
            encoded_token,
        )
    except (jwt.PyJWKClientConnectionError, OSError, TimeoutError):
        _unavailable("OIDC signing keys are unavailable")
    except jwt.PyJWTError:
        _deny("invalid OIDC access token")
    return signing_key.key


async def _decode_access_token(encoded_token: str) -> dict[str, Any]:
    signing_key = await _get_signing_key(encoded_token)
    try:
        claims = jwt.decode(
            encoded_token,
            signing_key,
            algorithms=[_SIGNING_ALGORITHM],
            issuer=_ISSUER,
            audience=_AUDIENCE,
            leeway=10,
            options={
                "require": ["sub", "iss", "aud", "iat", "exp"],
            },
        )
    except jwt.PyJWTError:
        _deny("invalid or expired OIDC access token")

    subject = claims["sub"]
    if not isinstance(subject, str) or not subject:
        _deny(
            "a user-delegated OIDC access token is required",
            code=status.HTTP_403_FORBIDDEN,
        )
    _validate_profile_claims(claims, subject)
    if _REQUIRED_SCOPE not in _get_scopes(claims):
        _deny(
            f"OIDC access token is missing {_REQUIRED_SCOPE}",
            code=status.HTTP_403_FORBIDDEN,
        )
    return claims


async def _fetch_user_profile(
    encoded_token: str,
    expected_subject: str,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(
                _USERINFO_URL,
                headers={"Authorization": f"Bearer {encoded_token}"},
            )
            response.raise_for_status()
            profile = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            _unavailable("OIDC UserInfo service is unavailable")
        _deny("OIDC UserInfo lookup failed")
    except httpx.RequestError:
        _unavailable("OIDC UserInfo service is unavailable")
    except ValueError:
        _deny("OIDC UserInfo lookup failed")

    if not isinstance(profile, dict):
        _deny("OIDC UserInfo returned an invalid profile")
    if profile.get("sub") != expected_subject:
        _deny("OIDC UserInfo subject mismatch")

    email = profile.get("email")
    if email is not None:
        if profile.get("email_verified") is not True:
            _deny(
                "OIDC email is not verified",
                code=status.HTTP_403_FORBIDDEN,
            )
        if not isinstance(email, str) or "@" not in email or len(email) > 320:
            _deny("OIDC UserInfo returned an invalid email")
        profile["email"] = email.strip().casefold()

    return profile


async def _lookup_user(
    *,
    subject: str,
    email: str | None,
    create: bool,
):
    from litellm.proxy import proxy_server

    return await get_user_object(
        user_id=subject,
        sso_user_id=subject,
        user_email=email,
        prisma_client=proxy_server.prisma_client,
        user_api_key_cache=proxy_server.user_api_key_cache,
        user_id_upsert=create,
    )


async def _resolve_user(subject: str, encoded_token: str):
    try:
        return await _lookup_user(subject=subject, email=None, create=False)
    except ValueError:
        profile = await _fetch_user_profile(encoded_token, subject)
        email = profile.get("email")

    try:
        return await _lookup_user(subject=subject, email=email, create=True)
    except ValueError:
        try:
            return await _lookup_user(subject=subject, email=email, create=False)
        except ValueError:
            _unavailable("LiteLLM user lookup failed")


async def user_api_key_auth(
    request: Request,
    api_key: str | None,
) -> UserAPIKeyAuth:
    if (request.method, request.url.path) == _LIVELINESS_ROUTE:
        return UserAPIKeyAuth(user_role=LitellmUserRoles.INTERNAL_USER_VIEW_ONLY)

    encoded_token = _require_access_token(api_key)
    claims = await _decode_access_token(encoded_token)
    user = await _resolve_user(claims["sub"], encoded_token)
    if user is None:
        _unavailable("LiteLLM user lookup failed")

    return UserAPIKeyAuth(
        user_id=user.user_id,
        user_email=user.user_email,
        user_role=LitellmUserRoles.INTERNAL_USER,
        allowed_routes=[LiteLLMRoutes.openai_routes.name],
        models=list(user.models or []),
        user_spend=user.spend,
        user_max_budget=user.max_budget,
        user_tpm_limit=user.tpm_limit,
        user_rpm_limit=user.rpm_limit,
    )

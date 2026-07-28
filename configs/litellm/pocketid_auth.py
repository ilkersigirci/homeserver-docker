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

_ISSUER = os.environ.get("POCKETID_ISSUER", "").rstrip("/")
_JWKS_URL = os.environ.get("POCKETID_JWKS_URL", "")
_USERINFO_URL = os.environ.get("POCKETID_USERINFO_URL", "")
_AUDIENCE = os.environ.get("LITELLM_OIDC_AUDIENCE", "")
_REQUIRED_SCOPE = os.environ.get("LITELLM_OIDC_REQUIRED_SCOPE", "")

_LIVELINESS_ROUTE = ("GET", "/health/liveliness")

if not all((_ISSUER, _JWKS_URL, _USERINFO_URL, _AUDIENCE, _REQUIRED_SCOPE)):
    raise RuntimeError("Pocket ID OIDC authentication settings are incomplete")

_JWKS_CLIENT = PyJWKClient(
    _JWKS_URL,
    cache_keys=True,
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


def _require_access_token(api_key: str) -> str:
    token = api_key.strip()
    if not token:
        _deny("missing Pocket ID access token")
    return token


def _get_scopes(claims: dict[str, Any]) -> set[str]:
    raw_scopes = claims.get("scp", claims.get("scope", []))
    if isinstance(raw_scopes, str):
        return set(raw_scopes.split())
    if isinstance(raw_scopes, list):
        return {scope for scope in raw_scopes if isinstance(scope, str)}
    return set()


async def _get_signing_key(encoded_token: str):
    try:
        signing_key = await asyncio.to_thread(
            _JWKS_CLIENT.get_signing_key_from_jwt,
            encoded_token,
        )
    except (jwt.PyJWKClientConnectionError, OSError, TimeoutError):
        _unavailable("Pocket ID signing keys are unavailable")
    except jwt.PyJWTError:
        _deny("invalid Pocket ID access token")
    return signing_key.key


async def _decode_access_token(encoded_token: str) -> dict[str, Any]:
    signing_key = await _get_signing_key(encoded_token)
    try:
        claims = jwt.decode(
            encoded_token,
            signing_key,
            algorithms=["RS256"],
            issuer=_ISSUER,
            audience=_AUDIENCE,
            leeway=10,
            options={
                "require": ["sub", "iss", "aud", "iat", "exp"],
            },
        )
    except jwt.PyJWTError:
        _deny("invalid or expired Pocket ID access token")

    subject = claims["sub"]
    if not isinstance(subject, str) or not subject or subject.startswith("client-"):
        _deny(
            "a user-delegated Pocket ID token is required",
            code=status.HTTP_403_FORBIDDEN,
        )
    if _REQUIRED_SCOPE not in _get_scopes(claims):
        _deny(
            f"Pocket ID token is missing {_REQUIRED_SCOPE}",
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
            _unavailable("Pocket ID user profile service is unavailable")
        _deny("Pocket ID user profile lookup failed")
    except httpx.RequestError:
        _unavailable("Pocket ID user profile service is unavailable")
    except ValueError:
        _deny("Pocket ID user profile lookup failed")

    if not isinstance(profile, dict):
        _deny("Pocket ID returned an invalid user profile")
    if profile.get("sub") != expected_subject:
        _deny("Pocket ID user profile subject mismatch")

    email = profile.get("email")
    if email is not None:
        if profile.get("email_verified") is not True:
            _deny(
                "Pocket ID email is not verified",
                code=status.HTTP_403_FORBIDDEN,
            )
        if not isinstance(email, str) or "@" not in email or len(email) > 320:
            _deny("Pocket ID returned an invalid email")
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
        # Concurrent first requests can race while creating the same user.
        try:
            return await _lookup_user(subject=subject, email=email, create=False)
        except ValueError:
            _unavailable("LiteLLM user lookup failed")


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
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

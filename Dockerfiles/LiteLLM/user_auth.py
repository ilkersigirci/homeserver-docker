"""Authenticate OIDC access tokens as LiteLLM Internal Users.

An RFC 9068 access token issued for the LiteLLM API resource resolves to the
Internal User named by its verified ``sub`` (LiteLLM's own JWT auth is
Enterprise-only). LiteLLM then enforces that user's models, budget, and rate
limits natively.

Every other credential returns ``None`` and continues through LiteLLM's native
master-key, virtual-key, and public-route authentication
(``custom-auth-fallback.patch``). A virtual key owned by an Internal User is
bounded by that user's models and budget natively.
"""

from __future__ import annotations

import asyncio
import os
import ssl
from typing import NoReturn

import jwt
import litellm
from fastapi import Request, status
from jwt import PyJWKClient
from litellm.llms.custom_httpx.http_handler import get_ssl_configuration
from litellm.proxy._types import (
    LiteLLMRoutes,
    LitellmUserRoles,
    ProxyErrorTypes,
    ProxyException,
    UserAPIKeyAuth,
)
from litellm.proxy.auth.auth_checks import get_user_object

_ASYMMETRIC_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
)


def _setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


_ISSUER = _setting("LITELLM_OIDC_ISSUER")
_AUDIENCE = _setting("LITELLM_OIDC_AUDIENCE")
_REQUIRED_SCOPE = _setting("LITELLM_OIDC_REQUIRED_SCOPE")
_ALGORITHM = _setting("LITELLM_OIDC_SIGNING_ALGORITHM")
if _ALGORITHM not in _ASYMMETRIC_ALGORITHMS:
    raise RuntimeError("LITELLM_OIDC_SIGNING_ALGORITHM must be an asymmetric algorithm")
# Share LiteLLM's SSL_VERIFY / SSL_CERT_FILE policy with PyJWT's urllib client.
_SSL_CONTEXT = get_ssl_configuration()
if _SSL_CONTEXT is False:
    _SSL_CONTEXT = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    _SSL_CONTEXT.check_hostname = False
    _SSL_CONTEXT.verify_mode = ssl.CERT_NONE
_JWKS_CLIENT = PyJWKClient(
    _setting("LITELLM_OIDC_JWKS_URL"), lifespan=300, timeout=5, ssl_context=_SSL_CONTEXT
)


def _deny(message: str, code: int) -> NoReturn:
    raise ProxyException(
        message=f"Authentication Error - {message}",
        type=ProxyErrorTypes.auth_error,
        param="Authorization",
        code=code,
    )


async def _oidc_subject(token: str) -> str:
    """Validate an RFC 9068 access token and return its subject."""
    try:
        signing_key = await asyncio.to_thread(_JWKS_CLIENT.get_signing_key_from_jwt, token)
    except (jwt.PyJWKClientConnectionError, OSError, TimeoutError):
        _deny("OIDC signing keys are unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
    except jwt.PyJWTError:
        _deny("invalid access token", status.HTTP_401_UNAUTHORIZED)

    try:
        decoded = jwt.decode_complete(
            token,
            signing_key.key,
            algorithms=[_ALGORITHM],
            issuer=_ISSUER,
            audience=_AUDIENCE,
            leeway=10,
            options={"require": ["iss", "aud", "sub", "iat", "exp"]},
        )
    except jwt.PyJWTError:
        _deny("invalid or expired access token", status.HTTP_401_UNAUTHORIZED)

    # RFC 9068 section 4: the typed header separates access tokens from ID tokens.
    if str(decoded["header"].get("typ", "")).lower() not in {"at+jwt", "application/at+jwt"}:
        _deny("an RFC 9068 access token is required", status.HTTP_401_UNAUTHORIZED)

    claims = decoded["payload"]
    scope = claims.get("scope")
    if not isinstance(scope, str) or _REQUIRED_SCOPE not in scope.split():
        _deny(f"access token lacks the {_REQUIRED_SCOPE} scope", status.HTTP_403_FORBIDDEN)
    subject = claims["sub"]
    if not isinstance(subject, str) or not subject.strip():
        _deny("access token has no subject", status.HTTP_401_UNAUTHORIZED)
    return subject


async def _internal_user(subject: str):
    from litellm.proxy import proxy_server

    try:
        # First use creates the user from `default_internal_user_params`.
        user = await get_user_object(
            user_id=subject,
            prisma_client=proxy_server.prisma_client,
            user_api_key_cache=proxy_server.user_api_key_cache,
            user_id_upsert=True,
        )
    except ValueError:
        _deny("user lookup failed", status.HTTP_503_SERVICE_UNAVAILABLE)
    if user is None or not user.models:
        # LiteLLM treats an empty model list as unrestricted and skips budget
        # checks for zero-cost models, so users stay blocked until an
        # administrator assigns an explicit model policy.
        _deny("user has no model policy", status.HTTP_403_FORBIDDEN)
    return user


def _user_auth(user) -> UserAPIKeyAuth:
    return UserAPIKeyAuth(
        user_id=user.user_id,
        user_email=user.user_email,
        user_role=LitellmUserRoles.INTERNAL_USER,
        # The Internal User is the human; pin the OpenAI `user` field to the
        # same subject so a client-supplied value cannot open a second identity.
        end_user_id=user.user_id,
        allowed_routes=[
            LiteLLMRoutes.openai_routes.name,
            LiteLLMRoutes.model_info_routes.name,
            # OpenAI model retrieval; LiteLLM scopes it to the user's models.
            "/v1/models/*",
            "/models/*",
        ],
        models=list(user.models),
        user_spend=user.spend,
        user_max_budget=user.max_budget,
        user_tpm_limit=user.tpm_limit,
        user_rpm_limit=user.rpm_limit,
    )


def _require_native_checks() -> None:
    """Refuse every credential unless LiteLLM's enforcement is delegated.

    With a custom-auth hook configured, LiteLLM skips its common model and
    budget checks for every credential, native keys included, unless
    ``custom_auth_run_common_checks`` is set. ``enable_post_custom_auth_checks``
    covers per-model budgets and fallbacks for tokens resolved here.
    """
    from litellm.proxy import proxy_server

    if (
        proxy_server.general_settings.get("custom_auth_run_common_checks") is not True
        or getattr(litellm, "enable_post_custom_auth_checks", False) is not True
    ):
        raise ProxyException(
            message="custom_auth_run_common_checks and enable_post_custom_auth_checks must be true",
            type=ProxyErrorTypes.internal_server_error,
            param=None,
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


async def user_api_key_auth(request: Request, api_key: str | None) -> UserAPIKeyAuth | None:
    """Resolve an OIDC access token; defer anything else to LiteLLM."""
    _require_native_checks()
    if not isinstance(api_key, str) or not api_key:
        return None
    try:
        jwt.get_unverified_header(api_key)
    except jwt.PyJWTError:
        return None  # Not a JWT: LiteLLM's native authentication decides.
    return _user_auth(await _internal_user(await _oidc_subject(api_key)))

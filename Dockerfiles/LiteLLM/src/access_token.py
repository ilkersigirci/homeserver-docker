"""RFC 9068 access-token checks that LiteLLM's JWT auth leaves to the deployment.

LiteLLM verifies the signature, issuer, audience, and an ``exp`` when present;
``jwt-auth.patch`` adds the ``typ: at+jwt`` header check. This
``litellm_jwtauth.custom_validate`` hook requires the ``exp`` and ``sub``
claims (sections 2.2 and 4) and the ``llm:invoke`` permission in the
space-delimited ``scope`` claim (section 2.2.3).
"""

from typing import Literal

from fastapi import HTTPException, status

REQUIRED_SCOPE = "llm:invoke"


def validate_claims(claims: dict) -> Literal[True]:
    if "exp" not in claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "access token has no expiry")
    # LiteLLM treats any non-None `sub` as a user id, but skips the user lookup for
    # an empty one, which would leave the token without the user's limits.
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "access token has no subject")
    scope = claims.get("scope")
    if not isinstance(scope, str) or REQUIRED_SCOPE not in scope.split():
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"access token lacks the {REQUIRED_SCOPE} scope")
    return True

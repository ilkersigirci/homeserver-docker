"""Verify /key/delete evicts a deleted key on every worker, not only the handling one."""

import asyncio
from typing import Final
from unittest.mock import AsyncMock, patch

from litellm.proxy._types import (
    LiteLLM_VerificationToken,
    LitellmUserRoles,
    UserAPIKeyAuth,
    hash_token,
)
from litellm.proxy.common_utils.user_api_key_cache import UserApiKeyCache
from litellm.proxy.management_endpoints.key_management_endpoints import (
    delete_verification_tokens,
)


async def main() -> None:
    hashed_token: Final = hash_token("sk-key-delete-check")
    key_row: Final = LiteLLM_VerificationToken(token=hashed_token, user_id="user-check", key_alias="check")
    prisma_client: Final = AsyncMock()
    prisma_client.db.litellm_verificationtoken.find_many = AsyncMock(return_value=[key_row])
    prisma_client.db.litellm_jwtkeymapping.find_many = AsyncMock(return_value=[])
    prisma_client.delete_data = AsyncMock(return_value=[hashed_token])
    cache: Final = UserApiKeyCache()
    cache.set_cache(key=hashed_token, value=UserAPIKeyAuth(token=hashed_token, user_id="user-check"))
    broadcast: Final[list[str]] = []

    async def publish(cache_key: str, **_: object) -> None:
        broadcast.append(cache_key)

    with (
        patch("litellm.proxy.proxy_server.prisma_client", prisma_client),
        patch("litellm.proxy.auth.auth_checks.publish_auth_cache_invalidation", publish),
    ):
        await delete_verification_tokens(
            tokens=["sk-key-delete-check"],
            user_api_key_cache=cache,
            user_api_key_dict=UserAPIKeyAuth(user_role=LitellmUserRoles.PROXY_ADMIN),
        )

    assert cache.get_cache(key=hashed_token) is None
    # Other workers drop their cached copy when the eviction is broadcast.
    assert broadcast == [hashed_token], broadcast
    print("Key delete eviction checks passed")


if __name__ == "__main__":
    asyncio.run(main())

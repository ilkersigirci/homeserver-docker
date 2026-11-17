"""Verify the files_settings backend learns the caller from the authenticated key alone.

A caller's OpenAI SDK calls the real file routes, which call the backend through the
provider's OpenAI SDK. Only auth and the backend are fakes. Client-header forwarding
is on, the setting under which a caller's own headers travel furthest.
"""

import asyncio
import json
from typing import Any, Final
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from openai import AsyncOpenAI

import litellm
import verify_files_extra_fields as files
from litellm.files.main import openai_files_instance
from litellm.proxy import proxy_server
from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.openai_files_endpoints import common_utils, files_endpoints

PREFIX = "x-litellm-user_api_key_"
# What a caller sends to pose as someone else. None of it may reach the backend.
SPOOF = {
    "x-litellm-user_api_key_user_id": "victim",
    "X-LiteLLM-User_Api_Key_Team_Id": "victim-team",
    "x-litellm-user_api_key_auth_metadata": '{"service_account_id": "victim"}',
    "x-litellm-user_api_key_user_email": "victim@example.test",
    "X-Files-Access-Mode": "admin",
    "X-Client-Trace": "client-trace",
}
# files.check uploads under a team's enforced expiry.
TEAM = {"enforced_file_expires_after": {"anchor": "created_at", "seconds": 7200}}
# Each key, and exactly the user information the backend must receive for it: its
# user_id, team_id and metadata, nothing else. The keys also carry details that are not
# sent: an email, and non-ASCII aliases httpx refuses in a header.
CALLERS: tuple[tuple[UserAPIKeyAuth, dict[str, Any]], ...] = (
    (
        UserAPIKeyAuth(
            api_key="sk-user",
            user_id="real-user",
            user_email="user@example.test",
            key_alias="İlker dizüstü",
            team_id="user-team",
            team_alias="Ar-Ge Şube",
            team_metadata=TEAM,
        ),
        {"user_id": "real-user", "team_id": "user-team", "auth_metadata": {}},
    ),
    (
        UserAPIKeyAuth(
            api_key="sk-service",
            key_alias="Arşiv servisi",
            team_id="real-team",
            metadata={"service_account_id": "real-service"},
            team_metadata=TEAM,
        ),
        {"team_id": "real-team", "auth_metadata": {"service_account_id": "real-service"}},
    ),
    # A key with no user or team: the spoofed values must not fill the gaps.
    (UserAPIKeyAuth(api_key="sk-bare", team_metadata=TEAM), {"auth_metadata": {}}),
)
# Headers an administrator configures for the backend. The ordinary one is sent;
# the user-information one is not, since only the authenticated key may supply it.
CONFIGURED = {"x-config-trace": "configured", f"{PREFIX}team_id": "victim-team"}


def user_information(request: httpx.Request) -> dict[str, Any]:
    found: dict[str, Any] = {
        name.removeprefix(PREFIX): value for name, value in request.headers.items() if name.startswith(PREFIX)
    }
    if "auth_metadata" in found:
        found["auth_metadata"] = json.loads(found["auth_metadata"])
    return found


async def check_caller(auth: UserAPIKeyAuth, expected: dict[str, Any], configured: bool = False) -> int:
    """Every file operation as this key. configured: the backend also gets the ordinary CONFIGURED header."""
    app = FastAPI()
    app.include_router(files_endpoints.router)
    app.dependency_overrides[user_api_key_auth] = lambda: auth
    files.sent.clear()
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(files.backend)) as backend_http,
        httpx.AsyncClient(transport=httpx.ASGITransport(app)) as proxy_http,
        AsyncOpenAI(
            api_key=files.BACKEND["api_key"], base_url=files.BACKEND["api_base"], http_client=backend_http
        ) as provider,
        AsyncOpenAI(
            api_key=str(auth.api_key),
            base_url="http://proxy.check/v1",
            http_client=proxy_http,
            default_headers=SPOOF,
            max_retries=0,
        ) as client,
    ):

        def provider_client(*, api_key: str, api_base: str, **_kwargs: Any) -> AsyncOpenAI:
            assert (api_base, api_key) == (files.BACKEND["api_base"], files.BACKEND["api_key"])
            return provider

        with patch.object(openai_files_instance, "get_openai_client", provider_client):
            # Upload, retrieve, content, raw content, list and delete.
            await files.check(client)
            async with client.files.with_streaming_response.content(files.FILE["id"]) as streamed:
                assert await streamed.read() == files.PARSED
    for request in files.sent:
        operation = (request.method, request.url.path)
        found = user_information(request)
        assert found == expected, (operation, found)
        assert request.headers.get_list("authorization") == [f"Bearer {files.BACKEND['api_key']}"], operation
        assert not any(name.startswith("x-files-") or name == "x-client-trace" for name in request.headers), operation
        assert request.headers.get("x-config-trace") == ("configured" if configured else None), operation
    return len(files.sent)


def check_helper() -> None:
    auth, _ = CALLERS[0]
    # A provider without a files_settings entry gets no user information.
    for config in (None, [{"custom_llm_provider": "azure", "api_base": "http://other.check"}]):
        files_endpoints.files_config = config
        data: dict[str, Any] = {"extra_query": {}}
        files_endpoints.add_user_information_headers(data=data, user_api_key_dict=auth, custom_llm_provider="openai")
        assert data == {"extra_query": {}}, data
    # Headers the proxy already set for the provider, such as traceparent, are kept.
    files_endpoints.files_config = [dict(files.BACKEND)]
    traced: dict[str, Any] = {"extra_headers": {"traceparent": "00-trace"}}
    files_endpoints.add_user_information_headers(data=traced, user_api_key_dict=auth, custom_llm_provider="openai")
    assert traced["extra_headers"]["traceparent"] == "00-trace", traced
    assert traced["extra_headers"][f"{PREFIX}user_id"] == "real-user", traced


async def check_configured_headers() -> int:
    """Headers merged in from configuration neither replace nor forge the user information."""
    auth, expected = CALLERS[0]
    # From the files_settings entry, whose own dict must come through unchanged.
    entry: Final = {**files.BACKEND, "extra_headers": dict(CONFIGURED)}
    files_endpoints.set_files_config([entry])
    requests = await check_caller(auth, expected, configured=True)
    assert entry["extra_headers"] == CONFIGURED, entry["extra_headers"]
    # From team credentials.
    files_endpoints.set_files_config([dict(files.BACKEND)])
    with patch.object(common_utils, "get_team_provider_credentials", lambda **_: {"extra_headers": dict(CONFIGURED)}):
        requests += await check_caller(auth, expected, configured=True)
    return requests


async def main() -> None:
    try:
        check_helper()
        files_endpoints.set_files_config([dict(files.BACKEND)])
        with patch.dict(proxy_server.general_settings, {"forward_client_headers_to_llm_api": True}):
            requests = sum([await check_caller(auth, expected) for auth, expected in CALLERS])
            requests += await check_configured_headers()
            files_endpoints.set_files_config([dict(files.BACKEND)])
            # add_user_information_to_llm_headers is for model calls: it adds nothing here.
            with patch.object(litellm, "add_user_information_to_llm_headers", True):
                requests += await check_caller(*CALLERS[0])
    finally:
        files_endpoints.files_config = None
    print(f"files ownership: {requests} backend requests carried only the authenticated key's details")


if __name__ == "__main__":
    asyncio.run(main())

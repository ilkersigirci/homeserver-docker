"""Verify provider-only file calls use files_settings, like file create does, and
that file content forwards `raw` to that backend."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import patch

import httpx
from fastapi import Response
from openai import AsyncOpenAI
from starlette.requests import Request

import litellm
from litellm.files.main import openai_files_instance
from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy.openai_files_endpoints import common_utils, files_endpoints
from litellm.proxy.openai_files_endpoints.file_content_streaming_handler import (
    FileContentStreamingHandler,
)

FILES_BACKEND = {
    "custom_llm_provider": "openai",
    "api_base": "http://files-backend.check/v1",
    "api_key": "files-backend-key",
}
TEAM_DEPLOYMENT = {
    "custom_llm_provider": "openai",
    "api_base": "http://team-deployment.check/v1",
    "api_key": "team-deployment-key",
}


class _Captured(Exception):
    """Stops the endpoint once the provider call's arguments are recorded."""


def _request(method: str, path: str, query: bytes = b"") -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("localhost", 4000),
        },
        receive,
    )


def _call(
    endpoint: Callable[..., Awaitable[object]], method: str, path: str, **kwargs: str
) -> Callable[[], Awaitable[object]]:
    return lambda: endpoint(
        request=_request(method, path),
        fastapi_response=Response(),
        user_api_key_dict=UserAPIKeyAuth(),
        **kwargs,
    )


async def _provider_calls() -> dict[str, dict[str, Any]]:
    """Run retrieve, content, delete, and list; return each provider call's kwargs."""
    calls: dict[str, dict[str, Any]] = {}

    def record(name: str) -> Callable[..., Awaitable[None]]:
        async def provider_call(**kwargs: Any) -> None:
            calls[name] = kwargs.get("data", kwargs)
            raise _Captured

        return provider_call

    file_id = "file-files-settings-check"
    endpoints = {
        "retrieve": _call(
            files_endpoints.get_file, "GET", f"/v1/files/{file_id}", file_id=file_id
        ),
        "content": _call(
            files_endpoints.get_file_content,
            "GET",
            f"/v1/files/{file_id}/content",
            file_id=file_id,
        ),
        "delete": _call(
            files_endpoints.delete_file,
            "DELETE",
            f"/v1/files/{file_id}",
            file_id=file_id,
        ),
        "list": _call(files_endpoints.list_files, "GET", "/v1/files"),
    }
    with (
        patch.object(
            common_utils,
            "get_team_provider_credentials",
            lambda **_kwargs: dict(TEAM_DEPLOYMENT),
        ),
        patch.object(litellm, "afile_retrieve", record("retrieve")),
        # OpenAI file content streams, so it never reaches litellm.afile_content.
        patch.object(
            FileContentStreamingHandler,
            "get_streaming_file_content_response",
            record("content"),
        ),
        patch.object(litellm, "afile_delete", record("delete")),
        patch.object(litellm, "afile_list", record("list")),
    ):
        for name, call in endpoints.items():
            try:
                await call()
            except Exception:  # the endpoint wraps _Captured in its own error
                pass
            assert name in calls, f"{name} never reached its provider call"
    return calls


def _assert_routed_to(
    backend: dict[str, str], calls: dict[str, dict[str, Any]]
) -> None:
    for name, data in calls.items():
        routed = (data.get("api_base"), data.get("api_key"))
        assert routed == (backend["api_base"], backend["api_key"]), (name, routed[0])


async def _assert_raw_forwarded() -> None:
    """Run the endpoint, afile_content, and the OpenAI SDK; only the network is mocked."""
    file_id = "file-raw-check"
    path = f"/v1/files/{file_id}/content"
    upload = b"%PDF original upload"
    sent: list[httpx.Request] = []

    def backend(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=upload)

    async def download(query: bytes) -> bytes:
        response = await files_endpoints.get_file_content(
            request=_request("GET", path, query),
            fastapi_response=Response(),
            user_api_key_dict=UserAPIKeyAuth(),
            file_id=file_id,
        )
        return b"".join([chunk async for chunk in response.body_iterator])

    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as session:

        def sdk_client(*, api_key: str, api_base: str, **_kwargs: Any) -> AsyncOpenAI:
            return AsyncOpenAI(api_key=api_key, base_url=api_base, http_client=session)

        with patch.object(openai_files_instance, "get_openai_client", sdk_client):
            assert await download(b"raw=true&other=1") == upload
            assert await download(b"") == upload

    url = f"{FILES_BACKEND['api_base']}/files/{file_id}/content"
    assert [str(request.url) for request in sent] == [f"{url}?raw=true", url], sent
    assert sent[0].headers["authorization"] == f"Bearer {FILES_BACKEND['api_key']}"


async def main() -> None:
    # files_settings check: its entry wins over the team deployment's credentials.
    files_endpoints.set_files_config([dict(FILES_BACKEND)])
    try:
        _assert_routed_to(FILES_BACKEND, await _provider_calls())
        await _assert_raw_forwarded()
    finally:
        files_endpoints.files_config = None

    # Without files_settings, provider-only calls keep the team credentials.
    _assert_routed_to(TEAM_DEPLOYMENT, await _provider_calls())

    print("files_settings routing and raw content: ok")


if __name__ == "__main__":
    asyncio.run(main())

"""Verify provider-only file calls use files_settings, like file create does."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import patch

from fastapi import Response
from starlette.requests import Request

import litellm
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


def _request(method: str, path: str) -> Request:
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
            "query_string": b"",
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


async def main() -> None:
    # files_settings check: its entry wins over the team deployment's credentials.
    files_endpoints.set_files_config([dict(FILES_BACKEND)])
    try:
        _assert_routed_to(FILES_BACKEND, await _provider_calls())
    finally:
        files_endpoints.files_config = None

    # Without files_settings, provider-only calls keep the team credentials.
    _assert_routed_to(TEAM_DEPLOYMENT, await _provider_calls())

    print("files_settings routing: ok")


if __name__ == "__main__":
    asyncio.run(main())

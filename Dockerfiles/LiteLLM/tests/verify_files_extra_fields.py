"""Verify files-api's own fields pass through the files endpoints, both ways.

A caller's OpenAI SDK calls the proxy routes, which call the files_settings
backend through the provider's OpenAI SDK. Only auth and the backend are fakes.
"""

import asyncio
from typing import Any
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from openai import AsyncOpenAI
from starlette.requests import Request

from litellm.files.main import openai_files_instance
from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.openai_files_endpoints import files_endpoints

BACKEND = {
    "custom_llm_provider": "openai",
    "api_base": "http://files-backend.check/v1",
    "api_key": "files-backend-key",
}
UPLOAD = b"Original upload\n"
PARSED = b'{"text": "Original upload"}'
METADATA = {"source": "archive", "tags": ["a", "b"]}
FILE = {
    "id": "file-extra-fields-check",
    "object": "file",
    "bytes": len(UPLOAD),
    "created_at": 1700000000,
    "filename": "document.txt",
    "purpose": "user_data",
    "metadata": METADATA,  # not an OpenAI file field
}

sent: list[httpx.Request] = []
form: dict[str, list[str]] = {}


async def backend(request: httpx.Request) -> httpx.Response:
    sent.append(request)
    if request.method == "POST":
        body = await request.aread()

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        headers = [(key.lower(), value) for key, value in request.headers.raw]
        async with Request({"type": "http", "headers": headers}, receive).form() as fields:
            form.clear()
            form.update({key: fields.getlist(key) for key in fields if key != "file"})
    if request.url.path.endswith("/content"):
        return httpx.Response(200, content=UPLOAD if "raw" in request.url.params else PARSED)
    if request.method == "DELETE":
        return httpx.Response(200, json={"id": FILE["id"], "object": "file", "deleted": True})
    if request.method == "GET" and request.url.path.endswith("/files"):
        return httpx.Response(200, json={"object": "list", "data": [FILE], "has_more": False})
    return httpx.Response(200, json=FILE)


async def check(client: AsyncOpenAI) -> None:
    # Upload: extra_body reaches the backend as form fields in the SDK's encoding.
    uploaded = await client.files.create(
        file=("document.txt", UPLOAD),
        purpose="user_data",
        expires_after={"anchor": "created_at", "seconds": 3600},
        extra_body={
            "language": "tr",
            "metadata": METADATA,
            # Real auth rejects api_base in a body; past auth (stubbed here), a
            # field is still backend data, never the LiteLLM call's api_base.
            "api_base": "http://elsewhere.check/v1",
            # The proxy's own fields stay in the proxy.
            "custom_llm_provider": "openai",
            "litellm_metadata": {"tags": ["proxy-only"]},
        },
        extra_query={"parse_method": "ocr"},
    )
    assert form == {
        "purpose": ["user_data"],
        "expires_after[anchor]": ["created_at"],
        "expires_after[seconds]": ["7200"],  # the team's enforced expiry still wins
        "language": ["tr"],
        "metadata[source]": ["archive"],
        "metadata[tags][]": ["a", "b"],
        "api_base": ["http://elsewhere.check/v1"],
    }, form
    assert sent[-1].url.params == httpx.QueryParams({"parse_method": "ocr"})
    assert uploaded.model_dump()["metadata"] == METADATA

    # Reads and delete: extra_query reaches the backend as query parameters.
    file_id = FILE["id"]
    query = {"language": "tr", "metadata": {"tags": ["a", "b"]}, "provider": "openai"}
    forwarded = httpx.QueryParams(
        [("language", "tr"), ("metadata[tags][]", "a"), ("metadata[tags][]", "b")]
    )

    retrieved = await client.files.retrieve(file_id, extra_query=query)
    assert retrieved.model_dump()["metadata"] == METADATA
    assert sent[-1].url.params == forwarded, sent[-1].url

    assert (await client.files.content(file_id, extra_query=query)).content == PARSED
    assert sent[-1].url.params == forwarded, sent[-1].url

    raw = await client.files.content(file_id, extra_query={"raw": "true"})
    assert raw.content == UPLOAD
    assert sent[-1].url.params == httpx.QueryParams({"raw": "true"})

    listed = await client.files.list(
        purpose="user_data", limit=5, after="file-0", extra_query=query
    )
    assert listed.data[0].model_dump()["metadata"] == METADATA
    assert sent[-1].url.params == forwarded.merge(
        {"purpose": "user_data", "limit": "5", "after": "file-0"}
    ), sent[-1].url

    assert (await client.files.delete(file_id, extra_query=query)).deleted
    assert sent[-1].url.params == forwarded, sent[-1].url

    # Without extra fields, the backend gets the request it got before.
    await client.files.retrieve(file_id)
    assert not sent[-1].url.query, sent[-1].url


async def main() -> None:
    app = FastAPI()
    app.include_router(files_endpoints.router)
    auth = UserAPIKeyAuth(
        api_key="sk-proxy-check",
        team_metadata={
            "enforced_file_expires_after": {"anchor": "created_at", "seconds": 7200}
        },
    )
    app.dependency_overrides[user_api_key_auth] = lambda: auth
    files_endpoints.set_files_config([dict(BACKEND)])
    try:
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(backend)) as backend_http,
            httpx.AsyncClient(transport=httpx.ASGITransport(app)) as proxy_http,
            AsyncOpenAI(
                api_key=BACKEND["api_key"],
                base_url=BACKEND["api_base"],
                http_client=backend_http,
            ) as provider,
            AsyncOpenAI(
                api_key="sk-proxy-check",
                base_url="http://proxy.check/v1",
                http_client=proxy_http,
            ) as client,
        ):

            def provider_client(
                *, api_key: str, api_base: str, **_kwargs: Any
            ) -> AsyncOpenAI:
                assert (api_base, api_key) == (BACKEND["api_base"], BACKEND["api_key"])
                return provider

            with patch.object(
                openai_files_instance, "get_openai_client", provider_client
            ):
                await check(client)
    finally:
        files_endpoints.files_config = None

    print("files extra fields: ok")


if __name__ == "__main__":
    asyncio.run(main())

"""Verify native background Responses return queued results in the OSS image."""

import asyncio
import json
from unittest.mock import patch

from fastapi import Response
from starlette.requests import Request

from litellm.proxy.auth.user_api_key_auth import UserAPIKeyAuth
from litellm.proxy.common_request_processing import ProxyBaseLLMRequestProcessing
from litellm.proxy.response_api_endpoints.endpoints import (
    cancel_response,
    get_response,
    responses_api,
)
from litellm.types.llms.openai import ResponsesAPIResponse


def _request(
    body: dict[str, object],
    *,
    method: str = "POST",
    path: str = "/v1/responses",
) -> Request:
    content = json.dumps(body).encode()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": content, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1),
            "server": ("localhost", 4000),
        },
        receive,
    )


async def main() -> None:
    queued = ResponsesAPIResponse(
        id="resp_background_check",
        created_at=1,
        model="background-check",
        object="response",
        output=[],
        status="queued",
    )
    calls: list[dict[str, object]] = []

    async def process(
        processor: ProxyBaseLLMRequestProcessing,
        **_kwargs: object,
    ) -> ResponsesAPIResponse:
        calls.append(dict(processor.data))
        if "response_id" in processor.data:
            return queued.model_copy(update={"id": "resp_reencrypted"})
        return queued

    with patch.object(
        ProxyBaseLLMRequestProcessing,
        "base_process_llm_request",
        process,
    ):
        result = await responses_api(
            request=_request(
                {
                    "model": "background-check",
                    "input": "Check background forwarding.",
                    "background": True,
                }
            ),
            fastapi_response=Response(),
            user_api_key_dict=UserAPIKeyAuth(),
        )

        assert result is queued
        response_id = "resp_client_visible"
        for endpoint, method, path in (
            (
                get_response,
                "GET",
                f"/v1/responses/{response_id}",
            ),
            (cancel_response, "POST", f"/v1/responses/{response_id}/cancel"),
        ):
            result = await endpoint(
                response_id=response_id,
                request=_request({}, method=method, path=path),
                fastapi_response=Response(),
                user_api_key_dict=UserAPIKeyAuth(),
            )
            assert result.id == response_id

    assert len(calls) == 3
    print("Native background Responses OSS check passed")


if __name__ == "__main__":
    asyncio.run(main())

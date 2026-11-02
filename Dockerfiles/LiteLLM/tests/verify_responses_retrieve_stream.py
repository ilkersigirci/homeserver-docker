"""Verify retrieve streams a stored Response's events from the provider."""

import asyncio
import json
from unittest.mock import patch

import httpx
import litellm
from fastapi import Response
from starlette.requests import Request

from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from litellm.proxy.auth.user_api_key_auth import UserAPIKeyAuth
from litellm.proxy.common_request_processing import ProxyBaseLLMRequestProcessing
from litellm.proxy.response_api_endpoints.endpoints import get_response

DELTA = {
    "type": "response.output_text.delta",
    "sequence_number": 3,
    "item_id": "msg_1",
    "output_index": 0,
    "content_index": 0,
    "delta": "resumed",
    "logprobs": [],
}
COMPLETED = {
    "type": "response.completed",
    "sequence_number": 4,
    "response": {
        "id": "resp_provider",
        "created_at": 1,
        "model": "stored",
        "object": "response",
        "output": [],
        "status": "completed",
    },
}


async def _check_route_forwards_the_parameters() -> None:
    forwarded: dict[str, object] = {}

    async def process(
        processor: ProxyBaseLLMRequestProcessing,
        **_kwargs: object,
    ) -> Response:
        forwarded.update(processor.data)
        return Response()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    path = "/v1/responses/resp_client_visible"
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"stream=true&starting_after=2",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("localhost", 4000),
        },
        receive,
    )
    with patch.object(
        ProxyBaseLLMRequestProcessing, "base_process_llm_request", process
    ):
        await get_response(
            response_id="resp_client_visible",
            request=request,
            fastapi_response=Response(),
            user_api_key_dict=UserAPIKeyAuth(),
        )

    assert forwarded["stream"] is True
    assert forwarded["starting_after"] == "2"


async def _check_handler_streams_the_provider_events() -> None:
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(
                f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                for event in (DELTA, COMPLETED)
            ),
        )

    client = AsyncHTTPHandler()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    stream = await litellm.aget_responses(
        response_id="resp_provider",
        custom_llm_provider="openai",
        api_base="http://provider/v1",
        api_key="key",
        stream=True,
        starting_after="2",
        client=client,
    )
    events = [event async for event in stream]

    assert [event.type for event in events] == [DELTA["type"], COMPLETED["type"]]
    assert events[0].delta == "resumed"
    assert requests[0].method == "GET"
    assert requests[0].url.path.endswith("/resp_provider")
    assert dict(requests[0].url.params) == {"stream": "true", "starting_after": "2"}


async def main() -> None:
    await _check_route_forwards_the_parameters()
    await _check_handler_streams_the_provider_events()
    print("Responses retrieve stream check passed")


if __name__ == "__main__":
    asyncio.run(main())

"""Check wildcard Responses routing against a local HTTP transport at build time."""

import json
from unittest.mock import patch

import httpx
import litellm
from litellm.llms.custom_httpx.http_handler import HTTPHandler
from litellm.llms.manus.responses.transformation import ManusResponsesAPIConfig
from litellm.llms.openai.responses.transformation import OpenAIResponsesAPIConfig
from litellm.llms.volcengine.responses.transformation import (
    VolcEngineResponsesAPIConfig,
)


def verify_request(capability: bool | None, stream: bool) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        response = {
            "id": "resp_streaming_check",
            "object": "response",
            "created_at": 1,
            "model": body["model"],
            "status": "completed",
            "output": [],
            "usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1},
        }
        if body.get("stream"):
            event = {
                "type": "response.completed",
                "sequence_number": 0,
                "response": response,
            }
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json=response)

    router = litellm.Router(
        model_list=[
            {
                "model_name": "graphs/*",
                "litellm_params": {
                    "model": "openai/*",
                    "api_base": "https://graphs.invalid/v1",
                    "api_key": "DUMMY",
                },
                "model_info": {"supports_native_streaming": capability},
            }
        ],
        num_retries=0,
    )
    # Router.responses discards its client argument, so inject the HTTP client
    # where the handler acquires it. Routing and request encoding remain real.
    with (
        httpx.Client(transport=httpx.MockTransport(upstream)) as client,
        patch(
            "litellm.llms.custom_httpx.llm_http_handler._get_httpx_client",
            return_value=HTTPHandler(client=client),
        ),
    ):
        # Neither graph exists in LiteLLM's model cost map or configuration.
        for model in ("new-graph", "another-new-graph"):
            result = router.responses(
                model=f"graphs/{model}",
                input="Check streaming.",
                store=False,
                stream=stream,
            )
            if stream:
                list(result)
            body = json.loads(requests[-1].content)
            assert requests[-1].url == "https://graphs.invalid/v1/responses"
            assert body["model"] == model
            assert bool(body.get("stream")) is (stream and capability is True), body
            assert "supports_native_streaming" not in body
            assert "model_info" not in body
    assert len(requests) == 2


def main() -> None:
    for capability in (True, False, None):
        for stream in (True, False):
            verify_request(capability, stream)

    config = OpenAIResponsesAPIConfig()
    assert config.should_fake_stream("gpt-4o", True, "openai") is False
    assert config.should_fake_stream("o1-pro", True, "openai") is True
    assert config.should_fake_stream("gpt-4o", True, "openai", False) is True
    assert (
        ManusResponsesAPIConfig().should_fake_stream("manus", True, "manus", True)
        is True
    )
    assert (
        VolcEngineResponsesAPIConfig().should_fake_stream(
            "model", True, "volcengine", False
        )
        is False
    )
    print("Wildcard Responses streaming checks passed")


if __name__ == "__main__":
    main()

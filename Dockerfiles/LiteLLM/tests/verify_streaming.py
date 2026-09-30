"""Check wildcard Responses routing against a local HTTP transport at build time."""

import json
from unittest.mock import patch

import httpx
import litellm
from litellm.llms.custom_httpx.http_handler import HTTPHandler

# Absent from LiteLLM's model cost map, which upstream reads as "fake the stream".
_UNKNOWN_MODELS = ("new-graph", "another-new-graph")
# Registered in main(), so the check does not depend on upstream's model catalog.
_KNOWN_MODEL = "registered-model"


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
        for model in (*_UNKNOWN_MODELS, _KNOWN_MODEL):
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
            # An explicit capability decides; unset keeps the upstream decision.
            native = model == _KNOWN_MODEL if capability is None else capability
            assert bool(body.get("stream")) is (stream and native), (model, body)
            assert "supports_native_streaming" not in body
            assert "model_info" not in body
    assert len(requests) == len(_UNKNOWN_MODELS) + 1


def main() -> None:
    # A known model without the capability field streams natively upstream.
    litellm.register_model({f"openai/{_KNOWN_MODEL}": {"litellm_provider": "openai", "mode": "responses"}})
    for capability in (True, False, None):
        for stream in (True, False):
            verify_request(capability, stream)
    print("Wildcard Responses streaming checks passed")


if __name__ == "__main__":
    main()

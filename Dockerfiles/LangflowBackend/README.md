# Langflow through the OpenAI API

Bifrost is the only public OpenAI-compatible API. Langflow keeps its existing
`POST /api/v1/responses` route behind Bifrost; it does not expose parallel
`/v1` routes or reimplement Chat Completions and model discovery.

```text
OpenAI client or Open WebUI
        |
        | /v1/responses
        v
      Bifrost
        |
        | /api/v1/responses
        v
      Langflow
```

## Why a custom image

Stock Langflow 1.11.4 exposes a Responses-shaped endpoint but is not wire
compatible with OpenAI clients:

- `input` accepts only a string, so canonical message arrays forwarded by
  Bifrost fail with HTTP 422;
- authentication accepts `x-api-key`, not the standard Bearer header;
- streaming emits legacy `response.chunk` data, duplicates the first text
  delta, and terminates with `[DONE]` instead of canonical typed events.

A Bifrost path override changes only the URL, while passthrough forwards these
incompatibilities unchanged. The thin custom image therefore patches Langflow's
existing endpoint instead of adding another API facade.

The custom backend image applies
[`openai-responses.patch`](../../Dockerfiles/LangflowBackend/patches/openai-responses.patch)
to Langflow's existing endpoint. The patch is limited to two upstream modules
and adds only what the gateway needs:

- canonical string or text-message-array `input`, plus `instructions`;
- OpenAI-standard `Authorization: Bearer` authentication in addition to
  Langflow's `x-api-key`;
- canonical Responses SSE events with monotonic sequence numbers;
- token events as the authoritative text stream, preventing the duplicated
  first delta described in
  [langflow-ai/langflow#10719](https://github.com/langflow-ai/langflow/issues/10719).

The flow must contain Chat Input and Chat Output components. Input is text-only,
and caller-provided tools are not supported by Langflow's endpoint.

## Bifrost provider

Create an OpenAI-based custom provider named `Langflow`. Keep the Langflow API
key in Bifrost's environment and configure both Responses request types to use
Langflow's actual path:

```json
{
  "providers": {
    "Langflow": {
      "keys": [
        {
          "name": "langflow-key",
          "value": "env.LANGFLOW_API_KEY",
          "models": ["FirstFlow"],
          "weight": 1.0
        }
      ],
      "network_config": {
        "base_url": "https://langflow.example.com"
      },
      "custom_provider_config": {
        "base_provider_type": "openai",
        "allowed_requests": {
          "responses": true,
          "responses_stream": true
        },
        "request_path_overrides": {
          "responses": "/api/v1/responses",
          "responses_stream": "/api/v1/responses"
        }
      }
    }
  }
}
```

The path overrides are normal custom provider configuration; no passthrough
route, compatibility conversion, or per-request passthrough header is needed.

Use an explicit provider/model prefix so routing does not depend on model
catalog discovery:

```bash
curl -fsS "https://aigateway.example.com/v1/responses" \
  --no-buffer \
  -H "Authorization: Bearer $BIFROST_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Langflow/FirstFlow",
    "input": "Who are you?",
    "stream": true
  }'
```

## OpenAI client and Open WebUI

Point the standard OpenAI client at Bifrost, not Langflow:

```python
import os

from openai import OpenAI

client = OpenAI(
    api_key=os.environ["BIFROST_API_KEY"],
    base_url="https://aigateway.example.com/v1",
)

for event in client.responses.create(
    model="Langflow/FirstFlow",
    input="Who are you?",
    stream=True,
):
    if event.type == "response.output_text.delta":
        print(event.delta, end="", flush=True)
```

For Open WebUI 0.11 or newer, add an OpenAI connection with the same Bifrost
`/v1` URL and Bifrost API key, set **API type** to **Responses**, and add
`Langflow/FirstFlow` as an explicit model ID. Bifrost cannot discover flows
through Langflow's Responses-only endpoint, so configure model IDs instead of
calling upstream model discovery. Disable tool calling and image input for this
text-only model.

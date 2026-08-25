# Langflow OpenAI Compatibility

Langflow exposes `POST /api/v1/responses`, but implements only a subset of the
OpenAI Responses API:

- `model` must be a flow UUID or its endpoint name, configured under
  **Share → API access → Endpoint Name** in the flow.
- `input` must be a string; message arrays are rejected.
- The flow must contain Chat Input and Chat Output components.
- Custom `tools` are not supported.
- Authentication uses the Langflow `x-api-key` header.

See the [Langflow Responses API documentation](https://docs.langflow.org/api-openai-responses).

## Bifrost incompatibility

Bifrost's normal `/v1/responses` route converts string input into a message
array before sending it to an OpenAI-compatible provider. Langflow consequently
returns `422 Input should be a valid string`. A Bifrost request path override
changes only the URL and cannot prevent this body conversion.

## Stream

Bifrost passthrough streams Langflow's SSE response without buffering when
`stream` is `true`, ending with a completed chunk and `[DONE]`. Langflow 1.11.4
uses noncanonical `response.chunk` events with `delta.content` and duplicates
the first non-empty token. The duplication also occurs when calling Langflow
directly. This is a Langflow limitation, not a Bifrost limitation; Bifrost
forwards the stream unchanged.

## OpenAI client

The native Python client works for non-streaming Responses calls through
Bifrost passthrough:

```python
import os

from openai import OpenAI

client = OpenAI(
    api_key=os.environ["BIFROST_API_KEY"],
    base_url="https://bifrost.example.com/openai_passthrough/v1",
    default_headers={"x-model-provider": "Langflow"},
)

response = client.responses.create(model="FirstFlow", input="Hello")
print(response.output_text)
```

Use `responses.create`, not `chat.completions.create`, and use the flow endpoint
name without the provider prefix. Native client streaming is incompatible with
Langflow's noncanonical events; consume the raw SSE stream instead:

```python
import os

import httpx

with httpx.stream(
    "POST",
    "https://bifrost.example.com/openai_passthrough/v1/responses",
    headers={
        "Authorization": f"Bearer {os.environ['BIFROST_API_KEY']}",
        "x-model-provider": "Langflow",
    },
    json={"model": "FirstFlow", "input": "Hello", "stream": True},
) as response:
    response.raise_for_status()
    for line in response.iter_lines():
        if line.startswith("data: "):
            print(line[6:])
```

## Native Bifrost passthrough

Use Bifrost's [OpenAI passthrough](https://docs.getbifrost.ai/integrations/passthrough)
instead of its normal Responses route. Configure the `Langflow` custom provider
with:

- base provider: `openai`
- base URL: the Langflow URL ending in `/api`
- extra header: `x-api-key: <LANGFLOW_API_KEY>`
- allowed requests: `passthrough` and `passthrough_stream`
- normal `responses` and `responses_stream` disabled
- no Responses path override

Example Bifrost `config.json`:

```json
{
  "$schema": "https://www.getbifrost.ai/schema",
  "providers": {
    "Langflow": {
      "keys": [],
      "network_config": {
        "base_url": "https://langflow.example.com/api",
        "extra_headers": {
          "x-api-key": "<LANGFLOW_API_KEY>"
        }
      },
      "custom_provider_config": {
        "base_provider_type": "openai",
        "is_key_less": true,
        "allowed_requests": {
          "passthrough": true,
          "passthrough_stream": true
        }
      }
    }
  }
}
```

Call it with:

```bash
BIFROST_URL=https://bifrost.example.com
FLOW_NAME=FirstFlow

curl -fsS "$BIFROST_URL/openai_passthrough/v1/responses" \
  -H "Authorization: Bearer $BIFROST_API_KEY" \
  -H "x-model-provider: Langflow" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "'${FLOW_NAME}'",
    "input": "Who are you?",
    "stream": false
  }'
```

Passthrough forwards the body unchanged. Use `FirstFlow`, not
`Langflow/FirstFlow`; the `x-model-provider` header selects Bifrost's provider.
Use the flow UUID if `FirstFlow` has not been saved as the flow endpoint name.

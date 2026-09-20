# Langflow through OpenAI-compatible gateways

Langflow keeps its native `POST /api/v1/responses` route. The custom backend
makes that route compatible with standard OpenAI Responses clients, whether
they call Langflow directly or through a gateway such as LiteLLM. No gateway is
required by the image.

```text
OpenAI client or Open WebUI
        |
        | /v1/responses
        v
Optional OpenAI-compatible gateway
        |
        | /api/v1/responses
        v
      Langflow
```

Langflow does not expose parallel `/v1` routes or implement Chat Completions
and model discovery.

## Why a custom image

Stock Langflow 1.12.0 exposes a Responses-shaped endpoint but is not fully wire
compatible with standard OpenAI clients:

- `input` accepts only a string, so canonical message arrays fail with HTTP 422;
- authentication accepts `x-api-key`, not the standard Bearer header;
- streaming emits legacy `response.chunk` data, duplicates the first text
  delta, and terminates with `[DONE]` instead of canonical typed events.

The custom backend applies
[`openai-responses.patch`](../../Dockerfiles/LangflowBackend/patches/openai-responses.patch)
to Langflow's existing endpoint. The gateway-neutral patch adds:

- canonical string or text-message-array `input`, plus `instructions`;
- OpenAI-standard `Authorization: Bearer` authentication in addition to
  Langflow's `x-api-key`;
- canonical Responses SSE events with monotonic sequence numbers;
- token events as the authoritative text stream, preventing the duplicated
  first delta described in
  [langflow-ai/langflow#10719](https://github.com/langflow-ai/langflow/issues/10719).

The flow must contain Chat Input and Chat Output components. Input is text-only,
and caller-provided tools are not supported by Langflow's endpoint.

## Endpoint contract

Use one of these base URLs:

- Inside this Compose project: `http://langflow-backend:7860/api/v1`
- Through Traefik: `https://langflow.example.com/api/v1`

Send `POST /responses` with a Langflow API key as either
`Authorization: Bearer <key>` or `x-api-key: <key>`. The `model` value is the
Langflow flow name or ID. Gateways must use an explicit model mapping because
Langflow does not expose an OpenAI-compatible `/models` endpoint.

## LiteLLM

### Expose a Langflow flow through LiteLLM

Create an OpenAI-compatible deployment in LiteLLM's Admin UI. The equivalent
static configuration is:

```yaml
model_list:
  - model_name: langflow-first-flow
    litellm_params:
      model: openai/FirstFlow
      api_base: http://langflow-backend:7860/api/v1
      api_key: os.environ/LANGFLOW_API_KEY
```

Store a Langflow API key in the deployment or inject `LANGFLOW_API_KEY` into
LiteLLM. Do not enable `use_chat_completions_api`: Langflow has a native
Responses endpoint and does not expose Chat Completions.

Clients can then use LiteLLM's normal Responses endpoint and its own API key:

```bash
curl -fsS "https://litellm.example.com/v1/responses" \
  --no-buffer \
  -H "Authorization: Bearer $LITELLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "langflow-first-flow",
    "input": "Who are you?",
    "stream": true
  }'
```

### Use LiteLLM from a Langflow flow

Configure an OpenAI-compatible model provider in Langflow with:

- base URL: `http://litellm:4000/v1`
- API key: a LiteLLM virtual or master key
- model: a model alias configured in LiteLLM

The internal `litellm` hostname is explicitly included in Langflow's SSRF
allowlist. Both services share the `t3_proxy` Docker network, so this path does
not depend on public DNS or Traefik.

## OpenAI clients and Open WebUI

Point clients at either LiteLLM's `/v1` URL or Langflow's direct `/api/v1` URL.
Use the Responses API and configure an explicit model ID. Disable tool calling
and image input for Langflow-backed models because this endpoint is text-only.

# Langflow through OpenAI-compatible gateways

Langflow keeps its native `POST /api/v1/responses` route. The custom backend
makes that route compatible with standard OpenAI Responses clients, whether
they call Langflow directly or through a gateway such as LiteLLM.

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

## Image contents

[`openai-responses.patch`](patches/openai-responses.patch) makes stock
Langflow 1.12.0's Responses-shaped endpoint wire compatible with standard
OpenAI clients:

- canonical string or text-message-array `input`, plus `instructions`; stock
  Langflow accepts only a string and rejects message arrays with HTTP 422;
- OpenAI-standard `Authorization: Bearer` authentication in addition to
  Langflow's `x-api-key`;
- canonical typed Responses SSE events with monotonic sequence numbers,
  replacing legacy `response.chunk` data and the `[DONE]` terminator;
- token events as the authoritative text stream, preventing the duplicated
  first delta described in
  [langflow-ai/langflow#10719](https://github.com/langflow-ai/langflow/issues/10719).

The image also installs pinned `lfx-openai`, `lfx-openai-compatible`, and
`langchain-openai`, so these providers work without the host package mount.
The mount remains available for additional bundles.

## Browser login

Traefik's `traefik-oidc-auth` plugin, registered in
[`apps/traefik.yml`](../../apps/traefik.yml), handles Langflow's browser login
through the `langflow-oidc` middleware in
[`gpu_coding.yml`](../../configs/traefik3/rules.specific/gpu_coding.yml). It
runs the authorization-code flow with PKCE, keeps the encrypted session
cookie, refreshes tokens, and sets `Authorization: Bearer <ID token>` on
upstream requests. Langflow's native external auth validates the issuer, the
audience (`LANGFLOW_CLIENT_ID`), and the signature, then provisions the local
user from the token claims. The backend must stay reachable only through
Traefik.

`langflow-responses-rtr` is the exception: `/api/v1/responses` requests that
carry an API key skip browser OIDC so OpenAI clients and LiteLLM can run
saved flows.

Register `https://langflow.<DOMAINNAME>/oidc/callback` in PocketID. The
Langflow client needs login scopes only; flows call LiteLLM with
[personal keys](#use-litellm-from-a-langflow-flow). For another provider,
such as Keycloak, update the middleware's `Provider` settings and
`LANGFLOW_EXTERNAL_AUTH_*` in [`apps/langflow.yml`](../../apps/langflow.yml).

## Endpoint contract

Use one of these base URLs:

- Inside this Compose project: `http://langflow-backend:7860/api/v1`
- Through Traefik: `https://langflow.example.com/api/v1`

Send `POST /responses` with a Langflow API key as either
`Authorization: Bearer <key>` or `x-api-key: <key>`. The `model` value is the
Langflow flow name or ID; the flow must contain Chat Input and Chat Output
components. Langflow exposes no `/v1` routes, Chat Completions, or
OpenAI-compatible `/models` endpoint, so clients and gateways need the
Responses API and an explicit model mapping. Input is text-only and
caller-provided tools are not supported, so disable tool calling and image
input for Langflow-backed models in clients such as Open WebUI.

## LiteLLM

### Use LiteLLM from a Langflow flow

1. Get a [personal LiteLLM virtual key](../LiteLLM/ARCHITECTURE.md#personal-virtual-keys).
2. Configure Langflow's stock **OpenAI Compatible** model provider once with
    Base URL `https://litellm.example.com/v1` and that key. Langflow stores
    both as the user's own global variables and lists the models the key may
    use.

LiteLLM may run on another machine, so use its HTTPS name. That name resolves
to a LAN address, which Langflow blocks by default, so it is listed in
`LANGFLOW_SSRF_ALLOWED_HOSTS`.

**Design choice.** Open WebUI forwards each user's OAuth token to LiteLLM, but
Langflow runs flows server-side (API calls, webhooks, background jobs) where
no user token exists. Acting for users with one shared deployment credential
would need custom trust code in both LiteLLM and Langflow, and that
credential, reachable from flow code, could spend any user's budget. A
personal key uses only native features of both products and can spend only
its owner's budget. The trade-off: each user holds a key.

### Expose a Langflow flow through LiteLLM

Create an OpenAI-compatible deployment in LiteLLM's Admin UI. The equivalent
static configuration is:

```yaml
model_list:
  - model_name: langflow-first-flow
    litellm_params:
      model: openai/FirstFlow
      api_base: https://langflow.example.com/api/v1
      api_key: os.environ/LANGFLOW_API_KEY
```

Leave `use_chat_completions_api` off ([endpoint contract](#endpoint-contract)).
The flow runs as the Langflow API key's owner, so its nested LiteLLM calls use
that owner's key and budget. Control who may call the flow with LiteLLM model
access.

Clients can then use LiteLLM's normal Responses endpoint and their own
credential:

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

### Shared flows

To offer a flow to many users, run it as a service and charge callers a
tariff:

1. In LiteLLM, create a key with no personal owner (e.g. alias
    `shared-flows`), limited to the models the flow uses and capped with
    `max_budget`, `budget_duration`, and RPM/TPM limits. The cap bounds
    runaway or underpriced flows.
2. In Langflow, publish the flow from a dedicated account whose OpenAI
    Compatible provider uses that key, and put that account's Langflow API key
    in the LiteLLM deployment.
3. Set `input_cost_per_token` and `output_cost_per_token` on the deployment.
    Each caller is charged from the usage Langflow reports, which may not
    include every internal call, so price with margin.

Caller spend on the flow model is the chargeback; the `shared-flows` key's
spend is the actual cost. Callers' own model restrictions do not apply inside
the flow.

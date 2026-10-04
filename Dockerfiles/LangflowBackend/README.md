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

- canonical string or message-array `input`, mapped onto Langflow's
  [session chat history](#conversation-history); stock Langflow accepts only a
  string and rejects message arrays with HTTP 422;
- `input_file.file_id` references and caller `instructions` exposed to flow
  components through the run context; flow authors choose how to use them;
- OpenAI-standard `Authorization: Bearer` authentication in addition to
  Langflow's `x-api-key`;
- canonical typed Responses SSE events with monotonic sequence numbers,
  replacing legacy `response.chunk` data and the `[DONE]` terminator;
- token events as the authoritative text stream, preventing the duplicated
  first delta described in
  [langflow-ai/langflow#10719](https://github.com/langflow-ai/langflow/issues/10719).

The image also installs pinned `lfx-openai`, `lfx-openai-compatible`, and
`langchain-openai`, so these providers work without the host package mount.
The mount remains available for additional bundles. The **Responses Input**
and **OpenaiFilesAPI** components are loaded from `/app/custom_components` through
`LANGFLOW_COMPONENTS_PATH`.

### Temporary S3 attachment backport

[`s3-chat-attachments.patch`](patches/s3-chat-attachments.patch) backports the
production changes from [langflow-ai/langflow#15249](https://github.com/langflow-ai/langflow/pull/15249)
(merge commit `d9f36c06f448790b2cad5666407333e5c1d13e1e`, included in source
release 1.12.3). It fixes Playground attachments being silently omitted when
`LANGFLOW_STORAGE_TYPE=s3`, using native storage helpers for images and documents.

**Remove this backport when upgrading the pinned `langflowai/langflow-backend`
image to a published tag that includes #15249.** Confirm the fix is present in
the image's installed LFX code; a GitHub source release alone is insufficient.
Delete the patch and its Dockerfile copy, application, and cleanup entries,
then remove this section. Patch application is strict so an upstream code
change or an already-applied fix stops the build for review.

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
Responses API and an explicit model mapping. Input supports text and file-ID
references. Caller-provided tools and `input_image` are not supported, so
disable tool calling and native image input for Langflow-backed models in
clients such as Open WebUI. Gateways may forward caller headers, so the
endpoint ignores `X-LANGFLOW-GLOBAL-VAR-*` overrides; use Langflow's `/run`
API for per-request variables.

## Conversation history

Langflow [groups chat history by session](https://docs.langflow.org/memory#session-id-and-chat-memory).
A request with `previous_response_id` continues that response's session.
Otherwise the input is the whole conversation. With an `X-Langflow-Session-Id`
header, its value is the session, and the session's stored messages for this
flow and caller are replaced by the request's earlier turns. The session therefore
mirrors the client's conversation, including edited and regenerated messages,
and each of its responses gets a unique ID; concurrent requests in one
conversation and flow can interleave. Any other request starts a new session.

A message-array `input` must end with a user message. Its text becomes the
Chat Input message, so components receive only the current question. Earlier
user and assistant messages are stored in the run's session before the flow
starts, as ordinary Langflow chat history. Messages without text are not
stored; their file IDs remain available through
[Responses Input](#file-references). With end-user session scoping
(`LANGFLOW_SERVING_END_USER_HEADER`) enabled, earlier messages in `input` are
rejected with HTTP 400.

Use the stock **Agent** component's built-in chat memory, which Langflow
[recommends for most flows](https://docs.langflow.org/memory#chat-memory-options).
Connect Chat Input to the Agent's **Input**, through OpenaiFilesAPI when the
flow [uses file references](#use-external-files-and-playground-attachments-in-one-flow),
put the flow's system instructions in **Agent Instructions**, and set
**Number of Chat History Messages** (advanced). The Agent reads the session's earlier
messages, up to that limit, and skips the message it is answering. Playground
runs and API requests therefore get the same history behavior. The Agent
lists only tool-capable models; the **OpenAI Compatible** provider marks
LiteLLM models as tool-capable.

**Message History** reads the same history but also returns the current
message, which Chat Input stores before other components run.

### Caller instructions

Langflow chat history has no system role, so `instructions` and system or
developer messages are not stored. Responses Input's **Instructions** output
joins them in input order; LiteLLM sends leading chat system messages, such
as Open WebUI system prompts, as `instructions`. Flows ignore them unless
the author connects this output; leave it unconnected to keep API runs
identical to Playground runs, where it is empty. To apply them, add a
`{caller_instructions}` variable to a **Prompt Template** that holds the
flow's instructions, connect **Instructions** to it, and connect the prompt
to **Agent Instructions**. Custom Python components can read
`self.ctx.get("responses_instructions", "")`.

## File references

Upload through an external OpenAI-compatible Files API, then include the
returned ID in the Responses request:

```json
{
  "model": "FirstFlow",
  "input": [
    {
      "role": "user",
      "content": [
        {"type": "input_text", "text": "Summarize this document."},
        {"type": "input_file", "file_id": "file-abc123"}
      ]
    }
  ]
}
```

Chat Input receives the last user message's text. Add **Responses →
Responses Input** to a flow; its **Input** output is a JSON object with
these fields:

- `input`: the original validated input string or message array, preserving
  file references and their message associations.
- `file_ids`: IDs from all input messages in order, including repeated IDs.

Connect this output to components that forward the IDs to a compatible model
endpoint or call the Files API's `/v1/files/{file_id}/content` endpoint and
use its response. The receiving endpoint must recognize the same file IDs.
Retrieval, authentication, and content handling are configured by the flow
author. The Responses endpoint performs no file I/O or content extraction.

Custom Python components can access the same original input through
`self.ctx.get("responses_input", [])`. This context belongs to the current
run; resend IDs on requests that need them. In the Playground or other run
endpoints, **Input** returns `{"input": [], "file_ids": []}`.

Only non-empty `file_id` references are accepted. Inline `file_data` and
`file_url` inputs are rejected with HTTP 400. Keep Chat Input and Chat Output
in the flow; Responses Input is an additional component.

### Use external files and Playground attachments in one flow

Add **Responses → OpenaiFilesAPI** between Chat Input and the model:

```mermaid
flowchart LR
    ChatInput[Chat Input] -->|Chat Input| Files[OpenaiFilesAPI]
    Responses[Responses Input] -->|Responses Input| Files
    Files -->|Message| Model[OpenAI or another model]
    Model --> ChatOutput[Chat Output]
```

1. Connect Chat Input's **Chat Message** to OpenaiFilesAPI's **Chat Input**.
2. Connect Responses Input's **Input** JSON output to **Responses Input**.
3. Connect OpenaiFilesAPI's **Message** to the model's **Input**, replacing
    the direct Chat Input connection. Keep the model connected to Chat Output.
4. Set **Files API Base URL**, including `/v1`, and the optional **Files API
    Key** bearer token. Use a Langflow secret global variable for the key.

When `file_ids` contains external references, the component calls
`GET {base_url}/files/{file_id}/content` once per distinct ID, in input order.
The endpoint must return JSON; its entire body is added to the question as
text, labeled with its file ID. The component copies the incoming Message
and preserves its native attachments and metadata. It performs no document
extraction. HTTP failures and non-JSON responses stop the flow.

With no external IDs, including Playground runs and text-only requests, it
returns the original Chat Input Message without making HTTP requests or
requiring Files API settings. Playground attachments use Langflow's native
file handling and retain its file-type and model limitations.

Requests use Langflow's API Request component and its network policy. For a
Files API on a private address, configure `LANGFLOW_SSRF_ALLOWED_HOSTS` for
that host as with other API Request components. Redirects are disabled.

## Open WebUI

Each Open WebUI chat keeps one Langflow session through native configuration:

- Open WebUI's LiteLLM connection in [`apps/open-webui.yml`](../../apps/open-webui.yml)
  sends the chat ID as `X-Langflow-Session-Id: {{CHAT_ID}}`.
- LiteLLM's `model_group_settings` in
  [`configs/litellm/config.yaml`](../../configs/litellm/config.yaml) forwards
  caller `x-` headers to `langflow/*` models only, so
  [name Langflow deployments](#expose-a-langflow-flow-through-litellm)
  `langflow/<flow>`.

Keep Open WebUI's task model (`TASK_MODEL_EXTERNAL`) on a regular model;
otherwise title generation would also run the flow and replace its session.

## Playground and API parity

To make a flow behave the same in the Playground and from Open WebUI through
LiteLLM:

- Use the Agent's built-in chat memory as described in
  [Conversation history](#conversation-history). Both paths then give it the
  same current message, earlier turns, and history limit.
- Leave Responses Input's **Instructions** unconnected. Open WebUI system
  prompts and memories arrive as `instructions` and then do not affect the run.
- In Open WebUI's settings for the Langflow-backed model, turn off the **File
  Context**, **Web Search**, and **Code Interpreter** capabilities, in addition
  to tool calling and image input. These add Open WebUI prompts or retrieved
  content to the request. With the default `RAG_SYSTEM_CONTEXT=false`, file
  and search content goes into the user message, which becomes Chat Input
  text the Playground never sends.

Files remain the one intended difference: Playground attachments use
Langflow's native file handling, while API requests use
[file IDs](#file-references).

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

In LiteLLM's Admin UI, create an **OpenAI** deployment with a custom model
name starting with `langflow/`, which [Open WebUI sessions](#open-webui)
require. Preserve existing fields and add:

- **Model Info**: `{"mode": "responses"}`.
- **LiteLLM Params**: `{"additional_drop_params": ["tools", "tool_choice", "parallel_tool_calls"]}`.

The equivalent static configuration is:

```yaml
model_list:
  - model_name: langflow/FirstFlow
    litellm_params:
      model: openai/FirstFlow
      api_base: https://langflow.example.com/api/v1
      api_key: os.environ/LANGFLOW_API_KEY
      additional_drop_params: [tools, tool_choice, parallel_tool_calls]
    model_info:
      mode: responses
```

Drop caller-provided tools because Langflow currently rejects the `tools`
field; tools configured inside the flow still work. Future Open WebUI
`ask_user` HITL support requires Langflow to accept tool definitions and
results, plus a pause/resume bridge, before removing these drops.

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
    "model": "langflow/FirstFlow",
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

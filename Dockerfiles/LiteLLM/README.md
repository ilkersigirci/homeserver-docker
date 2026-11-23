# LiteLLM

This image builds the pinned official `BerriAI/litellm` release without the
Enterprise source tree.

## Image contents

- [`scripts/`](scripts/) holds build tooling: `strip_enterprise.py` removes
  Enterprise source and package entries before installation.
- [`patches/permanent/`](patches/permanent/) unlocks LiteLLM's native JWT
  auth, SSO, and [other license-gated features](#unlocked-features), copies
  token users' email and name onto their Internal User, and
  passes the files backend's [own fields](#file-extensions) through the
  Files API and tells it [who is calling](#file-ownership);
  [`src/`](src/) ships the `access_token.py` claim validator that
  [authentication](ARCHITECTURE.md) configures.
- [`patches/temporary/`](patches/temporary/) holds
  [temporary upstream workarounds](#temporary-upstream-workarounds).
- [`tests/`](tests/) holds the `verify_*.py` and Admin UI
  `verify_*.integration.test.tsx` checks for every retained customization.

## Unlocked features

The image has no license, so `premium_user` is always false. Permanent patches
remove license gates only where the feature runs on MIT code outside
`enterprise/`, one feature at a time; forcing `premium_user` true would also
switch on unreviewed behavior and enterprise-backed code that is not here.

- [`premium-features.patch`](patches/permanent/premium-features.patch) unlocks
  per-model budgets on keys and teams, key regeneration and scheduled
  rotation, team admins, premium key/team metadata (tags, guardrails,
  policies, logging, prompts, pass-through routes, secret manager settings),
  SCIM v2, the GCS Pub/Sub and Azure Storage loggers, audit log writes
  (`litellm_settings.store_audit_logs`), and region outage alert settings.
- [`premium-ui.patch`](patches/permanent/premium-ui.patch) enables the matching
  Admin UI controls in the components that render them. The session token's
  `premium_user` claim stays false, so these stay locked: UI access control
  (saving it clears the SSO settings; use `ui_access_mode` in the config),
  allowed IPs (filter at the edge), email branding, organizations, and the
  audit log viewer.
- Enterprise code is absent, so no patch can provide the `/audit` read API
  (query `LiteLLM_AuditLog` instead), `team_member_key_duration`, per-key
  disabled callbacks, `DISABLE_ADMIN_ENDPOINTS`, managed files and vector
  stores, the email v2 system, or the legacy moderation callbacks.

## Temporary upstream workarounds

Each patch's header records the upstream problem, any upstream reports, what
the patch changes, and its removal check.

- [`jwt-fallback-access.patch`](patches/temporary/jwt-fallback-access.patch):
  client-supplied fallbacks on JWT requests
- [`jwt-jwks-ssl.patch`](patches/temporary/jwt-jwks-ssl.patch):
  JWKS fetch TLS settings
- [`model-info-access.patch`](patches/temporary/model-info-access.patch):
  direct-ID `/model/info` scope
- [`responses-websocket-budget.patch`](patches/temporary/responses-websocket-budget.patch):
  Responses WebSocket per-model budgets
- [`responses-background.patch`](patches/temporary/responses-background.patch):
  background Response IDs on retrieve and cancel
- [`responses-streaming.patch`](patches/temporary/responses-streaming.patch):
  wildcard native streaming
- [`responses-logging.patch`](patches/temporary/responses-logging.patch):
  streamed Responses success logging
- [`responses-disconnect-logging.patch`](patches/temporary/responses-disconnect-logging.patch):
  Responses streams cancelled before any output
- [`otel-propagation.patch`](patches/temporary/otel-propagation.patch):
  provider trace context
- [`files-settings-routing.patch`](patches/temporary/files-settings-routing.patch):
  files_settings on file retrieve, content, delete, and list
- [`files-extra-headers.patch`](patches/temporary/files-extra-headers.patch):
  per-request headers on OpenAI file retrieve, list, and delete

At each LiteLLM upgrade, test the pinned release without each workaround. Remove
a patch, its source hashes, and its entry above only when its removal check
passes against unpatched upstream code; keep the check. The Dockerfile applies
every patch under `patches/` and runs every `tests/verify_*` check, so neither
needs a Dockerfile step.

## File extensions

[`files-extra-fields.patch`](patches/permanent/files-extra-fields.patch)
forwards the OpenAI SDK's `extra_body` on upload and `extra_query` on every
file endpoint to the files_settings backend, and returns the fields the backend
adds to file objects.

```python
file = client.files.create(
    file=open("document.pdf", "rb"),
    purpose="user_data",
    extra_body={"language": "tr", "parse_method": "ocr", "metadata": {"source": "archive"}},
)
file.model_extra  # e.g. {"metadata": {...}}, if the backend returns it
content = client.files.content(file.id, extra_query={"language": "tr"})
original = client.files.content(file.id, extra_query={"raw": "true"})
```

The backend receives the SDK's encoding: `metadata[source]=archive` for an
object, repeated `tags[]` for an array; send `json.dumps(...)` for one JSON
string instead. The proxy keeps its own fields (`file`, `purpose`,
`expires_after`, `provider`, `custom_llm_provider`, `model`,
`target_model_names`, `target_storage`, `passthrough`, `litellm_metadata`), so
a team's enforced file expiry still applies. List's `limit`, `after`, and
`order` reach the backend too.

### File ownership

[`files-identity.patch`](patches/permanent/files-identity.patch) tells the
files_settings backend who is calling, so
[Files API](ARCHITECTURE.md#files-api-ownership) can scope each file to its
owner. On every file operation it adds three of LiteLLM's
`x-litellm-user_api_key_*` headers to the backend request: `user_id`,
`team_id`, and `auth_metadata` (the key's metadata as JSON, without callback
credentials). They are named and encoded as
`add_user_information_to_llm_headers` does on model calls. The key's other
details, such as aliases, email, and spend, are not sent.

The headers come from the authenticated key only. A caller cannot set them or
fill in one the key lacks. User and team ids must be ASCII, as LiteLLM's
generated ids and PocketID subjects are; httpx refuses other characters in a
header.

Settings:

- `litellm_settings.add_user_information_to_llm_headers` is not needed and
  changes nothing on file calls. Leave it unset: on model calls that forward
  client headers (`langflow/*`) it sends every key detail, and a non-ASCII
  alias makes those calls fail.
- `files_settings` chooses the backend. A provider without an entry, or a file
  call routed by `model`, gets no headers. `extra_headers` in the entry are
  sent too, except any `x-litellm-user_api_key_*` name.
- `forward_client_headers_to_llm_api` has no effect on file calls. Caller `x-`
  headers never reach the files backend, whether it is on or off.
- `forward_traceparent_to_llm_provider` is unaffected. A `traceparent` it adds
  is kept.
- Leave `general_settings.user_header_mappings` unset. It lets a request header
  replace the key's user id.

Setup:

- [`configs/litellm/config.yaml`](../../configs/litellm/config.yaml) sets
  `files_settings`.
- [`apps/litellm.yml`](../../apps/litellm.yml) and
  [`apps/litellm-stack.yml`](../../apps/litellm-stack.yml) require
  `FILES_API_BASE_URL` (including `/v1`) and `FILES_GATEWAY_TOKEN`, which must
  equal Files API's own `FILES_GATEWAY_TOKEN`.
- On `.212` the running container mounts
  `core-services/configs/litellm/config.yaml`, not this template. Give it the
  same `files_settings` entry when rolling out.

The patch needs two [temporary workarounds](#temporary-upstream-workarounds):
`files-settings-routing.patch` and `files-extra-headers.patch`.
[`verify_files_ownership.py`](tests/verify_files_ownership.py) runs every file
operation as a user key, a service-account key, and a key with neither, while
the caller sends forged headers. The user and service-account keys have
non-ASCII aliases, and the backend must receive exactly the three headers.

## Images

One patched source build publishes the unified proxy and each upstream
component image the patches change:

| Target | Image | Replaces upstream |
| --- | --- | --- |
| `unified` (default) | `homeserver-litellm` | `litellm` |
| `gateway` | `homeserver-litellm-gateway` | `litellm-gateway` |
| `backend` | `homeserver-litellm-backend` | `litellm-backend` |
| `ui` | `homeserver-litellm-ui` | `litellm-ui` |

The gateway and backend images run the unified image's patched and checked
Python environment with upstream's component entrypoints, ports, default
commands, and non-root user (uid 65532). The UI image serves the same patched
dashboard with upstream's `ui/nginx.conf`. Like upstream's unified image, the
Python images include the SAML and Bedrock realtime extras and the in-container
PgBouncer. They leave out the LiteAdmin MCP connector, which needs an Enterprise
license to host, the optional LiteAdmin Slack agent (`--admin-agent`), and the
opt-in Rust HTTP server (`litellm-gateway`, from the `litellm-proxy` package),
which runs none of the patched Python code.

### Compose

`apps/litellm.yml` runs the unified proxy. `apps/litellm-stack.yml` follows
upstream's componentized Helm chart. `litellm-migrate` runs upstream's
`litellm-migrations` image, since no patch changes the schema, and exits once
the migrations and request-log indexes are in place. The gateway serves the LLM
API, the backend serves the management API, SSO, and MCP, and the UI serves the
dashboard. On the shared hostname, Traefik sends inference requests to the
gateway, dashboard pages and navigation assets to the UI, and other routes to the backend. Features LiteLLM
loads on first use, such as SCIM, run on the component that receives them.
[`verify_components.py`](tests/verify_components.py) checks that each component
serves the routes the patches and configuration use.

Valkey is required even with one replica each, because the gateway and backend
are separate processes. Through the `REDIS_*` settings, LiteLLM shares rate
limits, spend counters, auth cache invalidation, SSO PKCE state, and job locks.
A key deleted, blocked, or changed on the backend takes effect on every gateway
at once. If Valkey is unreachable at startup, LiteLLM logs a warning and keeps
that state per process.

Both files set `LITELLM_OFFLINE_MODE`, so LiteLLM fetches nothing on its own:
the model cost map, Anthropic beta headers, blog posts, policy templates, and
auto-router presets come from the image's LiteLLM release, and the
latest-release check, breached-password check, and Hugging Face tokenizer
downloads are skipped (those token counts fall back to tiktoken). Configured
destinations, such as LLM providers and the identity provider, are unaffected.

Both files use the same database and configuration; include only one per host.
When switching, remove the old containers, for example with
`up -d --remove-orphans`, so their Traefik routers do not conflict. The gateway
and backend omit `container_name`; raise `deploy.replicas` to scale them. Each
process opens its own Prisma pool of two connections per physical CPU core, plus
one; before replicas approach PostgreSQL's `max_connections`, enable upstream's
in-container PgBouncer on the gateway with `LITELLM_PGBOUNCER_ENABLED`, as the
chart's `database.connectionPool` does. Leave `service.instance.id` unset so the
OpenTelemetry SDK assigns each process its own ID.

## Updating

1. Clone the official `BerriAI/litellm` `v<version>` tag into a fresh temporary
    directory. Set `IMAGE_VERSION` and its resolved `UPSTREAM_COMMIT` in
    `Dockerfile`. Compare upstream's Dockerfile, Python/workspace metadata, UI
    build, and Prisma entrypoint with our stages; refresh base pins as needed.
    Compare the `gateway/`, `backend/`, and `ui/` component images with our
    targets. Check the gateway and backend route allowlists and the dashboard's
    exported assets against the Traefik rules in `apps/litellm-stack.yml`.
2. Refresh `base-sources.sha256` for every patched file from pristine upstream
    source. Run `scripts/strip_enterprise.py <checkout>` to remove proprietary source,
    package/workspace entries, and the enterprise UI override, preserving
    unrelated dependency pins. Adapt the script if upstream's layout changed.
3. Apply `patches/permanent/` and then `patches/temporary/`, each in name order,
    with `patch --batch --forward --fuzz=0 -p1` inside the checkout. Resolve drift
    by editing upstream code and regenerating separate diffs; follow the
    [removal criteria](#temporary-upstream-workarounds) above. Keep
    authorization, model access, budgets, rate limits, and admin-only UI access
    intact; never enable `premium_user` globally.
4. Run `tests/verify_oss.py <patched-checkout>`, then build from the repository root:

    ```sh
    docker build --progress=plain -t homeserver-litellm:check Dockerfiles/LiteLLM
    ```

    The build rebuilds the OSS dashboard and runs all `verify_*.py` checks against
    the installed proxy. Fix failures without skipping checks or accepting patch
    fuzz. Verify startup with an isolated configuration if entrypoint or
    migration behavior changed; do not restart the live stack for a patch rebase.
5. Run `uvx prek run --files <changed-files>`.

Renovate proposes version bumps; each needs the source commit, hashes, patches,
and build checks refreshed. A version-only bump fails the source commit check.
The shared [custom-image workflow](../../docs/RUNNING.md#custom-images)
publishes every target as `<image>:<IMAGE_VERSION>` after merge; keep Compose
references on their published `tag@digest` until the rebuilt images exist and
Renovate resolves the new digests.

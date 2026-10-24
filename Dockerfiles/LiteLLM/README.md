# LiteLLM

This image builds the pinned official `BerriAI/litellm` release without the
Enterprise source tree.

## Image contents

- [`scripts/`](scripts/) holds build tooling: `strip_enterprise.py` removes
  Enterprise source and package entries before installation.
- [`patches/permanent/`](patches/permanent/) unlocks LiteLLM's native JWT
  auth, SSO, and [other license-gated features](#unlocked-features), and
  copies token users' email and name onto their Internal User;
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
  native background Responses
- [`responses-streaming.patch`](patches/temporary/responses-streaming.patch):
  wildcard native streaming
- [`responses-logging.patch`](patches/temporary/responses-logging.patch):
  streamed Responses success logging
- [`responses-disconnect-logging.patch`](patches/temporary/responses-disconnect-logging.patch):
  cancelled Responses stream failure logging
- [`otel-propagation.patch`](patches/temporary/otel-propagation.patch):
  provider trace context
- [`realtime-turns.patch`](patches/temporary/realtime-turns.patch):
  client-owned realtime voice responses
- [`files-settings-routing.patch`](patches/temporary/files-settings-routing.patch):
  files_settings on file retrieve, content, delete, and list
- [`key-delete-eviction.patch`](patches/temporary/key-delete-eviction.patch):
  `/key/delete` eviction on other workers and components

At each LiteLLM upgrade, test the pinned release without each workaround. Remove
a patch, its source hashes, and its entry above only when its removal check
passes against unpatched upstream code; keep the check. The Dockerfile applies
every patch under `patches/` and runs every `tests/verify_*` check, so neither
needs a Dockerfile step.

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
license to host, and the optional LiteAdmin Slack agent (`--admin-agent`).

### Compose

`apps/litellm.yml` runs the unified proxy. `apps/litellm-stack.yml` follows
upstream's componentized Helm chart. `litellm-migrate` runs upstream's
`litellm-migrations` image, since no patch changes the schema, and exits once
the migrations and request-log indexes are in place. The gateway serves the LLM
API, the backend serves the management API, SSO, and MCP, and the UI serves the
dashboard. Traefik sends the chart's ingress gateway paths to the gateway,
dashboard paths to the UI, and everything else to the backend. Features LiteLLM
loads on first use, such as SCIM, run on the component that receives them.
[`verify_components.py`](tests/verify_components.py) checks that each component
serves the routes the patches and configuration use.

Valkey is required even with one replica each, because the gateway and backend
are separate processes. Through the `REDIS_*` settings, LiteLLM shares rate
limits, spend counters, auth cache invalidation, SSO PKCE state, and job locks.
A key deleted, blocked, or changed on the backend takes effect on every gateway
at once; [`key-delete-eviction.patch`](patches/temporary/key-delete-eviction.patch)
covers deletion. If Valkey is unreachable at startup, LiteLLM logs a warning and
keeps that state per process.

Both files use the same database and configuration; include only one per host.
When switching, remove the old containers, for example with
`up -d --remove-orphans`, so their Traefik routers do not conflict. The gateway
and backend omit `container_name`; raise `deploy.replicas` to scale them. Each
process opens its own Prisma pool of two connections per physical CPU core, plus
one; before replicas approach PostgreSQL's `max_connections`, enable upstream's
in-container PgBouncer on the gateway with `LITELLM_PGBOUNCER_ENABLED`, as the
chart's `database.connectionPool` does. Replicas on one host share an
OpenTelemetry `service.instance.id`, because Compose cannot set it per replica.

## Updating

1. Clone the official `BerriAI/litellm` `v<version>` tag into a fresh temporary
    directory. Set `IMAGE_VERSION` and its resolved `UPSTREAM_COMMIT` in
    `Dockerfile`. Compare upstream's Dockerfile, Python/workspace metadata, UI
    build, and Prisma entrypoint with our stages; refresh base pins as needed.
    Compare the `gateway/`, `backend/`, and `ui/` component images with our
    targets, and the chart's ingress gateway paths with the gateway router in
    `apps/litellm-stack.yml`.
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

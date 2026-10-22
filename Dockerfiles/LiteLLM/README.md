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

At each LiteLLM upgrade, test the pinned release without each workaround. Remove
a patch, its source hashes, and its entry above only when its removal check
passes against unpatched upstream code; keep the check. The Dockerfile applies
every patch under `patches/` and runs every `tests/verify_*` check, so neither
needs a Dockerfile step.

## Updating

1. Clone the official `BerriAI/litellm` `v<version>` tag into a fresh temporary
    directory. Set `IMAGE_VERSION` and its resolved `UPSTREAM_COMMIT` in
    `Dockerfile`. Compare upstream's Dockerfile, Python/workspace metadata, UI
    build, and Prisma entrypoint with our stages; refresh base pins as needed.
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
publishes `homeserver-litellm:<IMAGE_VERSION>` after merge; update Compose's tag
and digest once that image exists.

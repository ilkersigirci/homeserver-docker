# LiteLLM

This image builds the pinned official `BerriAI/litellm` release without the
Enterprise source tree.

## Image contents

- [`scripts/`](scripts/) holds build tooling: `strip_enterprise.py` removes
  Enterprise source and package entries before installation.
- [`src/`](src/) holds code shipped in the image: `user_auth.py`, with the
  [`patches/permanent/`](patches/permanent/) patches, implements
  [authentication](ARCHITECTURE.md).
- [`patches/temporary/`](patches/temporary/) holds
  [temporary upstream workarounds](#temporary-upstream-workarounds).
- [`tests/`](tests/) holds the `verify_*.py` checks for every retained
  customization.

## Temporary upstream workarounds

Each patch's header records the upstream problem, any upstream reports, what
the patch changes, and its removal check.

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
- [`otel-propagation.patch`](patches/temporary/otel-propagation.patch):
  provider trace context

At each LiteLLM upgrade, test the pinned release without each workaround. Remove
a patch, its Dockerfile step, its source hashes, and its entry above only when
its removal check passes against unpatched upstream code; keep the check.

## Updating

1. Clone the official `BerriAI/litellm` `v<version>` tag into a fresh temporary
    directory. Set `IMAGE_VERSION` and its resolved `UPSTREAM_COMMIT` in
    `Dockerfile`. Compare upstream's Dockerfile, Python/workspace metadata, UI
    build, and Prisma entrypoint with our stages; refresh base pins as needed.
2. Refresh `base-sources.sha256` for every patched file from pristine upstream
    source. Run `scripts/strip_enterprise.py <checkout>` to remove proprietary source,
    package/workspace entries, and the enterprise UI override, preserving
    unrelated dependency pins. Adapt the script if upstream's layout changed.
3. Apply `patches/` in Dockerfile order with `patch --batch --forward --fuzz=0 -p1`
    inside the checkout. Resolve drift by editing upstream code and regenerating
    separate diffs; follow the [removal criteria](#temporary-upstream-workarounds)
    above. Keep authorization, model access, budgets, rate limits, and admin-only
    UI access intact; never enable `premium_user` globally.
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

# LiteLLM

This image builds the pinned official `BerriAI/litellm` release without the
Enterprise source tree. One process serves the Admin UI, native LiteLLM keys,
and OIDC access tokens against one PostgreSQL-backed policy/model catalog. See [ARCHITECTURE.md](ARCHITECTURE.md)
for the identity model.

## Image contents

- `strip_enterprise.py` removes Enterprise source and package entries before
  installation.
- `sso.patch` removes the five-user UI SSO cap and SSO debug-login license gate.
- `custom-auth-fallback.patch` lets an OSS custom-auth function return `None`
  and continue through LiteLLM's native authentication path.
- `model-info-access.patch` applies the caller's model and team scope to direct
  deployment-ID reads from the read-only model-info endpoint.
- `responses-websocket-budget.patch` applies the Internal User's per-model
  budgets when a Responses WebSocket names its model in the first frame.
- `user_auth.py` resolves RFC 9068 access tokens (validated with PyJWT) to a
  LiteLLM Internal User, created fail-closed on first use.
- `responses-background.patch`, `responses-streaming.patch`, and
  `responses-logging.patch` are narrow upstream Responses API workarounds.
- `otel-propagation.patch` propagates the model-call span to providers.
- `verify_*.py` exercises every retained customization during the image build.

## OIDC access tokens and personal keys

Clients holding a LiteLLM-audience user access token send it as
`Authorization: Bearer`. LiteLLM validates signature (issuer JWKS, pinned
algorithm), exact issuer and audience, expiry, `typ: at+jwt`, and the
required scope, then resolves `sub` to an Internal User. Configure
`LITELLM_OIDC_ISSUER`, `LITELLM_OIDC_JWKS_URL`, `LITELLM_OIDC_AUDIENCE`,
`LITELLM_OIDC_REQUIRED_SCOPE`, and `LITELLM_OIDC_SIGNING_ALGORITHM`; startup
fails if any is missing or the algorithm is symmetric.

A missing user is created from LiteLLM's native `default_internal_user_params`,
which [`config.yaml`](../../configs/litellm/config.yaml) sets to a fail-closed
`max_budget: 0` with no models. Requests are rejected until an administrator
assigns models and a budget. `custom_auth_run_common_checks` and
`enable_post_custom_auth_checks` hand model, budget, RPM, and TPM enforcement
to LiteLLM's native checks. The hook rejects every request with 500 unless
both are set: without the first, LiteLLM skips its common checks for native
keys too. OIDC identities may call OpenAI routes, model retrieval, and
read-only model-info routes only.

Every other credential returns `None` from the hook, so master keys, virtual
keys, and public routes use LiteLLM's native authentication. Tools without the
user's token, such as Langflow, use a virtual key owned by the user's Internal
User, which LiteLLM caps by that user's models and budget
([ARCHITECTURE.md](ARCHITECTURE.md#personal-virtual-keys)).

## TLS certificates

This image's OIDC JWKS client follows LiteLLM's native TLS settings. To trust a
private CA (for example, a self-hosted Keycloak), mount a PEM bundle containing
the public roots plus that CA and set `SSL_CERT_FILE` to its path. As a last
resort, set `LITELLM_SSL_VERIFY=false` in the host's `.env`; Compose passes it
as LiteLLM's native `SSL_VERIFY`, which disables certificate checks for all
LiteLLM outbound requests, including LLM providers. JWT signature and claim
checks still apply.

## Temporary upstream workarounds

`responses-streaming.patch` addresses wildcard deployments that lose native
streaming capability metadata. It is enabled only when
`LITELLM_ENABLE_RESPONSES_STREAMING_FIX=true` and the selected deployment sets
`model_info.supports_native_streaming: true`. Track
[issue #21090](https://github.com/BerriAI/litellm/issues/21090),
[issue #37800](https://github.com/BerriAI/litellm/issues/37800), and
[PR #37801](https://github.com/BerriAI/litellm/pull/37801).

`responses-background.patch` removes an Enterprise-only persistence import from
native background Responses and preserves polling IDs. Track
[issue #32782](https://github.com/BerriAI/litellm/issues/32782),
[PR #32784](https://github.com/BerriAI/litellm/pull/32784), and
[issue #17204](https://github.com/BerriAI/litellm/issues/17204).

`responses-logging.patch` normalizes streamed terminal Responses objects before
success logging. Track
[issue #34754](https://github.com/BerriAI/litellm/issues/34754).

`otel-propagation.patch` replaces the inbound `traceparent` at the provider
handoff with LiteLLM's model-call span context. Track
[issue #39067](https://github.com/BerriAI/litellm/issues/39067).

`model-info-access.patch` is required while a direct
`/model/info?litellm_model_id=...` lookup bypasses the filters used by the
listing form of the endpoint. Remove it only when the model-info regression
check passes against unpatched upstream LiteLLM.

`responses-websocket-budget.patch` is required while upstream's Responses
WebSocket first-frame authorization skips the Internal User's per-model budget
that HTTP requests enforce. Remove it only when the WebSocket budget check in
`verify_user_auth.py` passes against unpatched upstream LiteLLM.

At each LiteLLM upgrade, test the pinned release without each workaround. Remove
a patch, its Dockerfile steps, and source hashes only when the corresponding
`verify_*.py` check passes against unpatched upstream code.

## Updating

1. Clone the official `BerriAI/litellm` `v<version>` tag into a fresh temporary
    directory. Set `IMAGE_VERSION` and its resolved `UPSTREAM_COMMIT` in
    `Dockerfile`. Compare upstream's Dockerfile, Python/workspace metadata, UI
    build, and Prisma entrypoint with our stages; refresh base pins as needed.
2. Refresh `base-sources.sha256` for every patched file from pristine upstream
    source. Run `strip_enterprise.py <checkout>` to remove proprietary source,
    package/workspace entries, and the enterprise UI override, preserving
    unrelated dependency pins. Adapt the script if upstream's layout changed.
3. Apply patches in Dockerfile order with `patch --batch --forward --fuzz=0 -p1`
    inside the checkout. Resolve drift by editing upstream code and regenerating
    separate diffs; follow the [removal criteria](#temporary-upstream-workarounds)
    above. Keep authorization, model access, budgets, rate limits, and admin-only
    UI access intact; never enable `premium_user` globally.
4. Run `verify_oss.py <patched-checkout>`, then build from the repository root:

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

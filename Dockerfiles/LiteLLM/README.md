# LiteLLM

This image builds directly from a pinned official `BerriAI/litellm` source tag.
Enterprise-removal, SSO, and delegated-auth changes live here. It runs native
LiteLLM keys and user-delegated OIDC access tokens in one LiteLLM process.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the request flow, provider
configuration, authorization boundaries, and deployment contract.

The build owns:

- `strip_enterprise.py`, which removes enterprise source, packaging and lockfile
  entries, and the enterprise UI override before installation.
- `sso.patch`, which removes the five-user UI SSO cap and the license
  requirement for SSO debug login.
- `litellm-auth.patch`, which adds explicit ingress-lane dispatch and shared
  authorization checks to LiteLLM.
- `responses-streaming.patch`, a temporary upstream bug workaround, not a
  permanent image customization; see [removal criteria](#temporary-streaming-bug-workaround).
- `responses-logging.patch`, a temporary fix for missing streamed Responses
  success logs; see [removal criteria](#temporary-logging-bug-workaround).
- `oidc_delegated_auth.py`, which validates the configured Pocket ID or
  Keycloak user access-token profile.
- `verify_auth.py`, which exercises the integration during every image build.
- `verify_streaming.py`, which checks wildcard routing and the upstream `stream`
  request field during every image build without external API calls.
- `verify_logging.py`, which checks Responses success callbacks and spend-log
  payloads during every image build without external API calls or a database.
- `verify_oss.py`, which checks stripped source and the installed runtime.

The build pins base images by digest and source by tag plus commit checksum.
It checks source hashes, applies patches without fuzz, rebuilds the OSS dashboard,
and verifies the installed proxy and authentication code. The runtime contains
no enterprise tree or package. Other upstream premium feature gates remain;
authentication and user budget/model/rate limits still apply.

## Configuration

`OIDC_REQUIRE_VERIFIED_EMAIL` controls first-use delegated-user provisioning.
It defaults to `true`, which rejects a UserInfo email unless
`email_verified` is the JSON boolean `true`. Set it to `false` to allow the
OIDC subject through when its email is unverified; the unverified email is
discarded and cannot participate in LiteLLM account linking.

Only `true` and `false` are accepted, case-insensitively. Any other value stops
the process during configuration loading. For this repository's Compose
deployment, set `OIDC_REQUIRE_VERIFIED_EMAIL=false` in `.env` to opt out.

## Temporary Streaming Bug Workaround

Unlike the enterprise-removal, SSO, and delegated-auth customizations,
`responses-streaming.patch` exists only to work around a LiteLLM bug and must
be removed once the pinned upstream release fixes our affected request path.
Unknown model names reached through wildcard routes can miss LiteLLM's global
capability lookup, causing it to drop upstream `stream: true` and synthesize
events only after generation finishes.

Related upstream reports and proposed fix:

- [Issue #21090](https://github.com/BerriAI/litellm/issues/21090): custom-model
  Responses requests fall back to fake streaming and lose intermediate tool
  events. Its stale closure is not evidence of a fix.
- [Issue #37800](https://github.com/BerriAI/litellm/issues/37800): custom Azure
  deployment names fake-stream because the capability check ignores `base_model`.
- [PR #37801](https://github.com/BerriAI/litellm/pull/37801): proposes passing
  deployment metadata into that check and falling back to `base_model`.

The temporary streaming patch follows the metadata propagation approach in
PR #37801, but is not a direct backport: it honors
`model_info.supports_native_streaming` directly instead of requiring a
`base_model`. Set that boolean on wildcard deployments whose upstream supports
native Responses streaming. Omitted capabilities retain upstream behavior;
provider-specific Manus and Volcengine streaming rules remain unchanged.

The workaround is disabled by default. Set the custom image environment variable
`LITELLM_ENABLE_RESPONSES_STREAMING_FIX=true` to enable it; only `true`
(case-insensitive) enables the fix. Unset, `false`, and other values retain
upstream behavior and the original provider-method call signature. The image
does not set this flag for you.

Enabling the flag is not a global force-stream switch: the selected deployment
must also set a boolean `model_info.supports_native_streaming`. That boolean
overrides the model capability lookup for streaming Responses requests, including
exact-model deployments. Set it only where the upstream capability is known;
incorrectly setting `true` can make a non-streaming upstream reject requests.
External Responses provider subclasses that override `should_fake_stream` need
to accept the new argument when opting in. Non-streaming requests and unrelated
API paths are unchanged. Usage logging is handled by the separate patch below;
upstream error-metadata limitations remain.

At every upstream upgrade, check these references and test the candidate release
without this streaming patch. Remove it when `verify_streaming.py` passes for
wildcard deployments with arbitrary graph names and explicit streaming
capabilities, without requiring a `base_model` or exact-model registrations.
A merged PR or closed issue alone is insufficient.

When fixed, delete `responses-streaming.patch`, remove its Dockerfile copy/apply
steps, its environment flag, and source hashes used only by this patch, and
update this section and the upgrade runbook. Keep the native wildcard streaming
regression check in the build. Retire flag-specific opt-in/opt-out assertions
alongside the flag, and adapt internal API calls if upstream changes them,
without weakening the native-streaming request-path checks.
The unrelated OSS/auth customizations remain in place.

## Temporary Logging Bug Workaround

`responses-logging.patch` fixes the success-logging failure in
[upstream issue #34754](https://github.com/BerriAI/litellm/issues/34754).
The streaming parser can leave the terminal response as a dictionary after a
validation fallback. The success logger then raises `AttributeError` on `.usage`,
dropping the spend-log entry even though the client received its response.

The patch normalizes that dictionary into LiteLLM's response object and reuses
its usage conversion for dictionary and typed usage. It applies automatically
to streamed completed, incomplete, and failed terminal events. No flag is needed.
`verify_logging.py` checks sync/async success callbacks, response content, token
details, spend, and non-streaming behavior. It verifies the payload prepared for
PostgreSQL insertion; deployment validation must also confirm the stored row.

At each upgrade, test without this patch. Once the pinned release passes
`verify_logging.py`, remove the patch, its Dockerfile copy/apply steps, and its
source hash. Keep the regression check in the build.

## Updating

Use [update-litellm](../../docs/skills/update-litellm/SKILL.md). Renovate tracks
official version tags; the shared [custom-image workflow](../../docs/RUNNING.md#custom-images)
builds and publishes `homeserver-litellm:<IMAGE_VERSION>` for `linux/amd64` and
`linux/arm64`. Compose keeps its current pinned image until a new tag is
published and its digest can be resolved.

# LiteLLM

This image builds directly from a pinned official `BerriAI/litellm` source tag.
All OSS and delegated-auth changes live here; no fork image or repository is
required. It runs native LiteLLM keys and user-delegated OIDC access tokens in
one LiteLLM process.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the request flow, provider
configuration, authorization boundaries, and deployment contract.

The build owns:

- `strip_enterprise.py`, which removes enterprise source, packaging and lockfile
  entries, and the enterprise UI override before installation.
- `litellm-oss.patch`, which removes the five-user UI SSO cap and the license
  requirement for SSO debug login.
- `litellm-auth.patch`, which adds explicit ingress-lane dispatch and shared
  authorization checks to LiteLLM.
- `oidc_delegated_auth.py`, which validates the configured Pocket ID or
  Keycloak user access-token profile.
- `verify_auth.py`, which exercises the integration during every image build.
- `verify_oss.py`, which checks stripped source and the installed runtime.

The build pins base images by digest and source by tag plus commit checksum.
It checks source hashes, applies patches without fuzz, rebuilds the OSS dashboard,
and verifies the installed proxy and authentication code. The runtime contains
no enterprise tree or package. Other upstream premium feature gates remain;
authentication and user budget/model/rate limits still apply.

The OSS stripping and SSO changes derive from
[`litellm-OSS`](https://github.com/ilkersigirci/litellm-OSS/tree/2cd6cb24bf6b8ceb56491f23334bdaf8978efa97)
and retain its MIT notice in `LICENSE.litellm-oss`. Its workflows and agent automation are
not build dependencies.

## Configuration

`OIDC_REQUIRE_VERIFIED_EMAIL` controls first-use delegated-user provisioning.
It defaults to `true`, which rejects a UserInfo email unless
`email_verified` is the JSON boolean `true`. Set it to `false` to allow the
OIDC subject through when its email is unverified; the unverified email is
discarded and cannot participate in LiteLLM account linking.

Only `true` and `false` are accepted, case-insensitively. Any other value stops
the process during configuration loading. For this repository's Compose
deployment, set `OIDC_REQUIRE_VERIFIED_EMAIL=false` in `.env` to opt out.

## Updating

Use [update-litellm](../../docs/skills/update-litellm/SKILL.md). Renovate tracks
official version tags; the shared [custom-image workflow](../../docs/RUNNING.md#custom-images)
builds and publishes `homeserver-litellm:<IMAGE_VERSION>` for `linux/amd64` and
`linux/arm64`. Compose keeps its current pinned image until a new tag is
published and its digest can be resolved.

# LiteLLM

This image is a thin derivative of the community
[`nathanael-h/litellm-libre`](https://github.com/nathanael-h/litellm-libre)
image. It adds the OSS authentication dispatcher required to run native
LiteLLM keys and user-delegated OIDC access tokens in one LiteLLM process.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the request flow, provider
configuration, authorization boundaries, and deployment contract.

The image owns only:

- `litellm-auth.patch`, which adds explicit ingress-lane dispatch and shared
  authorization checks to LiteLLM.
- `oidc_delegated_auth.py`, which validates the configured Pocket ID or
  Keycloak user access-token profile.
- `verify_auth.py`, which exercises the integration during every image build.

The build is fail-closed. It pins the Libre base by digest, checks the exact
upstream source hashes before patching, applies the patch without fuzz, verifies
that Enterprise modules are absent, and compiles and tests the installed code.

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

When changing `IMAGE_VERSION` or its digest:

1. Confirm the upstream Libre release remains MIT-only.
2. Refresh `base-sources.sha256` from the pinned image.
3. Rebase `litellm-auth.patch` when the source hashes or patch application
    change.
4. Build the image locally. Do not bypass a failed source, patch, or Enterprise
    check.

The base image currently publishes only `linux/amd64`, so the matching workflow
intentionally builds only that platform.

# Hatchet

This image builds a pinned official Hatchet release with generic OIDC login.
The patch boundary is deliberate:

- `oidc.patch` is the rebased implementation from
  [hatchet-dev/hatchet#4176](https://github.com/hatchet-dev/hatchet/pull/4176).
- `oidc-hardening.patch` is this repository's security and identity layer on
  top of that PR.

The hardening patch adds PKCE S256, an OIDC nonce, one-time flow state, login
rate limiting, strict UserInfo subject validation, and session ID rotation. It
resolves returning users by the stable `(issuer, subject)` identity before
email. First-time provisioning requires a verified email, and an existing email
is treated as a conflict rather than an implicit account link. OIDC access and
refresh tokens are not retained because Hatchet does not consume them after
login.

The included database migration makes `(provider, providerUserId)` unique while
preserving Hatchet's existing one-OAuth-identity-per-user constraint. OIDC's
provider user ID is a versioned digest of issuer and subject, so two issuers may
use the same subject safely.

`IMAGE_VERSION` selects the official release and published image tag.
`UPSTREAM_COMMIT` pins that tag to its peeled commit. During the build,
`base-sources.sha256` verifies every existing upstream file changed by either
patch, both patches apply with zero fuzz, generated frontend snippets are
refreshed, and focused auth tests run before the binaries are built. The image
contains matching `hatchet-lite`, `hatchet-admin`, `hatchet-migrate`, and
frontend artifacts.

## OIDC Email Provisioning

First-time OIDC provisioning requires a non-empty `email` and
`email_verified: true` from the verified ID token or a subject-matched UserInfo
response. The email and its verification status always come from the same
verified claim set. If that email already belongs to a Hatchet account, login
is rejected; accounts are never linked by email.

Returning login uses only the verified issuer and subject, so it does not
depend on mutable email claims. There is no issuer-specific trust bypass, and
the instance-wide `SERVER_AUTH_SET_EMAIL_VERIFIED` setting does not override
the first-time provisioning policy.

The repository deployment is OIDC-only. Its session cookie is secure and scoped
to the Hatchet hostname rather than the parent domain.

## Updating

Renovate tracks GitHub releases rather than every Git tag. For an update:

1. Resolve the new official release tag to its peeled commit and update
    `IMAGE_VERSION` and `UPSTREAM_COMMIT` in `Dockerfile`.
2. Check out that release in a clean upstream clone and apply `oidc.patch`, then
    `oidc-hardening.patch`, with three-way merge support.
3. Resolve conflicts in the upstream patch first, regenerate it as the diff
    from the clean release, then rebase and regenerate the hardening patch as the
    diff from the upstream-patched tree.
4. If the API contract changed, run `hack/oas/generate-server.sh`. If repository
    queries changed, run the upstream `generate-sqlc` task. Run `go mod tidy`
    after dependency changes.
5. Refresh `base-sources.sha256` from the unpatched release for the union of
    existing files touched by both patches.
6. Build the image, run the tagged PostgreSQL integration tests, and exercise a
    complete runtime redirect and callback against a mock or real OIDC issuer.

The Compose image reference stays on its published `tag@digest` until the
custom-image workflow publishes the rebuilt tag and a later Renovate run
resolves its new digest.

Remove `oidc.patch` when an official Hatchet release contains equivalent generic
OIDC support. Remove `oidc-hardening.patch` only when upstream also provides the
same issuer/subject identity semantics, database constraints, and protocol
protections.

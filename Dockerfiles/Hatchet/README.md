# Hatchet

Builds the pinned official Hatchet release with generic OIDC login, based on
[hatchet-dev/hatchet#4176](https://github.com/hatchet-dev/hatchet/pull/4176).
`oidc.patch` adds the provider configuration, login button, handlers, and tests.

We prioritize Hatchet compatibility and a small patch over custom identity and
session hardening. Accounts are matched by email, not `(issuer, subject)`;
tokens are encrypted in native `UserOAuth`, and login does not rotate the
session ID. This avoids custom tables, migrations, queries, and shared-session
changes.

Protocol handling uses `go-oidc` and `golang.org/x/oauth2` for discovery, ID-token
verification, and PKCE S256. The handlers check the nonce and UserInfo subject,
keep email and verification claims paired, and expire login attempts after five
minutes. Flow data lives in Hatchet's existing session; starting another login
replaces the pending attempt. The OIDC routes use Hatchet's rate limiter.

## Configuration

Set `SERVER_AUTH_OIDC_ENABLED`, `SERVER_AUTH_OIDC_CLIENT_ID`,
`SERVER_AUTH_OIDC_CLIENT_SECRET`, and `SERVER_AUTH_OIDC_ISSUER_URL`.
Scopes default to `openid profile email`. Register this redirect URI:

```text
${SERVER_URL}/api/v1/users/oidc/callback
```

The provider must return an email in the ID token or a subject-matched UserInfo
response. New users without verified email remain subject to Hatchet's
email-verification gate. Matching an existing account requires
`email_verified: true` or an explicit `SERVER_AUTH_SET_EMAIL_VERIFIED` trust
setting. Configure an issuer trusted to assert account email addresses.

The repository deployment is OIDC-only, with a secure cookie scoped to the
Hatchet hostname.

## Updating and Validation

`IMAGE_VERSION` selects the official release and published tag;
`UPSTREAM_COMMIT` pins its peeled commit. The build verifies
`base-sources.sha256`, applies the patch with zero fuzz, refreshes frontend
snippets, runs focused tests, and builds matching server, admin, migration, and
frontend artifacts.

For an update:

1. Update the release tag and peeled commit in `Dockerfile`.
2. Rebase `oidc.patch` onto that release. Regenerate the OpenAPI server with
    `hack/oas/generate-server.sh` if the contract changes.
3. Refresh `base-sources.sha256` for existing upstream files touched by the patch.
4. Build the image and run the PostgreSQL authentication tests.

The image workflow runs the tagged integration tests, including PKCE code
exchange, nonce validation, flow expiry, replay rejection, and native account
provisioning. Publishing requires those tests to pass.

Keep the Compose reference on its published `tag@digest` until the rebuilt image
is published and Renovate resolves the new digest. Remove the patch when an
official release provides equivalent OIDC support.

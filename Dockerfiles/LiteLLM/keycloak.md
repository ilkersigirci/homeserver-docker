# Keycloak SSO for LiteLLM and Open WebUI

This guide assumes a custom LiteLLM image that supports both:

- Native LiteLLM master and virtual keys.
- User-delegated Keycloak access tokens through
  `oidc_delegated_auth.user_api_key_auth`.

Open WebUI authenticates users with Keycloak and forwards each user's current
Keycloak access token to LiteLLM. LiteLLM validates the token and applies
per-user model, budget, TPM, and RPM controls.

```text
Browser -> Keycloak -> LiteLLM Admin UI
Browser -> Keycloak -> Open WebUI -> Keycloak access token -> LiteLLM API
```

The examples use:

```text
Keycloak: https://sso.example.com
Realm: ai
LiteLLM native endpoint: https://litellm.example.com
LiteLLM delegated endpoint: https://litellm-sso.example.com
Open WebUI: https://chat.example.com
LiteLLM audience: litellm
Required permission: llm:invoke
```

Replace these values with the deployment's URLs.

## Request Lanes

Route both LiteLLM hostnames to the same LiteLLM process and port. The reverse
proxy must overwrite `X-LiteLLM-Auth-Lane` on every request:

| Endpoint | Header value | Accepted credential |
| --- | --- | --- |
| `https://litellm.example.com` | `native` | LiteLLM master or virtual key |
| `https://litellm-sso.example.com` | `custom` | Keycloak user access token |

Do not expose the LiteLLM backend port directly. Clients must not be able to
bypass the reverse proxy or choose the authentication lane themselves.

## Keycloak Realm

Create or select the `ai` realm and verify:

- The public issuer is exactly `https://sso.example.com/realms/ai`.
- Access tokens are signed with `RS256`.
- Users have a username, first name, last name, email, and verified email.
- Keycloak is reachable from users, LiteLLM, and Open WebUI through its canonical
  HTTPS URL.

Verify the discovery document:

```bash
curl -fsS \
  https://sso.example.com/realms/ai/.well-known/openid-configuration |
  jq '{issuer,authorization_endpoint,token_endpoint,userinfo_endpoint,jwks_uri}'
```

## Keycloak Clients

Create three OpenID Connect clients.

### LiteLLM API Resource

Create a non-login client that represents the LiteLLM API:

```text
Client ID: litellm
Client authentication: Off
Standard flow: Off
Direct access grants: Off
Implicit flow: Off
Service accounts: Off
```

This client exists so Keycloak can place `litellm` in the access token's `aud`
claim.

### LiteLLM Admin UI

Create the interactive LiteLLM client:

```text
Client ID: litellm-ui
Client authentication: On
Standard flow: On
Direct access grants: Off
Implicit flow: Off
Service accounts: Off
PKCE method: S256
```

Configure exact application URLs:

```text
Valid redirect URI:
https://litellm.example.com/sso/callback

Valid post-logout redirect URI:
https://litellm.example.com

Web origin:
https://litellm.example.com
```

Copy the generated client secret.

### Open WebUI

Create the interactive Open WebUI client:

```text
Client ID: open-webui
Client authentication: On
Standard flow: On
Direct access grants: Off
Implicit flow: Off
Service accounts: Off
PKCE method: S256
```

Configure:

```text
Valid redirect URI:
https://chat.example.com/oauth/oidc/callback

Valid post-logout redirect URI:
https://chat.example.com

Web origin:
https://chat.example.com
```

Copy this client's separate secret. Do not use wildcard redirect URIs in
production.

See the
[Keycloak client documentation](https://www.keycloak.org/docs/latest/server_admin/#assembly-managing-clients_server_administration_guide).

## Keycloak Client Scopes

### LiteLLM Permission

Create an optional OpenID Connect client scope named exactly `llm:invoke`:

```text
Include in token scope: On
```

Add an **Audience** mapper:

```text
Included Client Audience: litellm
Add to access token: On
Add to ID token: Off
```

Link `llm:invoke` as an optional client scope to `open-webui` and every other
client allowed to call the delegated LiteLLM endpoint.

### Group Membership

Create an optional OpenID Connect client scope named `groups`. Add a
**Group Membership** mapper:

```text
Token Claim Name: groups
Full group path: On
Add to ID token: On
Add to access token: On
Add to UserInfo: On
```

Link `groups` as an optional client scope to `litellm-ui` and `open-webui`.

Create a top-level Keycloak group named `admin` and add LiteLLM administrators
to it. The mapper must emit:

```json
{
  "groups": ["/admin"]
}
```

Also verify:

- `profile` and `email` are default scopes for both interactive clients.
- `profile` adds `preferred_username` to access tokens.
- `offline_access` is an optional scope for `open-webui`.

See the [Keycloak client-scope documentation](https://www.keycloak.org/docs/latest/server_admin/#_client_scopes)
and [protocol-mapper reference](https://www.keycloak.org/admin-api/protocol-mappers).

## Verify the Keycloak Token

In Keycloak, open:

```text
Clients -> open-webui -> Client scopes -> Evaluate
```

Select an administrator and request:

```text
openid email profile groups offline_access llm:invoke
```

The generated access token must contain:

```json
{
  "iss": "https://sso.example.com/realms/ai",
  "aud": "litellm",
  "typ": "Bearer",
  "preferred_username": "normal-user-name",
  "scope": "... groups ... llm:invoke ...",
  "groups": ["/admin"]
}
```

The ID token and UserInfo response must contain `groups: ["/admin"]`. UserInfo
must return the same `sub` as the access token and `email_verified: true`.

Do not use an ID token or service-account token for delegated LiteLLM requests.

## LiteLLM Configuration

LiteLLM requires PostgreSQL and stable master and salt keys:

```env
LITELLM_MASTER_KEY=sk-use-a-strong-random-value
LITELLM_SALT_KEY=sk-use-another-stable-random-value
DATABASE_URL=postgresql://litellm:password@postgres:5432/litellm
PROXY_BASE_URL=https://litellm.example.com
```

Configure LiteLLM Admin UI login:

```env
AUTO_REDIRECT_UI_LOGIN_TO_SSO=true
GENERIC_CLIENT_ID=litellm-ui
GENERIC_CLIENT_SECRET=<litellm-ui-client-secret>
GENERIC_CLIENT_USE_PKCE=true
PKCE_STRICT_CACHE_MISS=true

GENERIC_AUTHORIZATION_ENDPOINT=https://sso.example.com/realms/ai/protocol/openid-connect/auth
GENERIC_TOKEN_ENDPOINT=https://sso.example.com/realms/ai/protocol/openid-connect/token
GENERIC_USERINFO_ENDPOINT=https://sso.example.com/realms/ai/protocol/openid-connect/userinfo
GENERIC_SCOPE=openid email profile groups

GENERIC_USER_ID_ATTRIBUTE=sub
GENERIC_USER_EMAIL_ATTRIBUTE=email
GENERIC_USER_DISPLAY_NAME_ATTRIBUTE=name

GENERIC_ROLE_MAPPINGS_DEFAULT_ROLE=internal_user
GENERIC_ROLE_MAPPINGS_GROUP_CLAIM=groups
GENERIC_ROLE_MAPPINGS_ROLES={"proxy_admin":["/admin"]}
```

Configure delegated Keycloak access-token validation:

```env
OIDC_ISSUER=https://sso.example.com/realms/ai
OIDC_JWKS_URL=https://sso.example.com/realms/ai/protocol/openid-connect/certs
OIDC_USERINFO_URL=https://sso.example.com/realms/ai/protocol/openid-connect/userinfo
OIDC_AUDIENCE=litellm
OIDC_REQUIRED_SCOPE=llm:invoke
OIDC_TOKEN_PROFILE=keycloak
OIDC_SIGNING_ALGORITHM=RS256
OIDC_REQUIRE_VERIFIED_EMAIL=true
```

The signing algorithm must match the Keycloak access-token header.
Keep email verification required when email can link accounts. With
`OIDC_REQUIRE_VERIFIED_EMAIL=false`, an unverified email is discarded and
first-use provisioning resolves or creates the LiteLLM user by Keycloak `sub`.

Configure the custom authentication module:

```yaml
general_settings:
  custom_auth: oidc_delegated_auth.user_api_key_auth
  custom_auth_run_common_checks: true
  ui_access_mode: admin_only

litellm_settings:
  default_internal_user_params:
    max_budget: 0
```

`custom_auth_run_common_checks: true` is required for LiteLLM to load the
matched user and enforce model, budget, TPM, and RPM controls.

## Open WebUI Configuration

Configure Open WebUI login and token storage:

```env
WEBUI_URL=https://chat.example.com
WEBUI_SECRET_KEY=<strong-stable-random-secret>
OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=<separate-stable-random-secret>
ENABLE_PERSISTENT_CONFIG=false

ENABLE_OAUTH_SIGNUP=true
ENABLE_LOGIN_FORM=true

OAUTH_CLIENT_ID=open-webui
OAUTH_CLIENT_SECRET=<open-webui-client-secret>
OPENID_PROVIDER_URL=https://sso.example.com/realms/ai/.well-known/openid-configuration
OPENID_REDIRECT_URI=https://chat.example.com/oauth/oidc/callback
OAUTH_PROVIDER_NAME=Keycloak
OAUTH_SCOPES=openid email profile groups offline_access llm:invoke
OAUTH_CODE_CHALLENGE_METHOD=S256

OAUTH_GROUP_CLAIM=groups
ENABLE_OAUTH_GROUP_MANAGEMENT=true
ENABLE_OAUTH_GROUP_CREATION=true
```

Keycloak uses the linked client scope and audience mapper, so
`OAUTH_AUTHORIZE_PARAMS` must be unset or `{}`.

Keep `ENABLE_LOGIN_FORM=true` until Keycloak login succeeds. Set it to `false`
only after verifying OIDC login.

Configure the LiteLLM connection to forward the signed-in user's OAuth access
token:

```env
ENABLE_OPENAI_API=true
OPENAI_API_BASE_URL=https://litellm-sso.example.com/v1
OPENAI_API_KEY=
OPENAI_API_CONFIGS={"0":{"auth_type":"system_oauth"}}
ENABLE_BASE_MODELS_CACHE=false
```

Do not configure a shared LiteLLM key for this connection.

See the [Open WebUI Keycloak guide](https://docs.openwebui.com/features/authentication-access/auth/sso/keycloak/)
and [environment-variable reference](https://docs.openwebui.com/reference/env-configuration/).

## User Provisioning

The first delegated request resolves the immutable Keycloak `sub` to a LiteLLM
internal user. If the user does not exist, LiteLLM verifies UserInfo and creates
the record with `max_budget: 0`.

An administrator must then assign:

- A positive budget.
- Explicit allowed models.
- Optional TPM and RPM limits.

An empty model list may mean unrestricted access. Use explicit model names when
the intended policy is restrictive.

## Validation

1. Start Keycloak, PostgreSQL, LiteLLM, the reverse proxy, and Open WebUI.
2. Open `https://litellm.example.com/ui` and sign in as a `/admin` member.
3. Open `https://chat.example.com` and sign in through Keycloak.
4. Make one model request to create the LiteLLM internal-user record.
5. Assign that user a positive budget and explicit allowed models in LiteLLM.
6. Sign out of Open WebUI, sign in again, and retry the model request.
7. Confirm LiteLLM attributes spend to the internal user identified by the
  Keycloak `sub`.

Verify the lane behavior:

```bash
# Native endpoint without a LiteLLM key must fail.
curl -i https://litellm.example.com/v1/models

# Delegated endpoint without a Keycloak access token must fail.
curl -i https://litellm-sso.example.com/v1/models

# Delegated endpoint with the current user access token must succeed after
# assigning a budget and allowed models.
curl -i \
  https://litellm-sso.example.com/v1/models \
  -H "Authorization: Bearer $KEYCLOAK_ACCESS_TOKEN"
```

After changing scopes, audience mappers, or token claims, users must sign out
and sign in again so Open WebUI stores a newly issued access token.

## Troubleshooting

### LiteLLM UI Redirect Error

Verify that:

- `PROXY_BASE_URL` includes `https://`.
- The Keycloak redirect URI is exactly
  `https://litellm.example.com/sso/callback`.
- The reverse proxy preserves the external scheme and host.

### Invalid or Expired OIDC Access Token

Compare the access token with:

```text
OIDC_ISSUER
OIDC_AUDIENCE
OIDC_SIGNING_ALGORITHM
```

Verify that LiteLLM can reach the configured JWKS endpoint.

### Missing `llm:invoke`

Verify that:

- The `llm:invoke` client scope is optional for `open-webui`.
- Open WebUI requests `llm:invoke`.
- `Include in token scope` is enabled.
- The access token's space-delimited `scope` claim contains `llm:invoke`.

### Missing Audience

Verify that the `llm:invoke` scope has an Audience mapper with:

```text
Included Client Audience: litellm
Add to access token: On
```

### Administrator Cannot Access LiteLLM UI

Verify that:

- The user belongs to the top-level Keycloak `admin` group.
- The `groups` scope is requested by `litellm-ui`.
- ID token and UserInfo contain `groups: ["/admin"]`.
- `GENERIC_ROLE_MAPPINGS_ROLES` maps `/admin` to `proxy_admin`.

### First Model Request Is Denied

This is expected for a newly provisioned user. Assign a positive budget and
explicit allowed models, then retry.

# LiteLLM Authentication Architecture

LiteLLM runs as one OSS process with two authentication endpoints:

| Endpoint | Credential | Intended clients |
| --- | --- | --- |
| `https://litellm.$DOMAINNAME` | LiteLLM master or virtual key | CLI, SDK, and admin UI |
| `https://litellm-sso.$DOMAINNAME` | User-delegated OIDC access token | Open WebUI and SSO-aware applications |

Both hostnames forward to the same container and port. Each Traefik middleware
overwrites the fixed `X-LiteLLM-Auth-Lane` header. Both endpoints use
`Authorization: Bearer ...`; the backend never guesses a credential type or
falls back to another authentication method. Alternate API-key headers, URL
query keys, and WebSocket API-key subprotocols are rejected.

This one-process topology requires the repository-built
[`homeserver-litellm`](README.md) image. It is a thin
derivative of the community `nathanael-h/litellm-libre` image and owns one
runtime patch plus the delegated-auth module. A stock LiteLLM Libre image can
load the module, but it cannot dispatch custom and native authentication per
request in the same process. The delegated lane also requires the boolean
`custom_auth_run_common_checks: true`; the patched image rejects delegated
requests before OIDC validation if that invariant is missing.

## Protocol Roles

The client application performs an OIDC authorization-code flow and obtains an
OAuth access token for the LiteLLM resource. LiteLLM is the OAuth resource
server: it verifies that access token and maps its OIDC subject to a LiteLLM
internal user.

## Token Profiles

The image supports both token profiles, but each deployment configures exactly
one issuer and one profile:

| `OIDC_TOKEN_PROFILE` | Permission claim | User token requirement |
| --- | --- | --- |
| `pocket-id` | String array in `scp` | `sub` must not start with `client-` |
| `keycloak` | Space-delimited `scope` string | `typ` is `Bearer`; `preferred_username` must not start with `service-account-` |

The profile selects one exact token contract. LiteLLM does not inspect token
shape to guess a provider and does not fall back to the other profile.
These shapes follow [Pocket ID v2.11.0's access-token tests](https://github.com/pocket-id/pocket-id/blob/v2.11.0/backend/internal/oidc/preview_test.go#L41-L50),
[Pocket ID's client-subject assignment](https://github.com/pocket-id/pocket-id/blob/v2.11.0/backend/internal/oidc/token_handler.go#L96-L102),
[Keycloak's access-token initialization](https://github.com/keycloak/keycloak/blob/main/services/src/main/java/org/keycloak/protocol/oidc/TokenManager.java#L975-L986),
and [Keycloak's service-account prefix](https://github.com/keycloak/keycloak/blob/main/common/src/main/java/org/keycloak/common/constants/ServiceAccountConstants.java#L23-L28).

Both profiles require:

- An asymmetric JWT access token.
- Explicit issuer, JWKS, UserInfo, audience, required scope, token profile, and
  signing algorithm settings.
- A UserInfo endpoint whose `sub` matches the verified access token.

The implementation intentionally does not use discovery, token introspection,
opaque tokens, or provider SDKs. `OIDC_TOKEN_PROFILE` selects only the JWT claim
contract. Each deployment must also provide matching endpoints, clients,
audience, and scope configuration for its selected provider.

## Request Flow

```text
User signs in to a client application
    |
    | user-delegated access token for the LiteLLM resource
    v
LiteLLM verifies issuer, signature, audience, time, subject, and scope
    |
    | OIDC sub maps to a LiteLLM internal user
    v
LiteLLM enforces model access, budget, TPM, and RPM
    |
    v
Configured model provider
```

Using the same identity provider is not sufficient. The client must request a
token for the LiteLLM resource and forward that user's current access token with
every request.

## Pocket ID Configuration

Set `OIDC_TOKEN_PROFILE: pocket-id`.

The Pocket ID resource identifier is `https://llm.$BASE_DOMAINNAME`. It is the
stable access-token audience and does not need to match the external LiteLLM
route at `https://litellm-sso.$DOMAINNAME/v1`.

1. Open **Settings > APIs**, add an API such as `LiteLLM`, and set its permanent
    resource to `https://llm.$BASE_DOMAINNAME`.
2. Add the `llm:invoke` permission.
3. For each allowed OIDC client, open **API access** and grant `llm:invoke` as
    **User-delegated access**.
4. Configure the client to request that resource and permission during its
    authorization-code flow.

Do not grant client access (M2M) for this per-user flow. Machine subjects are
rejected because they cannot be charged to an end user.

See [Pocket ID APIs and permissions](https://pocket-id.org/docs/guides/apis).

## Keycloak Configuration

Set `OIDC_TOKEN_PROFILE: keycloak` and use the realm endpoints:

```yaml
OIDC_ISSUER: https://keycloak.example.com/realms/example
OIDC_JWKS_URL: https://keycloak.example.com/realms/example/protocol/openid-connect/certs
OIDC_USERINFO_URL: https://keycloak.example.com/realms/example/protocol/openid-connect/userinfo
OIDC_AUDIENCE: litellm
OIDC_REQUIRED_SCOPE: llm:invoke
OIDC_TOKEN_PROFILE: keycloak
OIDC_SIGNING_ALGORITHM: RS256
```

In Keycloak:

1. Create or select the client scope that represents `llm:invoke`, include its
    name in the token scope, and link it to every allowed client.
2. Configure an audience mapper so the access token's `aud` contains the exact
    value configured in `OIDC_AUDIENCE`.
3. Ensure the `profile` client scope adds `preferred_username` to access tokens.
4. Create an optional `groups` client scope with a **Group Membership** mapper.
    Set **Token Claim Name** to `groups`, keep **Full group path** enabled, and enable
    **Add to ID token**, **Add to access token**, and **Add to userinfo**.
5. Link the `groups` scope to the LiteLLM and Open WebUI clients. Both clients
    request it explicitly. Create a top-level `admin` group and add LiteLLM
    administrators to it. Keycloak then emits `groups: ["/admin"]`.
6. In the Keycloak deployment, map that exact full path:

    ```yaml
    GENERIC_ROLE_MAPPINGS_ROLES: '{"proxy_admin": ["/admin"]}'
    ```

    The Pocket ID deployment keeps its provider-specific `["admin"]` mapping.
7. Verify the generated access token before starting the deployment: it must
    contain `typ: Bearer`, the configured audience, a space-delimited `scope`
    containing `llm:invoke`, a normal user `preferred_username`, and
    `groups: ["/admin"]` for an administrator. Verify the same `groups` array in
    the ID token and UserInfo.

Keycloak service-account tokens use a `service-account-` preferred username and
are rejected even if they contain the required scope.

See [Keycloak client scopes and audiences](https://www.keycloak.org/docs/latest/server_admin/#_client_scopes)
and [Keycloak's Group Membership mapper](https://www.keycloak.org/admin-api/protocol-mappers#_group-membership).

## Provider-Specific Deployments

Pocket ID and Keycloak run as separate deployments. Each environment has its
own LiteLLM process, Open WebUI process, PostgreSQL data, OIDC clients, and
issuer configuration. A running deployment does not change providers and never
accepts tokens from both issuers.

Configure these values consistently within each environment:

- LiteLLM `GENERIC_*` admin-UI OIDC endpoints and client credentials.
- LiteLLM `OIDC_*` delegated-token validation settings.
- Open WebUI discovery URL, provider name, scopes, and OIDC client credentials.
- The provider-specific audience configuration.

Pocket ID clients send the RFC 8707 `resource` parameter. Keycloak clients do
not send that Pocket ID parameter; their linked client scope and audience mapper
place the LiteLLM audience in the access token.

## Delegated Client Contract

A web client normally requests:

- The `llm:invoke` permission.
- Its required identity scopes.
- `offline_access` when it needs refresh tokens.

Pocket ID clients also request the `https://llm.$BASE_DOMAINNAME` resource.
Keycloak clients request the linked client scope that produces the configured
LiteLLM audience.

Every delegated LiteLLM request sends:

```http
Authorization: Bearer <current-user-access-token>
```

The client refreshes expired tokens. A shared API key must not replace the user
token because it collapses attribution and enforcement to one identity.

## Gateway Enforcement

`oidc_delegated_auth.py`, baked into the image:

1. Verifies the configured asymmetric JWT signature.
2. Validates `iss`, `aud`, `sub`, `iat`, `exp`, and the required scope.
3. Enforces the configured Pocket ID or Keycloak token profile.
4. Rejects ID tokens and machine identities.
5. Uses UserInfo on first use to verify and provision the identity.
6. Resolves the immutable OIDC `sub` to a LiteLLM internal user.
7. Restricts delegated identities to LiteLLM's `openai_routes` group.

The `openai_routes` group includes OpenAI-compatible chat, responses, embeddings,
audio, images, files, batches, assistants, realtime, rerank, search, OCR, and
vector store routes. Management routes remain unavailable to delegated identities.

`GET /health/liveliness` remains public for the container health check.
`custom_auth_run_common_checks: true` loads the matched database user and
enforces model, spend, TPM, and RPM controls.

## User Provisioning

The first delegated request creates or links the LiteLLM user. New records use
the fail-closed `max_budget: 0` default from
[`config.yaml`](../../configs/litellm/config.yaml). An administrator must then
assign a positive budget and explicit allowed models.

Verified email can link a pre-existing UI SSO record during first use.
Subsequent authentication resolves by immutable OIDC `sub`.

The administration UI is always available at:

```text
https://litellm.$DOMAINNAME/ui
```

Its SSO login uses LiteLLM's generic OIDC authorization-code flow with PKCE.
The active provider must allow
`https://litellm.$DOMAINNAME/sso/callback` as a redirect URI.
This is a single-instance deployment, so the verifier uses the process cache;
strict cache-miss handling fails closed if the process restarts during login.
The main hostname selects native authentication before LiteLLM interprets the
standard bearer credential. `ui_access_mode: admin_only` rejects SSO users who
do not map to an administrative LiteLLM role.

## Spend Controls

Spend limits require nonzero model pricing. LiteLLM uses built-in pricing for
known models. Configure explicit input and output prices for local or custom
models:

```yaml
model_info:
  input_cost_per_token: 0.000001
  output_cost_per_token: 0.000002
```

These values represent $1 and $2 per million tokens. Models with both prices set
to zero bypass monetary budget checks; TPM and RPM limits remain independent.

Typical internal-user controls are:

```yaml
max_budget: 10
budget_duration: 30d
models:
  - allowed-model
```

Do not treat an empty `models` list as deny-all. Use explicit models or the
intended LiteLLM access group.

Delegated usage is attributed to the **Internal User**. **End User** can remain
empty because it comes from the optional OpenAI request-body `user` field.
**Key Alias** is empty because delegated requests do not use a virtual key.

`STORE_PROMPTS_IN_SPEND_LOGS` is enabled in
[`apps/litellm.yml`](../../apps/litellm.yml); set retention according to the
deployment's privacy requirements.

See [LiteLLM custom pricing](https://docs.litellm.ai/docs/proxy/custom_pricing)
and [LiteLLM spend tracking](https://docs.litellm.ai/docs/proxy/cost_tracking).

## Open WebUI

With Pocket ID, Open WebUI requests the LiteLLM resource and permission:

```yaml
OAUTH_SCOPES: openid email profile groups offline_access llm:invoke
OAUTH_AUTHORIZE_PARAMS: '{"resource":"https://llm.$BASE_DOMAINNAME"}'
```

Its OpenAI-compatible connection forwards the signed-in user's access token:

```yaml
ENABLE_OPENAI_API: true
OPENAI_API_BASE_URL: https://litellm-sso.$DOMAINNAME/v1
OPENAI_API_KEY: ""
OPENAI_API_CONFIGS: '{"0":{"auth_type":"system_oauth"}}'
```

Existing sessions must sign out and back in after changing the requested
resource or permission.

With Keycloak, keep `groups` and `llm:invoke` in `OAUTH_SCOPES`, point
`OPENID_PROVIDER_URL` at the realm discovery document, and remove
`OAUTH_AUTHORIZE_PARAMS`. The linked Keycloak client scope and audience mapper
must place the LiteLLM audience and permission in the access token.

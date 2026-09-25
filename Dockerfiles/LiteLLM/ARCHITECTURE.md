# LiteLLM Authentication and User Policy

One LiteLLM OSS process serves the Admin UI, native keys, and OIDC access
tokens against one PostgreSQL-backed policy and model catalog.

```text
Open WebUI / OAuth client -- Bearer <user access token>  --> LiteLLM --> provider
Langflow / CLI / SDK      -- Bearer sk-<user's own key>  --> LiteLLM --> provider
Administrator             -- master key / UI SSO         --> LiteLLM
```

## Identity model

| Caller | Credential | LiteLLM identity |
| --- | --- | --- |
| App holding the user's token | OIDC access token for the LiteLLM API resource | Internal User `sub` |
| Person using Langflow, a CLI, or an SDK | Virtual key owned by that Internal User | Internal User `sub` (`key.user_id`) |
| Backend service without a user | Its own virtual key | Key; optional native end-user tracking |
| Administrator | Master key or Admin UI SSO session | `proxy_admin` |

The Internal User is the policy scope for humans: allowed models,
`max_budget`, `budget_duration`, TPM/RPM, and spend. LiteLLM enforces it
natively for OIDC tokens and for every virtual key the user owns, so spend
from Open WebUI, Langflow, and scripts aggregates on one record.

## OAuth 2.0 resource server

[`user_auth.py`](user_auth.py) validates [RFC 9068](https://www.rfc-editor.org/rfc/rfc9068.html)
JWT access tokens locally with PyJWT: JWKS signature with the pinned
algorithm, exact issuer and audience, `exp`/`iat`, the `typ: at+jwt` header
(rejects ID tokens), and the required permission in the standard
space-delimited `scope` claim. The verified `sub` selects the Internal User.
The issuer is fixed by configuration, so `sub` alone identifies the human
([OIDC claim stability](https://openid.net/specs/openid-connect-core-1_0.html#ClaimStability));
never join users by email or username.

```yaml
LITELLM_OIDC_ISSUER: https://pocketid.$BASE_DOMAINNAME
LITELLM_OIDC_JWKS_URL: https://pocketid.$BASE_DOMAINNAME/.well-known/jwks.json
LITELLM_OIDC_AUDIENCE: https://llm.$BASE_DOMAINNAME
LITELLM_OIDC_REQUIRED_SCOPE: llm:invoke
LITELLM_OIDC_SIGNING_ALGORITHM: RS256
```

The hook exists only because LiteLLM's native `enable_jwt_auth` is
Enterprise-gated. It returns `None` for credentials it does not handle and
[`custom-auth-fallback.patch`](custom-auth-fallback.patch) lets LiteLLM
continue with native master-key, virtual-key, and public-route
authentication; upstream documents that mixed mode
(`custom_auth_settings.mode: auto`) as Enterprise-only. See the
[custom-auth contract](https://docs.litellm.ai/docs/proxy/custom_auth).

Resolved users receive `allowed_routes: openai_routes + model_info_routes`
plus model retrieval (`/v1/models/*`, `/models/*`): they can invoke models and
read model metadata but cannot manage keys, users, or models, whatever the
user's UI role.
`custom_auth_run_common_checks` and `enable_post_custom_auth_checks` delegate
model, budget, and rate-limit enforcement to LiteLLM. The hook rejects every
request with 500 unless both are set, because without
`custom_auth_run_common_checks` LiteLLM skips its common checks for every
credential.

Validation is local: a revoked token stays valid until `exp`, the JWKS cache
lasts five minutes, and an unreachable JWKS endpoint fails closed with 503.

## Personal virtual keys

Tools that run without the user's token, such as Langflow flows that run
server-side, use a virtual key owned by the user's Internal User. An
administrator mints it in the Admin UI or with `/key/generate` and
`user_id: <sub>`, or sets `ui_access_mode: all` so users mint their own.
LiteLLM caps every key without a team by its owner's models
(`can_user_call_model`) and `max_budget`, and records its spend on the owner.
Assign the user's models before issuing a key: for native keys an empty model
list means all models.

## Provisioning and fail-closed defaults

The first OIDC request or Admin UI SSO login creates the `sub`-keyed Internal
User from `default_internal_user_params` (`max_budget: 0`, no models).
`GENERIC_USER_ID_ATTRIBUTE: sub` keeps both paths on one record. Users created
by an OIDC request have no email; look up their `sub` in the provider. The hook
rejects users whose `models` list is empty because LiteLLM treats `[]` as
unrestricted and skips budget checks for zero-cost models. An administrator
then assigns models (or a model access group) and a budget in the Admin UI.
`fail_closed_budget_enforcement` rejects requests whose current spend cannot
be verified. Monetary budgets need nonzero model pricing; TPM/RPM are
independent.

`ui_access_mode: admin_only` limits the UI to administrators. Open WebUI users
need no key; see [Personal virtual keys](#personal-virtual-keys) for Langflow,
CLI, and SDK use.

## Client contracts

- OAuth clients request `llm:invoke` for the LiteLLM API resource
  ([Provider notes](#provider-notes)), send
  `Authorization: Bearer <access token>`, and refresh it themselves. Grant the
  permission as user-delegated access only, never to client-credentials
  clients.
- A person's own virtual key is bounded by that user's models and budget.
- A backend with no user context uses its own key. It may name an end user
  with LiteLLM's `x-litellm-end-user-id` header; LiteLLM records that end user
  natively and can budget it through `/customer/new`, but per-user model
  policy does not apply.

## Provider notes

- PocketID issues RFC 9068 tokens for its APIs: define the API resource, add
  the `llm:invoke` permission, and grant it per client as user-delegated
  access ([PocketID APIs](https://pocket-id.org/docs/guides/apis)). Clients
  request it with `resource=https://llm.$BASE_DOMAINNAME`.
- Keycloak 26.2+: on every client that calls LiteLLM, enable *Use "at+jwt" as
  access token header type* (Advanced → Fine grain OpenID Connect
  configuration). It is off by default, and LiteLLM rejects the plain `JWT`
  header with 401. Create a client scope named `llm:invoke` with an Audience
  mapper and link it only to clients with service accounts off. Keycloak does
  not implement RFC 8707 `resource`, so leave Open WebUI's
  `OAUTH_AUTHORIZE_PARAMS` unset. Issuer: `https://<host>/realms/<realm>`;
  JWKS: `<issuer>/protocol/openid-connect/certs`.
- Pairwise subjects differ per client; configure a shared identity so one
  human maps to one Internal User across applications.
- Switching providers changes every `sub`: users get new fail-closed Internal
  Users and need models and budgets reassigned.

## Verification contract

[`verify_user_auth.py`](verify_user_auth.py) runs during the image build:

- credentials other than JWTs, including master and virtual keys, bypass the
  hook and use LiteLLM's native authentication;
- valid tokens resolve to the upserted Internal User; wrong signature,
  issuer, audience, expiry, subject, token type, or scope fail closed;
- users without a model policy are rejected; user lookup failures return 503;
- resolved users cannot call key, user, or model management routes;
- `/model/info` listings and direct-ID lookups apply the caller's model and
  team scope ([`model-info-access.patch`](model-info-access.patch));
- OIDC tokens and native keys run through the installed authentication chain,
  which enforces denied models, per-model and total user budgets (also for a
  Responses WebSocket first frame), and scoped model retrieval; with either
  enforcement setting off, every credential is rejected.

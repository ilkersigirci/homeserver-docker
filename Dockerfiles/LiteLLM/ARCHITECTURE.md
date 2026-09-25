# LiteLLM Authentication and User Policy

How this image authenticates OIDC access tokens, Admin UI SSO logins, and
virtual keys against one PostgreSQL-backed policy and model catalog. Image
contents, upstream workarounds, and upgrades are in [README.md](README.md).

## Identity model

| Caller | Credential | LiteLLM identity |
| --- | --- | --- |
| App holding the user's token | OIDC access token for the LiteLLM API resource | Internal User `sub` |
| Person using Langflow, a CLI, or an SDK | Virtual key owned by that Internal User | Internal User `sub` (`key.user_id`) |
| Backend service without a user | Its own virtual key | Key; optional native end-user tracking |
| Administrator | Master key or Admin UI SSO session | `proxy_admin` |

The Internal User is the policy scope for humans: allowed models,
`max_budget`, `budget_duration`, TPM/RPM, and spend. A person's OIDC token and
[personal keys](#personal-virtual-keys) share it, so spend from Open WebUI,
Langflow, and scripts aggregates on one record.

## OAuth 2.0 resource server

[`user_auth.py`](src/user_auth.py) validates [RFC 9068](https://www.rfc-editor.org/rfc/rfc9068.html)
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

Startup fails if any setting is missing or the algorithm is symmetric.

The hook exists only because LiteLLM's native `enable_jwt_auth` is
Enterprise-gated. It returns `None` for credentials it does not handle and
[`custom-auth-fallback.patch`](patches/permanent/custom-auth-fallback.patch)
lets LiteLLM continue with native master-key, virtual-key, and public-route
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
credential. Two [temporary patches](README.md#temporary-upstream-workarounds)
close upstream gaps in that enforcement.

Traefik adds no authentication in front of LiteLLM. Validation is local: a
revoked token stays valid until `exp`, the JWKS cache lasts five minutes, and
an unreachable JWKS endpoint fails closed with 503.

The JWKS client follows LiteLLM's native TLS settings. To trust a private CA
(for example, a self-hosted Keycloak), mount a PEM bundle containing the public
roots plus that CA and set `SSL_CERT_FILE` to its path. As a last resort, set
`LITELLM_SSL_VERIFY=false` in the host's `.env`; Compose passes it as
LiteLLM's native `SSL_VERIFY`, which disables certificate checks for all
LiteLLM outbound requests, including LLM providers. JWT signature and claim
checks still apply.

## Admin UI SSO

The Admin UI uses LiteLLM's native generic OIDC SSO with PKCE against the same
provider ([`apps/litellm.yml`](../../apps/litellm.yml)).
`GENERIC_USER_ID_ATTRIBUTE: sub` resolves an SSO login and an OIDC request to
the same Internal User. The `groups` claim maps `admin` to `proxy_admin`, and
`ui_access_mode: admin_only` limits the UI to administrators.
[`sso.patch`](patches/permanent/sso.patch) removes the OSS five-user SSO cap
and the SSO debug-login license gate.

## Personal virtual keys

Tools that run without the user's token, such as Langflow, use a virtual key
owned by the user's Internal User. An administrator mints it in the Admin UI
or with `/key/generate` and `user_id: <sub>`, or sets `ui_access_mode: all` so
users mint their own. LiteLLM caps every key without a team by its owner's
models (`can_user_call_model`) and `max_budget`, and records its spend on the
owner; restrictions on the key itself still apply. Native key listings follow
the key's model policy.

## Provisioning and model access

The first OIDC request or Admin UI SSO login creates the `sub`-keyed Internal
User from `default_internal_user_params` (`max_budget: 0`, empty model list).
Users created by an OIDC request have no email; look up their `sub` in the
provider. An empty `models` list allows all models. Assign models (or a model
access group) in the Admin UI to limit which models the user can see and
invoke. New users can list models immediately; their zero budget blocks paid
model calls until an administrator assigns a budget. Zero-cost models are
exempt from monetary budget checks.
`fail_closed_budget_enforcement` rejects requests whose current spend cannot
be verified. Monetary budgets need nonzero model pricing; TPM/RPM are
independent.

## Client contracts

- OAuth clients request `llm:invoke` for the LiteLLM API resource
  ([Provider notes](#provider-notes)), send
  `Authorization: Bearer <access token>`, and refresh it themselves. Grant the
  permission as user-delegated access only, never to client-credentials
  clients. Open WebUI adds `llm:invoke` to `OAUTH_SCOPES`, sends the resource
  in `OAUTH_AUTHORIZE_PARAMS`, and forwards the token with
  `auth_type: system_oauth` ([`apps/open-webui.yml`](../../apps/open-webui.yml)).
- A backend with no user context uses its own key. It may name an end user
  with LiteLLM's `x-litellm-end-user-id` header; LiteLLM records that end user
  natively and can budget it through `/customer/new`, but per-user model
  policy does not apply.

## Provider notes

- PocketID issues RFC 9068 tokens for its APIs: define the API resource, add
  the `llm:invoke` permission, and grant it per client
  ([PocketID APIs](https://pocket-id.org/docs/guides/apis)). Clients
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
- To switch providers, update `LITELLM_OIDC_*`, the Admin UI `GENERIC_*`
  settings, and each client's login, such as
  [Langflow's](../LangflowBackend/README.md#browser-login). The switch changes
  every `sub`: users get new Internal Users from the defaults; reapply any
  model restrictions and budgets.

## Verification

[`verify_user_auth.py`](tests/verify_user_auth.py) checks the behavior described
here: token validation, native credential fallback, route limits, model
access, budgets, and the enforcement-settings guard. Change it together with
this document.

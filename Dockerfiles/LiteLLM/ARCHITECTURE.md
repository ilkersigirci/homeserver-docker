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

LiteLLM's native [JWT auth](https://docs.litellm.ai/docs/proxy/token_auth)
(`enable_jwt_auth`, [`config.yaml`](../../configs/litellm/config.yaml))
validates [RFC 9068](https://www.rfc-editor.org/rfc/rfc9068.html#section-4)
access tokens locally: the JWKS signature (asymmetric algorithms only) and the
exact issuer and audience. [`jwt-auth.patch`](patches/permanent/jwt-auth.patch)
adds the `typ: at+jwt` header check, which rejects ID tokens, and the
[`access_token.py`](src/access_token.py) `custom_validate` hook requires `exp`,
a non-empty `sub`, and the `llm:invoke` permission in the space-delimited
`scope` claim. The verified `sub` selects the Internal User. The issuer is
fixed by configuration, so `sub` alone identifies the human
([OIDC claim stability](https://openid.net/specs/openid-connect-core-1_0.html#ClaimStability));
`user_email_jwt_field` stays unset so users are never joined by email.

```yaml
JWT_PUBLIC_KEY_URL: https://pocketid.$BASE_DOMAINNAME/.well-known/openid-configuration
JWT_ISSUER: https://pocketid.$BASE_DOMAINNAME
JWT_AUDIENCE: https://llm.$BASE_DOMAINNAME
```

`JWT_PUBLIC_KEY_URL` is the issuer's
[OIDC Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html)
document, from which LiteLLM reads the `jwks_uri` signing keys, so it is always
`<issuer>/.well-known/openid-configuration`, whatever the provider.

The feature lives in MIT-licensed code outside `enterprise/`, behind a
`premium_user` gate. The patch removes that gate and keeps every token acting
as its Internal User:

- `/v1/models` and `/model/info` list the user's own models; upstream enforces
  them on calls but lists only key and team models.
- Upstream's single-team fallback is skipped. It would replace the models and
  personal budget of a user with exactly one team by that team's, so adding a
  user to a team for MCP grants would change their model policy.
- On MCP routes the user is admitted as LiteLLM admits its own MCP logins
  (`MCPRequestHandler.reload_admitted_user`). Users reach `allow_all_keys`
  servers plus the servers the Admin UI grants to them and to every team they
  belong to; an administrator gets LiteLLM's admin view.

LiteLLM treats any three-part bearer token as a JWT, so master and virtual
keys keep native authentication.

`enforce_rbac` with `role_permissions` limits every token to
`openai_routes + model_info_routes + mcp_inference_routes` plus model
retrieval (`/v1/models/*`, `/models/*`; the latter also matches the Google
GenAI-style `/models/{model}:generateContent` routes, still model-checked).
Users can invoke models, read model metadata, and list and call MCP tools, but
cannot manage keys, users, models, or MCP servers. `admin_allowed_routes: []`
disables LiteLLM's built-in `litellm_proxy_admin` token scope, so no token
reaches management routes. Following [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html#section-2.3),
the audience and scope restrict what a token may do, and the user's own
entitlements apply within that. The route limit follows the token, so a
`proxy_admin` user's token is still route-limited, while the admin keeps
unrestricted models and budget on those routes, as with LiteLLM's own logins.
That admin role is the one stored in LiteLLM, not re-read from the token, so
demoting someone in the provider takes effect once their LiteLLM role changes.

LiteLLM's common checks enforce the user's models, budgets, and rate limits
for tokens as for keys, and client-supplied fallbacks must be models the user
may call. Three [temporary patches](README.md#temporary-upstream-workarounds)
close upstream gaps in that enforcement. `end_user_id_jwt_field: sub` pins the
OpenAI `user` field to the same subject.

Traefik adds no authentication in front of LiteLLM. Validation is local: a
revoked token stays valid until `exp`. The discovery document and the keys
are each cached for `public_key_ttl` (600 s). If a refetch fails at the
network level (connection or TLS error), the last fetched copy stays usable
for `public_key_stale_ttl` (3600 s), and without one requests fail with 503.
An HTTP error response, such as Traefik's 502 while PocketID is down, gets no
grace period: tokens fail with 401 once the cache expires. LiteLLM refetches
keys when that cache expires, not on an unknown `kid` as
[OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html#RotateSigKeys)
describes. PocketID rotates its signing key only through `pocket-id
key-rotate`, which replaces it at once, so restart LiteLLM after a rotation.
There is no clock leeway, so keep hosts on NTP: a provider clock ahead of
LiteLLM's rejects fresh tokens (`iat`).

The JWKS client follows LiteLLM's native TLS settings
([`jwt-jwks-ssl.patch`](patches/temporary/jwt-jwks-ssl.patch)). To trust a
private CA (for example, a self-hosted Keycloak), mount a PEM bundle
containing the public roots plus that CA and set `SSL_CERT_FILE` to its path.
As a last resort, set `LITELLM_SSL_VERIFY=false` in the host's `.env`; Compose
passes it as LiteLLM's native `SSL_VERIFY` environment variable, which
disables certificate checks for all LiteLLM outbound requests, including LLM
providers and the JWKS fetch. JWT signature and claim checks still apply. The
JWKS client is built at startup, before `config.yaml` loads, so it reads the
environment variable, not `litellm_settings.ssl_verify`.

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
the key's model policy. Owners and administrators can regenerate a leaked key
in place, keeping its settings.

## Provisioning and model access

The first OIDC request (`user_id_upsert`) or Admin UI SSO login creates the
`sub`-keyed Internal User from `default_internal_user_params`
(`max_budget: 0`, empty model list). Users created by an OIDC request have no
email; look up their `sub` in the provider. An empty `models` list allows all
models. Assign models (or a model access group) in the Admin UI to limit which
models the user can see and invoke, and per-model budgets to cap spend on
individual models. New users can list models immediately;
their zero budget blocks paid model calls until an administrator assigns a
budget. Zero-cost models are exempt from monetary budget checks.
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
- Caller `x-` headers reach `langflow/*` deployments only, carrying Open
  WebUI's [Langflow session header](../LangflowBackend/README.md#open-webui).
  Langflow's Responses endpoint ignores its variable-override headers.

## Provider notes

- PocketID issues RFC 9068 tokens for its APIs: define the API resource, add
  the `llm:invoke` permission, and grant it per client
  ([PocketID APIs](https://pocket-id.org/docs/guides/apis)). Clients
  request it with `resource=https://llm.$BASE_DOMAINNAME`.
- Keycloak 26.2+: on every client that calls LiteLLM, enable *Use "at+jwt" as
  access token header type* (Advanced → Fine grain OpenID Connect
  configuration). It is off by default, and LiteLLM rejects the plain `JWT`
  header with 401. Create a client scope named `llm:invoke` with an Audience
  mapper and link it only to clients with service accounts off. Keycloak does not
  implement RFC 8707 `resource`, so leave Open WebUI's
  `OAUTH_AUTHORIZE_PARAMS` unset. Issuer: `https://<host>/realms/<realm>`.
- Pairwise subjects differ per client; configure a shared identity so one
  human maps to one Internal User across applications.
- To switch providers, update `JWT_*`, the Admin UI `GENERIC_*` settings, and
  each client's login, such as
  [Langflow's](../LangflowBackend/README.md#browser-login). The switch changes
  every `sub`: users get new Internal Users from the defaults; reapply any
  model restrictions and budgets.

## Verification

[`verify_jwt_auth.py`](tests/verify_jwt_auth.py) runs the installed auth chain
with the settings described here: token validation, native credential
fallback, route limits, model access and listings, budgets, and MCP grants.
The MCP principal is internal to LiteLLM, so the check resolves grants with
LiteLLM's own resolver on every build. Change it together with this document
and [`config.yaml`](../../configs/litellm/config.yaml).

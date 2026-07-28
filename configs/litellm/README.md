# Pocket ID Delegated Authentication

LiteLLM uses Pocket ID access tokens to identify end users without issuing a
shared LiteLLM key to client applications. LiteLLM remains the authority for
model access, spend limits, and request limits.

## Request Flow

```text
User signs in to an application with Pocket ID
    |
    | user-delegated access token
    v
Application calls litellm-sso
    |
    | Pocket ID sub maps to a LiteLLM internal user
    v
LiteLLM enforces models, spend budget, TPM, and RPM
    |
    v
Configured model provider
```

Using the same SSO provider is not sufficient by itself. The application must
request a token for the LiteLLM resource and forward that user's current token
with every request.

## Components

- `litellm-sso` is the inference gateway. Its custom authentication hook accepts
  delegated Pocket ID access tokens.
- `litellm-admin` is a separate, on-demand administration interface backed by
  the same database. Standard users do not need to sign in to it.
- A client application signs users in with Pocket ID and forwards each user's
  current access token to `litellm-sso`.

The two LiteLLM processes are required for this OSS design. Combining custom
authentication with native virtual-key authentication in one process requires
LiteLLM Enterprise. `litellm-sso` therefore handles delegated inference while
the temporary `litellm-admin` process provides native UI and key administration
against the same database.

The Pocket ID resource identifier is `https://llm.$BASE_DOMAINNAME`. It is the
stable token audience and does not need to match the external LiteLLM API route
at `https://litellm.$DOMAINNAME/v1`.

## Pocket ID API Permission

Create a dedicated Pocket ID API so LiteLLM receives access tokens intended for
this gateway, not ID tokens or access tokens issued for another service:

1. Open **Settings > APIs**, add an API such as `LiteLLM`, and set its permanent
    resource to `https://llm.$BASE_DOMAINNAME`.
2. Add the `llm:invoke` permission with a description such as `Invoke models
    through LiteLLM`.
3. For each allowed application, open **Settings > OIDC Clients > API access**
    and grant `llm:invoke` as **User-delegated access**.
4. Have the application request the resource and permission during its normal
    authorization-code flow.

The resource becomes the token audience, and `llm:invoke` limits which OIDC
clients may obtain a delegated token accepted by `litellm-sso`. It authorizes
entry to the gateway; LiteLLM's user record separately controls models, spend
budgets, and rate limits. Do not enable client access (M2M) for this per-user
flow because it has no user identity to charge.

See [Pocket ID APIs and permissions](https://pocket-id.org/docs/guides/apis).

## Client Contract

A web client normally uses an authorization-code flow and requests:

- The `llm:invoke` permission.
- The `https://llm.$BASE_DOMAINNAME` resource.
- Standard identity scopes required by the client.
- `offline_access` when the client needs refresh tokens.

For every LiteLLM request, the client must send:

```http
Authorization: Bearer <current-user-access-token>
```

The client is responsible for refreshing expired access tokens. Do not replace
the user token with a shared API key: a shared identity prevents LiteLLM from
selecting the correct user record and enforcing that user's controls.

## Gateway Enforcement

`pocketid_auth.py`:

1. Assigns the delegated identity LiteLLM's native `openai_routes` route group.
2. Reads the bearer token from the request.
3. Verifies its RS256 signature against the Pocket ID JWKS.
4. Validates the issuer, audience, timestamps, and `llm:invoke` permission.
5. Rejects client-credential subjects; a delegated user token is required.
6. Resolves the LiteLLM user by the immutable Pocket ID `sub`.
7. Returns the user's identity and control values to LiteLLM.

The native group covers LiteLLM's OpenAI-compatible data plane, including chat,
responses, embeddings, audio, images, videos, files, batches, fine-tuning,
assistants, threads, realtime, rerank, search, OCR, vector stores, and
containers. It also includes state-changing operations such as file uploads and
deletions, so `llm:invoke` means access to that data plane rather than only
stateless inference.

`GET /health/liveliness` remains public for the container health check. After
custom authentication, LiteLLM returns `403` for routes outside
`openai_routes`, including key, user, team, model, and spend management. The
group comes from the installed LiteLLM package; review its membership when
upgrading the pinned image.

`custom_auth_run_common_checks: true` makes LiteLLM load the matching database
record and enforce its model allowlist and spend budget. The authentication
result also carries current spend, TPM, and RPM limits.

The UserInfo endpoint is queried only when a subject is not already linked.
Verified email matching can link a pre-existing SSO record during that first
request, but subsequent authentication uses `sub`.

## User Provisioning

Users should first sign in to the client application, not `litellm-admin`. The
client's first model request automatically creates or links their LiteLLM
record.

New records receive `max_budget: 0`. An administrator then assigns a positive
budget and allowed models. The user reloads the client application after the
update.

For bulk onboarding, pre-create users through LiteLLM administration using their
Pocket ID `sub`, or define a deliberately limited baseline in
`default_internal_user_params`.

## Spend Limits

LiteLLM calculates spend from model usage and pricing, attributes it to the
internal user selected by Pocket ID `sub`, and compares accumulated spend with
that user's budget before allowing further requests.

### Model Pricing

Spend limits require meaningful model pricing. LiteLLM uses its built-in cost
map for known models. For local or custom models, configure an input and output
price in the Models section of `litellm-admin`.

The equivalent `config.yaml` structure is:

```yaml
model_info:
  input_cost_per_token: 0.000001
  output_cost_per_token: 0.000002
```

These values represent $1 per million input tokens and $2 per million output
tokens. They can represent an internal accounting rate for locally hosted
models; they do not need to be an external provider invoice.

Important pricing behavior:

- Existing spend records are not recalculated after pricing changes.
- A model with both token prices explicitly set to zero bypasses all LiteLLM
  budget checks.
- Unknown models must be tested to confirm that requests produce nonzero cost.
- TPM and RPM limits do not depend on monetary pricing.

See [LiteLLM custom pricing](https://docs.litellm.ai/docs/proxy/custom_pricing).

### User Controls

Configure each internal user in `litellm-admin`:

```yaml
max_budget: 10
budget_duration: 30d
models:
  - allowed-model
```

- `max_budget` is the maximum spend in dollars according to the configured
  model prices. `null` means uncapped.
- `budget_duration` resets the enforcement counter on that interval. A value
  such as `30d` creates a recurring budget; omitting it creates a non-recurring
  limit.
- `models` is the model allowlist. Do not treat an empty list as deny-all;
  configure explicit models or LiteLLM's `all-proxy-models` access group.
- `tpm_limit` and `rpm_limit` provide independent capacity controls.

LiteLLM 1.92.0 does not apply a user record's `max_parallel_requests` to this
custom-auth flow.

`max_budget: 0` is a fail-closed onboarding default for priced models. It does
not block models deliberately configured with zero cost because those models
bypass budget enforcement.

### Attribution and Verification

Delegated requests are recorded against LiteLLM's **Internal User**. The
**End User** field may be empty because it comes from the optional OpenAI
request-body `user` field. **Key Alias** is empty because this flow does not use
a LiteLLM virtual key.

After changing model pricing or a user budget:

1. Send a small request through the client application.
2. Confirm the Usage page attributes nonzero spend to the expected Internal
    User.
3. For direct or streaming requests, also check for a nonzero
    `x-litellm-response-cost` response header. Some clients do not expose it.
4. Test that a deliberately small budget rejects a request after it is
    exhausted.

The database retains spend logs even when a recurring budget counter resets.
`STORE_PROMPTS_IN_SPEND_LOGS` is currently enabled in `apps/litellm.yml`, so
those logs also retain prompt content. Spend accounting does not require prompt
storage; disable it or define retention according to the deployment's privacy
requirements.

See [LiteLLM spend tracking](https://docs.litellm.ai/docs/proxy/cost_tracking)
and [custom-auth enforcement](https://docs.litellm.ai/docs/proxy/custom_auth).

## Open WebUI Example

Open WebUI requests a Pocket ID token for the LiteLLM resource and stores the
OAuth session server-side:

```yaml
OAUTH_SCOPES: openid email profile groups offline_access llm:invoke
OAUTH_AUTHORIZE_PARAMS: '{"resource":"https://llm.$BASE_DOMAINNAME"}'
```

After adding or changing the resource or permission, existing sessions must
sign out and back in once. Reloading does not replace an access token issued
without the new audience or scope.

Its OpenAI-compatible connection forwards the signed-in user's access token:

```yaml
ENABLE_OPENAI_API: true
OPENAI_API_BASE_URL: https://litellm.$DOMAINNAME/v1
OPENAI_API_KEY: ""
OPENAI_API_CONFIGS: '{"0":{"auth_type":"system_oauth"}}'
```

LiteLLM is the model entitlement and spend authority for this connection. Open
WebUI's duplicate model ACL and shared model cache are disabled, and direct
connections are prohibited:

```yaml
BYPASS_MODEL_ACCESS_CONTROL: true
ENABLE_BASE_MODELS_CACHE: false
ENABLE_DIRECT_CONNECTIONS: false
```

This configuration is appropriate while all inference models are
LiteLLM-backed. Re-enable Open WebUI model access control before relying on
private or group-shared Open WebUI workspace models.

Open WebUI image generation and Mistral OCR currently use separate shared
provider credentials. Their usage is not attributed to the Pocket ID user and
does not consume the user's LiteLLM budget.

## Administration

Start the administration interface only while managing users, spend budgets,
model pricing, model access, or native virtual keys:

```bash
docker compose --env-file .env --file compose/gpu.yml --profile litellm-admin up -d litellm-admin
docker compose --env-file .env --file compose/gpu.yml --profile litellm-admin stop litellm-admin
```

The interface is available at `https://litellm-admin.$DOMAINNAME/ui`. Stopping
it does not affect the shared database or `litellm-sso`.

## Validation

After changing the auth hook, route policy, or LiteLLM image, run:

```bash
docker exec -i -e PYTHONPATH=/app/litellm-config litellm-sso python - < tests/litellm/test_pocketid_auth.py
```

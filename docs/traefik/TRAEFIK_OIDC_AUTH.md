# Traefik OIDC Authentication

`traefik-oidc-auth` handles Langflow's browser login only. LiteLLM validates
OIDC access tokens itself and needs no Traefik authentication contract; see
[`Dockerfiles/LiteLLM/ARCHITECTURE.md`](../../Dockerfiles/LiteLLM/ARCHITECTURE.md).

## Configuration location

The plugin version is registered in [`apps/traefik.yml`](../../apps/traefik.yml).
The Langflow middleware is defined in
[`configs/traefik3/rules.specific/gpu_coding.yml`](../../configs/traefik3/rules.specific/gpu_coding.yml).

## Langflow browser login

`langflow-oidc` runs the authorization-code flow with PKCE, keeps the
encrypted session cookie, refreshes tokens, and sets
`Authorization: Bearer <ID token>` on upstream requests. Langflow's native
external auth validates the issuer, the audience (`LANGFLOW_CLIENT_ID`), and
the signature, then provisions the local user from the token claims. The
backend must stay reachable only through Traefik.

`langflow-responses-rtr` is the exception: `/api/v1/responses` requests that
carry an API key skip browser OIDC so OpenAI clients and LiteLLM can run
saved flows.

Register this callback in PocketID:

```text
https://langflow.<DOMAINNAME>/oidc/callback
```

The Langflow client needs login scopes only. Model calls inside flows use each
user's own LiteLLM virtual key; see
[`Dockerfiles/LangflowBackend/README.md`](../../Dockerfiles/LangflowBackend/README.md#use-litellm-from-a-langflow-flow).

## LiteLLM API bearer tokens

Open WebUI requests `llm:invoke` for the `https://llm.<BASE_DOMAINNAME>`
resource at login and sends the resulting user access token to
`https://litellm.<DOMAINNAME>/v1` with `auth_type: system_oauth`. LiteLLM
checks the RFC 9068 `typ: at+jwt` header, signature, exact issuer and
audience, expiry, and scope, then resolves `sub` to an Internal User.
Requests fail until that user has explicit models and a budget. ID tokens are
for OIDC clients and are rejected by the LiteLLM API. See
[PocketID's API guide](https://pocket-id.org/docs/guides/apis).

Tools without a user token, such as Langflow, use a LiteLLM virtual key owned
by the user's Internal User instead.

## Provider changes

For another provider, such as Keycloak, update LiteLLM's `LITELLM_OIDC_*`
settings and Langflow's browser login. See LiteLLM's
[provider notes](../../Dockerfiles/LiteLLM/ARCHITECTURE.md#provider-notes).

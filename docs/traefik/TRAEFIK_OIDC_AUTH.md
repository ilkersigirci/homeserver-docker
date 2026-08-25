# Traefik OIDC Authentication

`traefik-oidc-auth` runs the OIDC authorization-code flow at Traefik and passes
the resulting access token to the upstream application.

## When To Use It

Use this plugin when an application can validate an OIDC provider's access token
but needs Traefik to handle the browser login, callback, session, and token
refresh.

TinyAuth's normal ForwardAuth flow returns an allow/deny result and identity
headers, not the original PocketID access token required by this flow. TinyAuth
can instead act as an OIDC server, but then the application validates a
TinyAuth-issued token rather than the PocketID token. For Langflow, the plugin
keeps PocketID as the issuer end to end.

## Request Flow

1. A browser requests a protected router.
2. The middleware redirects it to the OIDC provider.
3. The provider returns to `https://<service-host>/oidc/callback`.
4. The middleware exchanges the code for tokens and creates an encrypted session
    cookie.
5. Traefik adds `Authorization: Bearer <access-token>` to upstream requests.
6. The upstream application validates the token and resolves the user.

Unauthenticated browser requests are redirected. API-style requests receive
`401` unless another authentication path is configured.

## How It Is Configured

The plugin and its version are registered in `apps/traefik.yml`.
The middleware is defined under `configs/traefik3/rules/`. Its Go templates read
the selected container variables with `{{env "VARIABLE"}}`. Application routers
enable it with:

```yaml
traefik.http.routers.app-rtr.middlewares: "chain-no-auth@file,app-oidc@file"
```

The middleware handles `/oidc/callback` and `/logout` before forwarding normal
requests to the application.

## Langflow Example

Langflow uses `langflow-oidc@file`, configured in
`configs/traefik3/rules/middlewares-langflow-oidc.yml`. Traefik reads the
PocketID client ID, client secret, and session secret from its container
environment, then forwards the PocketID access token to Langflow. Langflow
validates the JWT and creates a local user on first login.

The registered PocketID callback is:

```text
https://langflow.<DOMAINNAME>/oidc/callback
```

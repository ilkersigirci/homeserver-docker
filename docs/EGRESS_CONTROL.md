# Egress Control

Controlled outbound HTTP(S) for normal Traefik-backed Docker apps.

## Model

- `app_internal`: internal backend network for routed apps; no direct egress.
- `egress`: outbound network used by Squid.
- `egress-proxy`: Squid on both networks, fixed at `192.168.95.10`; port `3128` stays internal.
- `egress-proxy-test`: curl client on `app_internal` that validates proxy env and direct-egress denial.

## App Rules

- Put proxied apps on `app_internal`; set `traefik.docker.network: "app_internal"`.
- Configure lowercase `http_proxy`, `https_proxy`, and `no_proxy`.
- Add allowed hosts to `configs/egress-proxy/allow-domains.txt`.
- Add explicit IP exceptions to `configs/egress-proxy/allow-ips.txt`; keep it empty otherwise.
- Keep one shared allowlist for one trust class; use Squid auth if apps need different allowlists.
- Squid enforces destination host, IP, and port; it cannot enforce HTTPS paths without TLS interception.

## Current App

- `apps/presenton.yml` routes outbound HTTP(S) through `egress-proxy`.
- `configs/egress-proxy/allow-domains.txt` contains the host from `$AIGATEWAY_BASE_URL`.

## Out Of Scope

- Host-network, macvlan, DNS, Syncthing, torrent/download, and monitoring-exporter egress.
- Browser CDN controls; use Traefik CSP middleware instead.
- Global `DOCKER-USER`/nftables deny policy until per-host exceptions are documented.

## Validation

Run from the target host after deployment:

```bash
COMPOSE_PROFILES=core,testing docker compose --env-file .env -f compose/gpu.yml up -d egress-proxy
COMPOSE_PROFILES=core,testing docker compose --env-file .env -f compose/gpu.yml run --rm egress-proxy-test
docker exec -u proxy egress-proxy tail -n 80 /var/log/squid/access.log
```

Expected:

- Allowed domain succeeds through Squid with `proxy_used=1`.
- Direct no-proxy domain check fails.
- Denied domain/IP checks fail through Squid and appear in `access.log`.
- Allowed IP checks skip unless `ALLOWED_HTTP_IP_URL` or `ALLOWED_HTTPS_IP_URL` is set.

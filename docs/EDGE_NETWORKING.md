# Edge Networking and Cloudflare

This document defines how internet-facing traffic is handled.

## Intent

- Keep public ingress limited to designated edge hosts.
- Minimize exposed ports.
- Hide origin hosts behind Cloudflare.

## Model

- `compose/remoteserver.yml` and `compose/remoteserver2.yml` are the public edge machines.
- Ingress services such as Traefik and CrowdSec run on those edge hosts.
- Other machines stay private in LAN and are accessed internally or via Tailscale.

## Cloudflare Rules

- Public services should use Cloudflare proxied DNS (Orange Cloud).
- Origin IPs should not be published directly.
- Cloudflare should be treated as the primary internet-facing shield in front of edge ingress.

## Port Exposure Rules

- Only necessary public ports should be published on edge hosts.
- Default public web entrypoints are `80` and `443`.
- Avoid ad hoc public port publishing from non-edge hosts.

## Traefik Integration Notes

- `apps/traefik.yml` is the edge ingress definition.
- Trusted forwarded headers are restricted via `CLOUDFLARE_IPS` and `LOCAL_IPS`.
- New public services should be routed through Traefik instead of direct container port exposure.
- Traefik writes `logs/traefik/access.log` for CrowdSec acquisition.

## Public Service Checklist

- Add routing labels in the target app compose fragment.
- Ensure DNS record is proxied in Cloudflare.
- Confirm service is reachable through Traefik hostname.
- Confirm no extra direct public port is exposed for that service.

# Architecture

High-level repository map: change locations, boundaries, and invariants only.

## Documentation Rules

- Keep docs concise: include only current commands, paths, invariants, and failure handling.
- Do not add narrative, history, duplicate examples, or one-off notes.
- Prefer linking to scripts/runbooks over copying long command blocks.
- Remove obsolete or unnecessary doc text when touching related docs.

## Bird's-Eye View

This repository is a multi-host Docker Compose setup for a personal homeserver platform.
The core idea is to keep one source of truth while separating:
- host-specific composition
- reusable service definitions

Deployment is host-driven:
- each host uses `compose/<host>.yml`
- the host file defines networks and includes active app fragments from `apps/`
- profiles decide which groups of services are active

## Codemap

- `compose/`
  - Entry points per host (`gpu.yml`, `nas.yml`, `remoteserver.yml`, etc.).
  - Defines shared networks and the selected app fragments for that machine.
- `apps/`
  - Active compose fragments referenced by one or more host files.
  - Holds service runtime options, labels, mounts, environment, profiles, and hardening settings.
- `apps-not-used/`
  - Parked compose fragments not currently referenced by host files.
  - Keep these here instead of deleting when a service is temporarily unused.
- `configs/`
  - Versioned service configuration mounted into containers.
- `scripts/`
  - Operational entrypoints (`docker-manage.sh`, permission prep, helpers).
- `scripts/database/`
  - Database backup and major-upgrade automation.
- `Dockerfiles/`
  - Custom images when upstream images are not enough.
- `appdata/`, `data/`, `logs/`, `backups/`
  - Persistent runtime state and operational artifacts.
- `docs/`
  - Concise runbooks and architecture/operational documentation.

## System Boundaries

- Edge boundary:
  - Public ingress is concentrated in the remote-server stack via reverse proxy/security services.
  - Detailed policy: [`docs/EDGE_NETWORKING.md`](./EDGE_NETWORKING.md).
- Private boundary:
  - Most workloads are inside private LAN/Tailscale networks.
- Docker API boundary:
  - Containers should use socket-proxy services rather than raw Docker socket access.
- Egress boundary:
  - Normal web app outbound HTTP(S) should use the controlled Squid proxy path.
  - Detailed policy: [`docs/EGRESS_CONTROL.md`](./EGRESS_CONTROL.md).
- Observability boundary:
  - Each host runs a local OTEL collector agent; telemetry is forwarded to centralized backends.
  - Detailed pattern: [`docs/OBSERVABILITY.md`](./OBSERVABILITY.md).

## Architectural Invariants

- Machine files compose services; app files define services.
- Service selection is done by host includes and profiles, not by duplicating service definitions per host.
- Shared Docker network definitions and host-specific app overlays belong in `compose/fragments/`.
- Include a base app fragment before any `compose/fragments/` overlay that augments the same service.
- Host compose `include` entries should reference `compose/` fragments or `apps/` service fragments. Parked service files belong in `apps-not-used/`.
- Bind mounts should use repository-based paths (`$REPO_PATH/...`) for predictable layout.
- Prefer hardened container defaults (`read_only`, `no-new-privileges`, dropped capabilities) unless a service documents an exception.
- Telemetry-capable services should send OTLP to local `otel-collector-agent`.
- Public exposure should go through managed ingress controls, not ad hoc port exposure.
- PostgreSQL major upgrades should follow [`docs/postgres_upgrade.md`](./postgres_upgrade.md) and `scripts/database/postgres-upgrade-major.sh`.

## Cross-Cutting Concerns

- Security:
  - Edge hardening, Docker socket segmentation, container least-privilege defaults.
- Operability:
  - `scripts/docker-manage.sh` is the standard operator entrypoint.
- Data safety:
  - Stateful paths are explicit and DB upgrades are runbook/script driven.
- Observability:
  - OTEL-first pattern with local agents and central dashboards/storage.

## Where To Change Things

- Add or remove a service for a host:
  - edit `compose/<host>.yml` include list.
- Change runtime behavior of one service:
  - edit `apps/<service>.yml` and matching `configs/<service>/`.
- Park or unpark a service fragment:
  - move `apps/<service>.yml` <-> `apps-not-used/<service>.yml`, then keep compose include lists aligned.
- Change ingress/routing/TLS behavior:
  - edit `apps/traefik.yml` and `configs/traefik3/`.
- Change deploy/operations workflow:
  - edit `scripts/docker-manage.sh` and related scripts.
- Change DB upgrade behavior:
  - edit `scripts/database/` and keep runbook docs aligned.

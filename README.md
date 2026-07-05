# Homeserver Docker

Compose-based homelab repository for running services across multiple machines (`gpu`, `nas`, `remoteserver`, and others).

![Services](./resources/services.png)

## How It Works

- Each machine has an entry compose file in `compose/`.
- Machine files define shared networks and `include` active service fragments from `apps/`.
- Service fragments not currently included by any host compose file are parked in `apps-not-used/`.
- Service fragments are grouped by compose profiles (`core`, `desktop_apps`, `maintenance`, `media`, `monitoring`, `programming`, `reading`, `others`).
- Runtime configs live in `configs/`; persistent state lives in `appdata/` and `data/`.

## Quick Start

Prerequisites:
- Docker
- Docker Compose 5.3.0 or later for `pre_start` init containers
- A configured `.env`
- `MY_HOSTNAME` set to a host with a matching file in `compose/`

```bash
# Start selected profiles for this host
bash scripts/docker-manage.sh up

# Stop the stack
bash scripts/docker-manage.sh down

# Pull images and recreate
bash scripts/docker-manage.sh pull
```

## Repository Layout

- `compose/` machine-level stack entrypoints
- `apps/` active service compose fragments referenced by host files
- `apps-not-used/` parked service compose fragments not referenced by host files
- `configs/` service configuration files
- `scripts/` operational scripts and maintenance tooling
- `Dockerfiles/` custom image definitions built by per-image custom image workflows
- `docs/` runbooks and architecture notes
- `appdata/`, `data/`, `logs/`, `backups/` runtime state and artifacts

## Documentation

Human/operator docs:
1. [Running The Stack](docs/RUNNING.md)
2. [Architecture](docs/ARCHITECTURE.md)
3. [Edge Networking and Cloudflare](docs/EDGE_NETWORKING.md)
4. [Observability and OpenTelemetry](docs/OBSERVABILITY.md)
5. [PostgreSQL Upgrade Runbook](docs/postgres_upgrade.md)
6. [Database Script Reference](scripts/database/README.md)

For coding agents, start at [AGENTS.md](AGENTS.md).

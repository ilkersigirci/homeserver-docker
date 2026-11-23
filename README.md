# Homeserver Docker

Compose-based homelab repository for running services across multiple machines (`titan`, `nas`, `remoteserver`, and others).

![Services](./resources/services.png)

## How It Works

- Each machine has an entry compose file in `compose/`.
- Machine files define shared networks and `include` active service fragments from `apps/`.
- Service fragments not currently included by any host compose file are parked in `apps-not-used/`.
- Service fragments are grouped by compose profiles (`core`, `desktop_apps`, `maintenance`, `media`, `monitoring`, `programming`, `reading`, `others`).
- Runtime configs live in `configs/`; persistent state lives in `appdata/` and `data/`.

## Deploy from the controller

From this checkout on `coding`, run `just ansible-deploy --limit titan`
to update the target checkout, sync its environment and apply Compose. See the
[deployment runbook](docs/RUNNING.md#deploy-from-coding) for setup and other targets.

## Quick Start

On the host you want to manage, export `MY_HOSTNAME` and start the stack from
its configured Docker checkout.

```bash
just local up
```

See the [local operations runbook](docs/RUNNING.md#local-operations-on-one-host) for prerequisites and actions.

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
5. [Database Script Reference](scripts/database/README.md)

For coding agents, start at [AGENTS.md](AGENTS.md).

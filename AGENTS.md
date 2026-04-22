# AGENTS

Primary entrypoint for coding agents working in this repository.
`README.md` is human/operator oriented; use this file for agent navigation.

Read in this order:

1. [Running The Stack](docs/RUNNING.md) - host selection, safe day-to-day commands, and compose usage.
2. [Architecture](docs/ARCHITECTURE.md) - repository codemap, boundaries, and invariants.
3. [Edge Networking and Cloudflare](docs/EDGE_NETWORKING.md) - public ingress policy and Cloudflare rules.
4. [Observability and OpenTelemetry](docs/OBSERVABILITY.md) - OTEL topology and service onboarding.
5. [PostgreSQL Upgrade Runbook](docs/postgres_upgrade.md) - deterministic major-upgrade procedure.
6. [Database Script Reference](scripts/database/README.md) - script-level examples and defaults.

Task routing:

- Stack lifecycle and compose commands: [docs/RUNNING.md](docs/RUNNING.md)
- Repository structure and change locations: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Public ingress / Cloudflare changes: [docs/EDGE_NETWORKING.md](docs/EDGE_NETWORKING.md)
- Telemetry/OTEL changes: [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md)
- PostgreSQL major upgrades: [docs/postgres_upgrade.md](docs/postgres_upgrade.md)

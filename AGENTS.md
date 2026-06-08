# AGENTS

Primary entrypoint for coding agents working in this repository.
`README.md` is human/operator oriented; use this file for agent navigation.

Read in this order:

1. [Running The Stack](docs/RUNNING.md) - host selection, safe day-to-day commands, and compose usage.
2. [Architecture](docs/ARCHITECTURE.md) - repository codemap, boundaries, and invariants.
3. [Edge Networking and Cloudflare](docs/EDGE_NETWORKING.md) - public ingress policy and Cloudflare rules.
4. [Egress Control](docs/EGRESS_CONTROL.md) - Docker outbound policy, proxy allowlists, and exceptions.
5. [Observability and OpenTelemetry](docs/OBSERVABILITY.md) - OTEL topology and service onboarding.
6. [PostgreSQL Upgrade Runbook](docs/postgres_upgrade.md) - deterministic major-upgrade procedure.
7. [Database Script Reference](scripts/database/README.md) - script-level examples and defaults.

Task routing:

- Stack lifecycle and compose commands: [docs/RUNNING.md](docs/RUNNING.md)
- Repository structure and change locations: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Public ingress / Cloudflare changes: [docs/EDGE_NETWORKING.md](docs/EDGE_NETWORKING.md)
- Docker egress policy changes: [docs/EGRESS_CONTROL.md](docs/EGRESS_CONTROL.md)
- Telemetry/OTEL changes: [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md)
- PostgreSQL major upgrades: [docs/postgres_upgrade.md](docs/postgres_upgrade.md)

Validation:

- After code, config, or documentation edits, run uvx prek on the changed files
  before handing the work back:
  `uvx prek run --files <changed-files>`
- If a hook cannot be run, mention the blocker and any narrower validation that was
  completed.

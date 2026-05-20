---
name: create-docker-service
description: Create new Docker Compose app fragments for this repository by starting from `.vscode/snippets/dockercompose.json` and wiring them into the active host file. Use when adding a new service under `apps/`, updating `compose/$MY_HOSTNAME.yml` includes, deciding whether Traefik labels are needed for external access, and starting the stack with `docs/RUNNING.md`.
---

# Create Docker Service

## Overview

Create a new service fragment in `apps/` using the `dockerservice` snippet as a baseline, add a real container healthcheck, then wire it into `compose/$MY_HOSTNAME.yml` for the target machine.

## Required Context

- Read `docs/ARCHITECTURE.md` for compose/app boundaries.
- Read `docs/RUNNING.md` for startup commands.
- Read `.vscode/snippets/dockercompose.json` and use the `Docker Service Template` snippet body as the base.
- Assume work is executed from the repository root (`$HOME/docker`).

## Workflow

### 1) Resolve host target

- Ensure `MY_HOSTNAME` is set.
- Set `host_file="compose/$MY_HOSTNAME.yml"` and verify it exists.
- Stop and ask for clarification only if the host file is missing.

### 2) Create app fragment in `apps/`

- Create `apps/<service>.yml`.
- Start with:

```yaml
services:
  <service>:
    ...
```

- Copy the snippet service block and adapt it:
  - Always pin the image to a digest (`image: repo/name:tag@sha256:...`).
  - Resolve digests with `scripts/get-image-sha.sh --pinned-only <image:tag>` when needed.
  - Keep profile membership aligned with existing groups in the host compose file.
  - Keep hardening defaults unless service docs require exceptions (`read_only`, `tmpfs`, `no-new-privileges`, dropped capabilities).
  - Keep repository-relative mounts using `$REPO_PATH/...`.
  - Replace the snippet placeholder `healthcheck.disable: true` with a real healthcheck whenever possible.
  - Prefer HTTP probes against a local endpoint (for example `/health`, `/healthz`, `/api/health`, `/api/status`) on `127.0.0.1:<service-port>`.
  - Use the repository default timing unless service docs require otherwise:

```yaml
healthcheck:
  test: ["CMD", "curl", "-fsS", "--max-time", "3", "http://127.0.0.1:<port>/<health-path>"]
  interval: 5m
  timeout: 5s
  retries: 3
  start_period: 30s
```

  - If `curl` is unavailable in the image, use another reliable in-container command (for example `wget --spider` or a service-native CLI check).
  - Keep `disable: true` only when no reliable probe exists, and document the reason inline with a comment.

### 3) Decide exposure model before labels

- If external HTTP/HTTPS access is required:
  - Attach service to `t3_proxy`.
  - Configure `expose` and Traefik labels for the app port.
  - Keep direct `ports` only when explicitly required.
- If service is internal-only:
  - Do not add Traefik labels.
  - Remove only external URL-oriented labels and values (for example, public hostnames and public `https://...$DOMAINNAME` links).
  - Keep non-external metadata labels when still useful for internal dashboards.
  - Prefer private networks; publish host ports only if absolutely needed.
  - Example: PostgreSQL services should not have Traefik labels.

### 4) Add host include

- Edit `compose/$MY_HOSTNAME.yml`.
- Add:

```yaml
- ../apps/<service>.yml
```

- Place it near related services and keep surrounding comments/order style consistent.

### 5) Start and validate

- Preferred:

```bash
bash scripts/docker-manage.sh up
```

- Compose-compatible alternative from `docs/RUNNING.md`:

```bash
PROFILES="core,desktop_apps,maintenance,media,monitoring,programming,reading,others"
COMPOSE_FILE="$HOME/docker/compose/$MY_HOSTNAME.yml"
ENV_FILE="$HOME/docker/.env"

COMPOSE_PROFILES="$PROFILES" docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" up -d
```

- Validate compose syntax:

```bash
docker compose --env-file .env --file "compose/$MY_HOSTNAME.yml" config
```

- Confirm runtime behavior matches intent:
  - External service resolves through Traefik route.
  - Internal-only service is reachable only through intended internal network/ports.
  - Healthcheck transitions to `healthy` in expected startup time.

### 6) Add runtime placeholders only after permission validation

- First validate the service is healthy with `user: "$PUID:$PGID"`.
- If the service is healthy with `user: "$PUID:$PGID"`, add only the runtime directories that must exist in a fresh clone:

```bash
mkdir -p data/<service> appdata/<service>
touch data/<service>/.gitkeep appdata/<service>/.gitkeep
git add -f data/<service>/.gitkeep appdata/<service>/.gitkeep
```

- If the service is not healthy with `user: "$PUID:$PGID"`:
  - Add `custom-user` to the service profiles.
  - Do not add any `.gitkeep` files for that service.

## Routing Rules

- Add Traefik labels only for externally routed services.
- Keep internal databases and private backends off Traefik.
- Keep edge-host placement as an operator decision; apply `docs/EDGE_NETWORKING.md` when choosing to expose a service publicly.
- Follow `docs/EDGE_NETWORKING.md` when exposing services to the internet.

## Done Criteria

- Service definition exists in `apps/<service>.yml`.
- Host include exists in `compose/$MY_HOSTNAME.yml`.
- Label strategy matches access model:
  - External service: Traefik labels present and valid.
  - Internal-only service: no Traefik labels.
- Service has an active healthcheck (not `disable: true`) unless an inline comment explains why a probe is not feasible.
- Service can be started with the workflow in `docs/RUNNING.md`.
- Runtime `.gitkeep` files were force-added only if the service is healthy with `user: "$PUID:$PGID"`; otherwise `custom-user` profile is present and no runtime placeholders were added.

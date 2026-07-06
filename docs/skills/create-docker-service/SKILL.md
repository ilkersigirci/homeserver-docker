---
name: create-docker-service
description: Create and wire Docker Compose service fragments from the repository snippet, including host include, access model, healthcheck, and validation.
---

# Create Docker Service

## Required Context

- Read `docs/ARCHITECTURE.md` for compose/app boundaries.
- Read `docs/RUNNING.md` for startup commands.
- Read `.vscode/snippets/dockercompose.json` and use the `Docker Service Template` snippet body as the base.
- Assume work is executed from the repository root (`$HOME/docker`).

## Workflow

### 1) Resolve Target Host

- Ensure `MY_HOSTNAME` is set.
- Set `host_file="compose/$MY_HOSTNAME.yml"` and verify it exists.
- Stop and ask for clarification only if the host file is missing.

### 2) Create App Fragment

- Create `apps/<service>.yml` from the `Docker Service Template` snippet.
- Keep the service under:

```yaml
services:
  <service>:
    ...
```

- Pin the image to a digest (`image: repo/name:tag@sha256:...`).
- Resolve digests with `scripts/get-image-sha.sh --pinned-only <image:tag>` when needed.
- Align profiles with existing host groups.
- Keep hardening defaults unless service docs require an exception.
- Use `$REPO_PATH/...` mounts.
- Replace `healthcheck.disable: true` with a real probe whenever possible.

```yaml
healthcheck:
  test: ["CMD", "curl", "-fsS", "--max-time", "3", "http://127.0.0.1:<port>/<health-path>"]
  interval: 5m
  timeout: 5s
  retries: 3
  start_period: 30s
```

- If `curl` is unavailable, use another reliable in-container check.
- Keep `disable: true` only when no reliable probe exists; add a short inline reason.

### 3) Choose Access Model

- External HTTP/HTTPS: attach to `t3_proxy`, add `expose`, and add Traefik labels.
- Internal-only: no Traefik labels; prefer private networks and avoid host ports.
- Keep direct `ports` only when explicitly required.

### 4) Add Host Include

Add the app fragment near related services in `compose/$MY_HOSTNAME.yml`:

```yaml
- ../apps/<service>.yml
```

### 5) Validate

Start with the repository workflow:

```bash
bash scripts/docker-manage.sh up
```

- Validate compose syntax with the command pattern in `docs/RUNNING.md`.
- Confirm Traefik/internal reachability matches the access model.
- Confirm healthcheck reaches `healthy` in expected startup time.

### 6) Initialize Writable Bind Mounts

For a non-root service whose writable bind-mount ownership is not guaranteed,
use a root `pre_start` hook to set ownership before the service starts:

```yaml
pre_start:
  - image: busybox:1.37.0@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028
    user: root
    command: ["chown", "-R", "<uid>:<gid>", "<writable-container-path>"]
```

- Resolve named image users to numeric UID/GID values for the BusyBox hook.
- Target only paths the service must write.
- For repository bind mounts used by `PUID:PGID`, prefer a tracked `.gitkeep` so the clone creates the source with the correct ownership.
- Do not add a hook when a tracked `.gitkeep` creates the bind source with ownership matching `PUID:PGID`.
- Never recursively chown read-only mounts, shared external media, or repository roots.
- For a shared external mount, chown only the mount root when the service must create children.
- Exclude nested read-only mounts from recursive traversal.
- Do not add runtime `.gitkeep` files for bind paths initialized by `pre_start`.
- If the service cannot run with `user: "$PUID:$PGID"`, document the required runtime identity or root-entrypoint behavior.

## Done Criteria

- Service definition exists in `apps/<service>.yml`.
- Host include exists in `compose/$MY_HOSTNAME.yml`.
- Label strategy matches access model:
  - External service: Traefik labels present and valid.
  - Internal-only service: no Traefik labels.
- Service has an active healthcheck (not `disable: true`) unless an inline comment explains why a probe is not feasible.
- Service can be started with the workflow in `docs/RUNNING.md`.
- Writable non-root bind mounts with unmanaged ownership have narrowly scoped `pre_start` hooks.
- Services that require a different identity or a root entrypoint document why.

# Homeserver Docker

![Services](./resources/services.png)

## Architecture

I have a dedicated compose file for each machine in `compose/` that includes the relevant services for that machine. For example, `compose/gpu.yml` includes all services that run on the gpu machine, while `compose/remoteserver.yml` includes services that run on the remote machine that has a **Public IP**.

- `compose/remoteserver.yml` - Services that run on the remote server with public IP (e.g. Traefik, Crowdsec) - Needs maximum security hardening
  - It is behind Cloudflare and only exposes necessary ports (e.g. 80, 443) to the public. All other services are either internal or accessed via Tailscale.
  - If I want to make a service public, I am always using Cloudflare Orange Cloud to hide the real IP and add an extra layer of security.
  - I don't expose my Public IP in any way.
- Other machines are in my home network inside the same LAN. All private IP. Uses tailscale for secure connectivity between machines and to access the remote server from outside.

The `apps` folder contains a collection of Docker Compose files for running various services on a home server machines.


### OpenTelemetry Pattern

- Run `apps/grafana-lgtm.yml` only on the `gpu` machine.
- Run `apps/otel-collector-agent.yml` on every machine, which receives local OTLP and exports host metrics (`cpu`, `memory`, `disk`, `filesystem`, `network`)
- Services that export telemetry (e.g. `apps/traefik.yml`, `apps/homeserver-api.yml`) are configured to point to the local OTEL agent on each machine.

To point all app telemetry to the local agent on each machine:
```env
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector-agent:4317
OTEL_EXPORTER_OTLP_INSECURE=true
```

## Useful Commands

```bash
# Start selected components
bash scripts/docker-manage.sh up

# Stop selected components
bash scripts/docker-manage.sh down

# Pull latest images
bash scripts/docker-manage.sh pull
```

Currently used aliases (already defined in the SHELL profile):
```bash
alias dup="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml up"
alias ddown="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml down --volumes --remove-orphans"
alias drm="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml rm -svf"
alias dpull="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml pull"
alias dbuild="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml build"
```

### Volume Bind Permission Script

```bash
# Permissions bootstrap
bash scripts/docker-manage.sh prep-perms
```

For custom compose targets, you can run the permission bootstrap directly:
```bash
# Check only
bash scripts/prepare-bind-permissions.sh \
  --compose-file compose/$MY_HOSTNAME.yml \
  --env-file .env \
  --check-only

# Preview
sudo bash scripts/prepare-bind-permissions.sh \
  --compose-file compose/$MY_HOSTNAME.yml \
  --env-file .env \
  --dry-run

# Apply
sudo bash scripts/prepare-bind-permissions.sh \
  --compose-file compose/$MY_HOSTNAME.yml \
  --env-file .env
```

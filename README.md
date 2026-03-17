# Homeserver Docker

![Services](./resources/services.png)

The `apps` folder contains a collection of Docker Compose files for running various services on a home server machines.
The `compose` folder defines which services to run on which machines, allowing for easy management of multiple hosts with different configurations.

Essential commands

```bash
# Start selected components
bash scripts/docker-manage.sh up

# Stop selected components
bash scripts/docker-manage.sh down

# Pull latest images
bash scripts/docker-manage.sh pull
```

Useful aliases

```bash
alias dup="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml up"
alias ddown="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml down --volumes --remove-orphans"
alias drm="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml rm -svf"
alias dpull="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml pull"
alias dbuild="docker compose --env-file $HOME/docker/.env --file $HOME/docker/compose/$MY_HOSTNAME.yml build"
```

Start containers at machine start-up

```bash
nano $HOME/.config/autostart/start.sh.desktop

[Desktop Entry]
Type=Application
Exec=$HOME/docker/scripts/docker-manage.sh up
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name[en_US]=Start Docker Apps
Name=Start Docker Apps
Comment[en_US]=
Comment=
```

Docker Daemon Json Example
```json title="/etc/docker/daemon.json"
{
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

## OpenTelemetry Pattern (Multi-Machine)

- Run `apps/traefik.yml` and `apps/otel-collector-agent.yml` on every machine.
  - `traefik.yml` exports edge telemetry over OTLP
  - `otel-collector-agent.yml` receives local OTLP and exports host metrics (`cpu`, `memory`, `disk`, `filesystem`, `network`)
- Run `apps/grafana-lgtm.yml` only on the central machine.
- Point all app telemetry to the local agent on each machine:

```env
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector-agent:4317
OTEL_EXPORTER_OTLP_INSECURE=true
```
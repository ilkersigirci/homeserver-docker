# Running The Stack

This is the operator quick reference for humans and coding agents.

## Prerequisites

- Docker + Docker Compose installed
- Repo `.env` exists at `$HOME/docker/.env`
- `MY_HOSTNAME` is set and matches a file in `compose/` (example: `gpu`, `remoteserver`)

## Preferred Commands (Repository Script)

```bash
# Start selected profiles
bash scripts/docker-manage.sh up

# Stop stack
bash scripts/docker-manage.sh down

# Pull and recreate
bash scripts/docker-manage.sh pull

# Restart
bash scripts/docker-manage.sh restart

# Prepare bind-mount permissions for services in profile 'custom-user'
bash scripts/docker-manage.sh prep-perms
```

## Direct Docker Compose Commands

Use these when you need to bypass `scripts/docker-manage.sh` and stay behavior-compatible.

```bash
PROFILES="core,desktop_apps,maintenance,media,monitoring,programming,reading,others"
COMPOSE_FILE="$HOME/docker/compose/$MY_HOSTNAME.yml"
ENV_FILE="$HOME/docker/.env"

COMPOSE_PROFILES="$PROFILES" docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" up -d
COMPOSE_PROFILES="$PROFILES" docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" down --remove-orphans
COMPOSE_PROFILES="$PROFILES" docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" pull
COMPOSE_PROFILES="$PROFILES" docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" up -d
```

## Destructive Operations

- `down --volumes` and `rm -svf` are intentionally excluded from normal workflows.
- Use them only for explicit cleanup tasks, after confirming data-loss impact on bound volumes and named volumes.

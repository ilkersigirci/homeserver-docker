# PostgreSQL Upgrade Runbook (Deterministic)

This runbook is for coding agents working in this repository.

It standardizes:
- major Postgres upgrades (example: `16 -> 18.3`)
- migration to Postgres 18+ storage layout
- non-root compose style used in this repo
- recovery from restart loops

Run commands from repo root: `/home/ilker/docker`.

See also: [Database Script Reference](../scripts/database/README.md)

## 1) Required Inputs

Set these first:

```bash
SERVICE="forgejo-db"                  # Compose DB service name
WRITERS="forgejo"                     # Comma-separated writer services to stop/restart
PROFILES="programming,forgejo"        # COMPOSE_PROFILES for this stack slice
APP_FILE="apps/forgejo.yml"           # App compose fragment that defines SERVICE
DATA_DIR="$REPO_PATH/data/forgejo/db" # Host bind dir for DB
COMPOSE_FILE="compose/$MY_HOSTNAME.yml"
ENV_FILE=".env"
NEW_IMAGE="postgres:18.3@sha256:059fa0289cc5a184034e05a1f4f6d6fd79f69dc718b8b04ab60b6b469eed411e"
```

Resolve UID/GID from `.env`:

```bash
PUID="$(awk -F= '/^PUID=/{print $2}' "$ENV_FILE")"
PGID="$(awk -F= '/^PGID=/{print $2}' "$ENV_FILE")"
```

Safety preflight (required before any root-level `docker run` file operations):

```bash
DATA_DIR="$(realpath -m "$DATA_DIR")"
REPO_DATA_ROOT="$(realpath -m "$REPO_PATH/data")"

[[ "$DATA_DIR" == "$REPO_DATA_ROOT/"* ]] || {
  echo "Refusing DATA_DIR outside repo data root: $DATA_DIR"
  exit 1
}
[[ "$DATA_DIR" != "$REPO_DATA_ROOT" ]] || {
  echo "Refusing DATA_DIR at repo data root: $DATA_DIR"
  exit 1
}
[[ "$DATA_DIR" != "/" ]] || {
  echo "Refusing DATA_DIR=/"
  exit 1
}
[ -d "$DATA_DIR" ] || {
  echo "Missing DATA_DIR: $DATA_DIR"
  exit 1
}

RESOLVED_DB_BIND="$(
  COMPOSE_PROFILES="$PROFILES" docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" config --format json \
  | jq -r --arg svc "$SERVICE" '
      .services[$svc].volumes[]?
      | select(.type=="bind" and .target=="/var/lib/postgresql")
      | .source
    ' | head -n1
)"
[[ -n "$RESOLVED_DB_BIND" && "$RESOLVED_DB_BIND" != "null" ]] || {
  echo "Could not resolve /var/lib/postgresql bind source for service: $SERVICE"
  exit 1
}
RESOLVED_DB_BIND="$(realpath -m "$RESOLVED_DB_BIND")"
[[ "$RESOLVED_DB_BIND" == "$DATA_DIR" ]] || {
  echo "DATA_DIR mismatch. Compose resolved: $RESOLVED_DB_BIND, provided: $DATA_DIR"
  exit 1
}
```

## 2) Canonical Compose Pattern for Postgres 18.3

For DB services on `postgres:18.3`, use this pattern:

- `user: $PUID:$PGID`
- `read_only: true`
- `tmpfs`:
  - `/tmp:uid=$PUID,gid=$PGID,mode=1777`
  - `/var/run/postgresql:uid=$PUID,gid=$PGID,mode=775`
- bind mount target must be exactly: `/var/lib/postgresql`
- `environment` should include `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- do not set `PGDATA` for these services
- remove `custom-user` profile from DB service if present

## 3) Major Upgrade Procedure (Dump/Restore)

Critical ordering:
- Run this workflow **before** changing the DB service image in app compose files to the new major version.
- Keep DB service runnable on the old major so backup can be taken from a healthy source container.
- After script success, commit/update compose image to the new major.

Use repository script.
For option details and additional examples, see [Database Script Reference](../scripts/database/README.md).

Run:

```bash
scripts/database/postgres-upgrade-major.sh \
  --service "$SERVICE" \
  --new-image "$NEW_IMAGE" \
  --compose-file "$COMPOSE_FILE" \
  --env-file "$ENV_FILE" \
  --profiles "$PROFILES" \
  --stop-services "$WRITERS" \
  --db-user postgres \
  --yes
```

Script behavior:
1. creates logical backup in `backups/postgres/`
2. stops writer services + DB
3. rotates old data dir to `${DATA_DIR}_pg_old_<timestamp>`
4. starts DB on target image
5. restores backup
6. restarts writers

Restore behavior:
- script first restores in strict mode (`ON_ERROR_STOP=1`)
- if strict mode hits expected bootstrap conflicts (`role/database postgres already exists`), it retries in permissive mode
- any other strict-mode failure aborts the upgrade

## 4) Postgres 18 Layout Migration (Critical)

If logs contain this error:

- `Error: in 18+ ... Counter to that, there appears to be PostgreSQL data in: /var/lib/postgresql`
- or same message for `/var/lib/postgresql/data`

then migrate data to required 18+ layout: `<bind>/18/docker`.

Stop DB first:

```bash
COMPOSE_PROFILES="$PROFILES" docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" stop "$SERVICE"
```

Migrate layout (works for both legacy root and `data/` layouts):

```bash
# DATA_DIR is expected to be preflight-validated above.
[ -d "$DATA_DIR" ] || { echo "Missing DATA_DIR: $DATA_DIR"; exit 1; }

docker run --rm --user 0:0 -v "$DATA_DIR":/mnt "$NEW_IMAGE" bash -lc '
set -euo pipefail
mkdir -p /mnt/18

# Case A: cluster at /mnt (legacy root layout)
if [[ -f /mnt/PG_VERSION ]] && [[ ! -f /mnt/18/docker/PG_VERSION ]]; then
  mkdir -p /mnt/18/docker
  shopt -s dotglob nullglob
  for p in /mnt/*; do
    bn="$(basename "$p")"
    if [[ "$bn" == "18" || "$bn" == ".gitkeep" ]]; then
      continue
    fi
    mv "$p" /mnt/18/docker/
  done
fi

# Case B: cluster at /mnt/data (legacy PGDATA=/pgdata/data style after remap)
if [[ -f /mnt/data/PG_VERSION ]] && [[ ! -f /mnt/18/docker/PG_VERSION ]]; then
  mv /mnt/data /mnt/18/docker
fi

rm -f /mnt/18/docker/postmaster.pid /mnt/18/docker/postmaster.opts
chown -R '"$PUID:$PGID"' /mnt/18
touch /mnt/.gitkeep
'
```

Start services again:

```bash
START_SERVICES="$SERVICE $(echo "$WRITERS" | tr "," " ")"
COMPOSE_PROFILES="$PROFILES" docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d $START_SERVICES
```

## 5) Permission Repair (If Needed)

If logs show `Permission denied` during init (`initdb`/`chmod` on data dir), fix bind ownership:

```bash
# DATA_DIR is expected to be preflight-validated above.
docker run --rm --user 0:0 -v "$DATA_DIR":/mnt "$NEW_IMAGE" bash -lc '
chown -R '"$PUID:$PGID"' /mnt
chmod 700 /mnt
touch /mnt/.gitkeep
'
```

## 6) Validation Checklist

Run all of these:

```bash
WRITER_REGEX="$(echo "$WRITERS" | sed "s/,/|/g")"
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}' | rg "$SERVICE|$WRITER_REGEX"
docker logs --tail 120 "$SERVICE" 2>&1
```

Expected:
- DB container is `Up` and `(healthy)` if healthcheck exists
- logs include `database system is ready to accept connections`
- writer logs show successful DB init/connection

Home Assistant recorder check (recommended when upgrading `home-assistant-db`):

```bash
docker exec "$SERVICE" psql -U postgres -d postgres -P pager=off -c "
SELECT to_timestamp(min(last_updated_ts)) AS min_state_ts,
       to_timestamp(max(last_updated_ts)) AS max_state_ts,
       count(*) AS states_total
FROM states;
SELECT to_timestamp(min(start_ts)) AS min_short_ts,
       to_timestamp(max(start_ts)) AS max_short_ts,
       count(*) AS statistics_short_term_total
FROM statistics_short_term;
"
```

Ensure date ranges and row counts are consistent with pre-upgrade expectations.

Also validate compose syntax after edits:

```bash
COMPOSE_PROFILES="$PROFILES" \
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" config >/tmp/compose-config.yaml
```

## 7) Rollback

Do not delete rotated old dir (`*_pg_old_*`) until validation is complete.

Rollback steps:
1. stop writer + DB services
2. restore previous DB image in app file
3. move current data dir aside
4. move `*_pg_old_*` back to original data dir
5. start DB + writers

If needed, restore from SQL backup generated in `backups/postgres/`.

## 8) Agent Guardrails

- Never perform a major image bump without logical backup.
- Never use `postgres:18.3` with bind target `/var/lib/postgresql/data` in this repo.
- For Postgres 18+, always use mount target `/var/lib/postgresql` and let container manage `18/docker`.
- Keep `.gitkeep` inside each DB bind directory so Git tracks empty dirs.
- Always run the DATA_DIR preflight checks before any root-level `docker run` that mutates files.

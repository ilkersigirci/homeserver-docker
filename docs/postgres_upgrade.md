# PostgreSQL Major Upgrade

Use `scripts/database/postgres-upgrade-major.sh` for major upgrades.
Run from the repo root.

See also: [Database Script Reference](../scripts/database/README.md)

## Required Inputs

Set these before running the script:

```bash
SERVICE="forgejo-db"                  # Compose DB service name
WRITERS="forgejo"                     # Comma-separated writer services to stop/restart
PROFILES="programming,forgejo"        # COMPOSE_PROFILES for this stack slice
COMPOSE_FILE="compose/$MY_HOSTNAME.yml"
ENV_FILE=".env"
NEW_IMAGE="postgres:18.3@sha256:059fa0289cc5a184034e05a1f4f6d6fd79f69dc718b8b04ab60b6b469eed411e"
```

## Compose Rules For Postgres 18+

- pin the image to an immutable digest
- `user: "$PUID:$PGID"`
- `read_only: true`
- `tmpfs` includes `/tmp:uid=$PUID,gid=$PGID,mode=1777` and `/var/run/postgresql:uid=$PUID,gid=$PGID,mode=775`
- bind mount target is `/var/lib/postgresql`, not `/var/lib/postgresql/data`
- set `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`
- do not set `PGDATA`

## Upgrade

Run this before changing the source compose image so the old DB can still be backed up:

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

After success, update the app compose image to `NEW_IMAGE`.
Then validate compose syntax:

```bash
COMPOSE_PROFILES="$PROFILES" docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" config >/tmp/compose-config.yaml
```

## Manual Repair

- For Postgres 18 layout errors, stop the DB and move the cluster under `<bind>/18/docker`.
- For init permission errors, fix ownership on the DB bind dir to `$PUID:$PGID`.
- Before root-level `docker run` file mutations, confirm the target path is the exact DB bind source from compose; never operate on `/`, `$REPO_PATH/data`, or paths outside `$REPO_PATH/data`.

## Validation

Run all of these:

```bash
WRITER_REGEX="$(echo "$WRITERS" | sed "s/,/|/g")"
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}' | rg "$SERVICE|$WRITER_REGEX"
docker logs --tail 120 "$SERVICE" 2>&1
```

Expected:

- DB container is `Up` and `(healthy)` if healthcheck exists
- logs include `database system is ready to accept connections`
- writers reconnect successfully

## Rollback

Do not delete rotated old dir (`*_pg_old_*`) until validation is complete.

Rollback steps:

1. stop writer + DB services
2. restore previous DB image in app file
3. move current data dir aside
4. move `*_pg_old_*` back to original data dir
5. start DB + writers

If needed, restore from SQL backup generated in `backups/postgres/`.

## Guardrails

- Never perform a major image bump without logical backup.
- Never use `postgres:18.3` with bind target `/var/lib/postgresql/data` in this repo.
- For Postgres 18+, always use mount target `/var/lib/postgresql` and let container manage `18/docker`.
- Keep `.gitkeep` inside each DB bind directory so Git tracks empty dirs.

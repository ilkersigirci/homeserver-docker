#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  postgres-upgrade-major.sh --service <compose_service> [options]

Required:
  --service NAME               Docker Compose service name (e.g. hatchet-db)

Options:
  --new-image IMAGE            New Postgres image (e.g. postgres:18.3)
                               If omitted, script uses image from compose file.
  --compose-file PATH          Compose file path
                               Default: compose/$MY_HOSTNAME.yml
  --env-file PATH              Env file passed to docker compose
                               Default: $HOME/docker/.env
  --profiles CSV               COMPOSE_PROFILES value (comma-separated)
  --stop-services CSV          Comma-separated writer services to stop before DB stop
                               Example: hatchet,langfuse-web
  --db-user USER               Postgres user for restore and readiness checks
                               Default: POSTGRES_USER from container, else postgres
  --data-dir PATH              Host Postgres data directory. Auto-detected for bind mounts.
  --backup-dir PATH            Backup directory for logical dump
                               Default: $REPO_PATH/backups/postgres (or repo-root/backups/postgres)
  --backup-file PATH           Reuse an existing backup file (.sql or .sql.gz)
  --skip-backup                Skip creating a new backup (requires --backup-file)
  --yes                        Non-interactive mode
  -h, --help                   Show this help

Flow:
  1) Backup (pg_dumpall)
  2) Stop writer services + DB
  3) Move old data dir to data-dir_pg_old_<timestamp>
  4) Start DB with new image
  5) Restore backup
  6) Restart writer services

Examples:
  scripts/database/postgres-upgrade-major.sh \
    --service hatchet-db \
    --new-image postgres:18.3 \
    --stop-services hatchet \
    --profiles programming,hatchet

  scripts/database/postgres-upgrade-major.sh \
    --service forgejo-db \
    --backup-file /path/to/forgejo.sql.gz \
    --skip-backup \
    --yes
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

err() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

compose() {
  if [[ -n "$profiles" ]]; then
    COMPOSE_PROFILES="$profiles" docker compose -f "$compose_file" --env-file "$env_file" "$@"
  else
    docker compose -f "$compose_file" --env-file "$env_file" "$@"
  fi
}

compose_with_override() {
  local override_file="$1"
  shift
  if [[ -n "$profiles" ]]; then
    COMPOSE_PROFILES="$profiles" docker compose -f "$compose_file" -f "$override_file" --env-file "$env_file" "$@"
  else
    docker compose -f "$compose_file" -f "$override_file" --env-file "$env_file" "$@"
  fi
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backup_script="$script_dir/postgres-backup.sh"

service=""
new_image=""
compose_file=""
env_file="$HOME/docker/.env"
profiles=""
stop_services_csv=""
db_user=""
data_dir=""
skip_backup=false
assume_yes=false
backup_file=""
default_backup_root="${REPO_PATH:-$repo_root}/backups/postgres"
backup_dir="$default_backup_root"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      service="${2:-}"
      shift 2
      ;;
    --new-image)
      new_image="${2:-}"
      shift 2
      ;;
    --compose-file)
      compose_file="${2:-}"
      shift 2
      ;;
    --env-file)
      env_file="${2:-}"
      shift 2
      ;;
    --profiles)
      profiles="${2:-}"
      shift 2
      ;;
    --stop-services)
      stop_services_csv="${2:-}"
      shift 2
      ;;
    --db-user)
      db_user="${2:-}"
      shift 2
      ;;
    --data-dir)
      data_dir="${2:-}"
      shift 2
      ;;
    --backup-dir)
      backup_dir="${2:-}"
      shift 2
      ;;
    --backup-file)
      backup_file="${2:-}"
      shift 2
      ;;
    --skip-backup)
      skip_backup=true
      shift
      ;;
    --yes)
      assume_yes=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      err "Unknown argument: $1"
      ;;
  esac
done

[[ -n "$service" ]] || err "--service is required"
[[ -x "$backup_script" ]] || err "Backup script missing or not executable: $backup_script"

if [[ -z "$compose_file" ]]; then
  if [[ -n "${MY_HOSTNAME:-}" ]] && [[ -f "$repo_root/compose/$MY_HOSTNAME.yml" ]]; then
    compose_file="$repo_root/compose/$MY_HOSTNAME.yml"
  else
    err "Could not infer compose file. Pass --compose-file."
  fi
fi

[[ -f "$compose_file" ]] || err "Compose file not found: $compose_file"
[[ -f "$env_file" ]] || err "Env file not found: $env_file"

container_id="$(compose ps -q "$service" 2>/dev/null || true)"
if [[ -z "$container_id" ]]; then
  log "Service '$service' is not running. Starting it for inspection and backup."
  compose up -d "$service"
  container_id="$(compose ps -q "$service" 2>/dev/null || true)"
fi
[[ -n "$container_id" ]] || err "Could not resolve running container for service '$service'"

container_name="$(docker inspect --format '{{.Name}}' "$container_id" | sed 's#^/##')"
old_image="$(docker inspect --format '{{.Config.Image}}' "$container_id")"

if [[ -z "$db_user" ]]; then
  db_user="$(
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_id" \
      | sed -n 's/^POSTGRES_USER=//p' \
      | head -n1
  )"
fi
db_user="${db_user:-postgres}"

pgdata="$(
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_id" \
    | sed -n 's/^PGDATA=//p' \
    | head -n1
)"
pgdata="${pgdata:-/var/lib/postgresql/data}"

mount_info="$(
  docker inspect --format '{{range .Mounts}}{{println .Type "|" .Source "|" .Destination}}{{end}}' "$container_id"
)"

detected_mount_type=""
detected_data_dir=""
detected_mount_dest=""
best_len=0
while IFS='|' read -r mount_type mount_src mount_dest; do
  mount_type="$(trim "$mount_type")"
  mount_src="$(trim "$mount_src")"
  mount_dest="$(trim "$mount_dest")"
  [[ -n "$mount_src" ]] || continue
  if [[ "$pgdata" == "$mount_dest" || "$pgdata" == "$mount_dest/"* || "$mount_dest" == "$pgdata" || "$mount_dest" == "$pgdata/"* ]]; then
    if (( ${#mount_dest} > best_len )); then
      best_len=${#mount_dest}
      detected_mount_type="$mount_type"
      detected_data_dir="$mount_src"
      detected_mount_dest="$mount_dest"
    fi
  fi
done <<< "$mount_info"

if [[ -z "$data_dir" ]]; then
  data_dir="$detected_data_dir"
fi
[[ -n "$data_dir" ]] || err "Could not auto-detect data dir. Pass --data-dir."
[[ "$data_dir" = /* ]] || err "--data-dir must be an absolute host path"
[[ "$data_dir" != "/" ]] || err "Refusing to operate on '/'"

if [[ "$skip_backup" == true ]] && [[ -z "$backup_file" ]]; then
  err "--skip-backup requires --backup-file"
fi

if [[ -n "$backup_file" ]] && [[ ! -f "$backup_file" ]]; then
  err "Backup file not found: $backup_file"
fi

if [[ "$skip_backup" == false ]] && [[ -z "$backup_file" ]]; then
  mkdir -p "$backup_dir"
  backup_cmd=(
    "$backup_script"
    --service "$service"
    --compose-file "$compose_file"
    --env-file "$env_file"
    --db-user "$db_user"
    --backup-dir "$backup_dir"
    --print-path-only
  )
  if [[ -n "$profiles" ]]; then
    backup_cmd+=(--profiles "$profiles")
  fi
  backup_file="$("${backup_cmd[@]}")"
fi

[[ -f "$backup_file" ]] || err "Backup file not found after backup step: $backup_file"

timestamp="$(date '+%Y%m%d_%H%M%S')"
old_data_dir_backup="${data_dir}_pg_old_${timestamp}"
target_image="${new_image:-$old_image}"

if [[ "$assume_yes" == false ]]; then
  cat <<EOF
About to run Postgres major-upgrade workflow:
  Service        : $service
  Current image  : $old_image
  Target image   : $target_image
  Container      : $container_name
  PGDATA         : $pgdata
  Data dir       : $data_dir
  Old data backup: $old_data_dir_backup
  SQL backup     : $backup_file
  Stop services  : ${stop_services_csv:-<none>}

Continue? [y/N]
EOF
  read -r confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    log "Cancelled."
    exit 1
  fi
fi

stopped_services=()
if [[ -n "$stop_services_csv" ]]; then
  IFS=',' read -r -a stop_services <<< "$stop_services_csv"
  for raw_service in "${stop_services[@]}"; do
    svc="$(trim "$raw_service")"
    [[ -n "$svc" ]] || continue
    [[ "$svc" != "$service" ]] || continue
    svc_id="$(compose ps -q "$svc" 2>/dev/null || true)"
    if [[ -n "$svc_id" ]]; then
      log "Stopping writer service: $svc"
      compose stop "$svc"
      stopped_services+=("$svc")
    fi
  done
fi

log "Stopping DB service: $service"
compose stop "$service"

[[ -d "$data_dir" ]] || err "Data dir does not exist: $data_dir"
parent_dir="$(dirname "$data_dir")"
[[ -w "$parent_dir" ]] || err "No write permission on parent dir: $parent_dir"

log "Rotating data dir to keep rollback path"
mv "$data_dir" "$old_data_dir_backup"
mkdir -p "$data_dir"
chown --reference="$old_data_dir_backup" "$data_dir" 2>/dev/null || true
chmod --reference="$old_data_dir_backup" "$data_dir" 2>/dev/null || true

override_file=""
cleanup() {
  if [[ -n "$override_file" ]] && [[ -f "$override_file" ]]; then
    rm -f "$override_file"
  fi
}
trap cleanup EXIT

if [[ -n "$new_image" ]]; then
  override_file="$(mktemp /tmp/postgres-upgrade-override.XXXXXX.yml)"
  cat > "$override_file" <<EOF
services:
  $service:
    image: $new_image
EOF
  log "Starting DB with override image: $new_image"
  compose_with_override "$override_file" up -d "$service"
else
  log "Starting DB with image from compose file: $target_image"
  compose up -d "$service"
fi

new_container_id="$(compose ps -q "$service" 2>/dev/null || true)"
[[ -n "$new_container_id" ]] || err "Could not resolve new container for service '$service'"
new_container_name="$(docker inspect --format '{{.Name}}' "$new_container_id" | sed 's#^/##')"

log "Waiting for Postgres readiness"
ready=false
for _ in $(seq 1 90); do
  if docker exec "$new_container_name" pg_isready -U "$db_user" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 2
done
[[ "$ready" == true ]] || err "Timed out waiting for Postgres to become ready"

restore_log="$(mktemp /tmp/postgres-restore.XXXXXX.log)"
restore_exit=0

log "Restoring backup (strict mode): $backup_file"
if [[ "$backup_file" == *.gz ]]; then
  if ! gunzip -c "$backup_file" | docker exec -i "$new_container_name" psql -v ON_ERROR_STOP=1 -U "$db_user" -d postgres >"$restore_log" 2>&1; then
    restore_exit=$?
  fi
else
  if ! cat "$backup_file" | docker exec -i "$new_container_name" psql -v ON_ERROR_STOP=1 -U "$db_user" -d postgres >"$restore_log" 2>&1; then
    restore_exit=$?
  fi
fi

if [[ "$restore_exit" -ne 0 ]]; then
  if rg -q '^ERROR:  role "postgres" already exists$|^ERROR:  database "postgres" already exists$' "$restore_log"; then
    log "Strict restore hit expected bootstrap conflicts. Retrying restore in permissive mode."
    if [[ "$backup_file" == *.gz ]]; then
      gunzip -c "$backup_file" | docker exec -i "$new_container_name" psql -U "$db_user" -d postgres >"$restore_log" 2>&1
    else
      cat "$backup_file" | docker exec -i "$new_container_name" psql -U "$db_user" -d postgres >"$restore_log" 2>&1
    fi
  else
    tail -n 40 "$restore_log" >&2
    err "Restore failed. See log: $restore_log"
  fi
fi

if rg -q '^FATAL:|^PANIC:' "$restore_log"; then
  tail -n 40 "$restore_log" >&2
  err "Restore produced fatal errors. See log: $restore_log"
fi

db_version="$(docker exec "$new_container_name" psql -U "$db_user" -d postgres -tAc 'select version();' | tr -d '\r')"
log "Restore complete. Running version: $db_version"

if [[ ${#stopped_services[@]} -gt 0 ]]; then
  for svc in "${stopped_services[@]}"; do
    log "Restarting service: $svc"
    compose start "$svc"
  done
fi

cat <<EOF

Upgrade completed successfully.
  Service         : $service
  Backup file     : $backup_file
  Old data dir    : $old_data_dir_backup
  Active data dir : $data_dir
  DB version      : $db_version

Rollback (manual):
  1) Stop writer services and DB
  2) Remove '$data_dir'
  3) Move '$old_data_dir_backup' back to '$data_dir'
  4) Start DB + writer services
EOF

if [[ -n "$new_image" ]]; then
  cat <<EOF

Reminder:
  Update the Postgres image for '$service' in your compose source to '$new_image'
  so future normal deploys do not revert to '$old_image'.
EOF
fi

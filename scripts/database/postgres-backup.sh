#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  postgres-backup.sh --service <compose_service> [options]

Required:
  --service NAME               Docker Compose service name (e.g. hatchet-db)

Options:
  --compose-file PATH          Compose file path
                               Default: compose/$MY_HOSTNAME.yml
  --env-file PATH              Env file passed to docker compose
                               Default: $HOME/docker/.env
  --profiles CSV               COMPOSE_PROFILES value (comma-separated)
  --db-user USER               Postgres user for pg_dumpall
                               Default: POSTGRES_USER from container, else postgres
  --backup-dir PATH            Backup directory
                               Default: $REPO_PATH/backups/postgres (or repo-root/backups/postgres)
  --output-file PATH           Exact output file path
  --start-if-stopped           Start the DB service if it's not currently running
  --no-gzip                    Write plain .sql instead of .sql.gz
  --print-path-only            Print only backup file path to stdout
  -h, --help                   Show this help

Examples:
  scripts/database/postgres-backup.sh --service hatchet-db --profiles programming,hatchet
  scripts/database/postgres-backup.sh --service forgejo-db --no-gzip
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

err() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

compose() {
  if [[ -n "$profiles" ]]; then
    COMPOSE_PROFILES="$profiles" docker compose -f "$compose_file" --env-file "$env_file" "$@"
  else
    docker compose -f "$compose_file" --env-file "$env_file" "$@"
  fi
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

service=""
compose_file=""
env_file="$HOME/docker/.env"
profiles=""
db_user=""
start_if_stopped=false
gzip_output=true
print_path_only=false
output_file=""
default_backup_root="${REPO_PATH:-$repo_root}/backups/postgres"
backup_dir="$default_backup_root"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      service="${2:-}"
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
    --db-user)
      db_user="${2:-}"
      shift 2
      ;;
    --backup-dir)
      backup_dir="${2:-}"
      shift 2
      ;;
    --output-file)
      output_file="${2:-}"
      shift 2
      ;;
    --start-if-stopped)
      start_if_stopped=true
      shift
      ;;
    --no-gzip)
      gzip_output=false
      shift
      ;;
    --print-path-only)
      print_path_only=true
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
if [[ -z "$container_id" ]] && [[ "$start_if_stopped" == true ]]; then
  if [[ "$print_path_only" == false ]]; then
    log "Service '$service' is not running. Starting it for backup."
  fi
  compose up -d "$service"
  container_id="$(compose ps -q "$service" 2>/dev/null || true)"
fi

[[ -n "$container_id" ]] || err "Service '$service' is not running. Use --start-if-stopped if needed."

container_name="$(docker inspect --format '{{.Name}}' "$container_id" | sed 's#^/##')"
[[ -n "$container_name" ]] || err "Could not resolve container name for service '$service'"

if [[ -z "$db_user" ]]; then
  db_user="$(
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_id" \
      | sed -n 's/^POSTGRES_USER=//p' \
      | head -n1
  )"
fi
db_user="${db_user:-postgres}"

timestamp="$(date '+%Y%m%d_%H%M%S')"
mkdir -p "$backup_dir"

if [[ -z "$output_file" ]]; then
  if [[ "$gzip_output" == true ]]; then
    output_file="$backup_dir/${service}_all_${timestamp}.sql.gz"
  else
    output_file="$backup_dir/${service}_all_${timestamp}.sql"
  fi
fi

mkdir -p "$(dirname "$output_file")"

if [[ "$print_path_only" == false ]]; then
  log "Backing up service '$service' (container: $container_name, user: $db_user)"
fi

if [[ "$gzip_output" == true ]]; then
  docker exec "$container_name" pg_dumpall -U "$db_user" | gzip -c > "$output_file"
else
  docker exec "$container_name" pg_dumpall -U "$db_user" > "$output_file"
fi

[[ -s "$output_file" ]] || err "Backup file is empty: $output_file"

if [[ "$print_path_only" == true ]]; then
  printf '%s\n' "$output_file"
  exit 0
fi

size_human="$(du -h "$output_file" | awk '{print $1}')"
log "Backup completed: $output_file ($size_human)"

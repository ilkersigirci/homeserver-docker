#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage:
  pbs-compose-cold-backup-docker-client.sh [--dry-run]

Legacy Docker-client cold backup flow:
  1. Start pbs-client container from apps/pbs-client.yml.
  2. Stop currently running app services, excluding pbs-client.
  3. Run "backupnow" inside pbs-client.
  4. Start the app services that were stopped.

Environment overrides:
  MY_HOSTNAME        Host compose name when COMPOSE_FILE is not set.
  COMPOSE_FILE       Default: compose/$MY_HOSTNAME.yml
  ENV_FILE           Default: .env
  COMPOSE_PROFILES   Default: core,desktop_apps,maintenance,media,monitoring,programming,reading,others
  STOP_TIMEOUT       Default: 120
  PBS_SERVICE        Default: pbs-client

Examples:
  MY_HOSTNAME=gpu scripts/backup/pbs-compose-cold-backup-docker-client.sh
  MY_HOSTNAME=gpu scripts/backup/pbs-compose-cold-backup-docker-client.sh --dry-run
USAGE
}

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

repo_path() {
  local path="$1"

  if [[ "$path" = /* ]]; then
    printf '%s\n' "$path"
  else
    printf '%s/%s\n' "$repo_root" "$path"
  fi
}

compose() {
  COMPOSE_PROFILES="$profiles" docker compose \
    -f "$compose_file" \
    -f "$pbs_compose_file" \
    --env-file "$env_file" \
    "$@"
}

run() {
  if [[ "$dry_run" == true ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi

  "$@"
}

load_running_services() {
  local services

  services="$(compose ps --services --filter status=running)" \
    || fail "Could not list running Compose services"

  running_services=()
  if [[ -n "$services" ]]; then
    mapfile -t running_services < <(grep -Fxv "$pbs_service" <<<"$services" || true)
  fi
}

stop_apps() {
  if [[ "${#running_services[@]}" -eq 0 ]]; then
    log "No running app services found to stop"
    return 0
  fi

  apps_stopped=true
  log "Stopping app services: ${running_services[*]}"
  run compose stop --timeout "$stop_timeout" "${running_services[@]}"
}

start_apps() {
  if [[ "$apps_stopped" != true ]]; then
    return 0
  fi

  log "Starting app services: ${running_services[*]}"
  run compose start "${running_services[@]}"
  apps_stopped=false
}

cleanup() {
  local status=$?
  trap - EXIT

  if ! start_apps; then
    status=1
  fi

  exit "$status"
}

parse_args() {
  dry_run=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        dry_run=true
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
  done
}

validate_config() {
  [[ -f "$compose_file" ]] || fail "Compose file not found: $compose_file"
  [[ -f "$pbs_compose_file" ]] || fail "PBS compose file not found: $pbs_compose_file"
  [[ -f "$env_file" ]] || fail "Env file not found: $env_file"
  [[ "$stop_timeout" =~ ^[0-9]+$ ]] || fail "STOP_TIMEOUT must be a whole number"
}

main() {
  parse_args "$@"

  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  profiles="${COMPOSE_PROFILES:-core,desktop_apps,maintenance,media,monitoring,programming,reading,others}"
  pbs_service="${PBS_SERVICE:-pbs-client}"
  stop_timeout="${STOP_TIMEOUT:-120}"
  pbs_compose_file="$repo_root/apps/pbs-client.yml"
  env_file="$(repo_path "${ENV_FILE:-.env}")"

  if [[ -n "${COMPOSE_FILE:-}" ]]; then
    compose_file="$(repo_path "$COMPOSE_FILE")"
  else
    [[ -n "${MY_HOSTNAME:-}" ]] || fail "MY_HOSTNAME is required when COMPOSE_FILE is not set"
    compose_file="$repo_root/compose/$MY_HOSTNAME.yml"
  fi

  validate_config
  load_running_services

  trap cleanup EXIT

  log "Starting $pbs_service"
  run compose up -d "$pbs_service"

  stop_apps

  log "Running PBS backup via $pbs_service"
  run compose exec -T "$pbs_service" backupnow

  log "PBS backup completed"
  start_apps
}

apps_stopped=false
running_services=()
main "$@"

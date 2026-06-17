#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage:
  pbs-compose-cold-backup.sh [--dry-run]

Generic cold backup flow:
  1. Verify the official proxmox-backup-client is installed.
  2. Stop currently running Docker Compose services.
  3. Back up /home/ilker/docker with proxmox-backup-client.
  4. Start the services that were stopped.

Required PBS environment:
  PBS_REPOSITORY or PBS_SERVER + PBS_DATASTORE
  PBS_PASSWORD or PBS_PASSWORD_FILE/PBS_PASSWORD_CMD/PBS_PASSWORD_FD

Common optional PBS environment:
  PBS_AUTH_ID
  PBS_NAMESPACE
  PBS_FINGERPRINT
  PBS_ENCRYPTION_PASSWORD or PBS_ENCRYPTION_PASSWORD_FILE/PBS_ENCRYPTION_PASSWORD_CMD/PBS_ENCRYPTION_PASSWORD_FD

Script environment overrides:
  MY_HOSTNAME        Host compose name when COMPOSE_FILE is not set.
  COMPOSE_FILE       Default: compose/$MY_HOSTNAME.yml
  ENV_FILE           Default: .env
  BACKUP_SOURCE      Default: /home/ilker/docker
  BACKUP_ARCHIVE     Default: docker.pxar
  COMPOSE_PROFILES   Default: core,desktop_apps,maintenance,media,monitoring,programming,reading,others
  STOP_TIMEOUT       Default: 120

Examples:
  MY_HOSTNAME=gpu scripts/backup/pbs-compose-cold-backup.sh
  MY_HOSTNAME=gpu PBS_NAMESPACE=hosts/gpu scripts/backup/pbs-compose-cold-backup.sh
  MY_HOSTNAME=gpu scripts/backup/pbs-compose-cold-backup.sh --dry-run
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
    mapfile -t running_services <<<"$services"
  fi
}

stop_apps() {
  if [[ "${#running_services[@]}" -eq 0 ]]; then
    log "No running services found to stop"
    return 0
  fi

  apps_stopped=true
  log "Stopping services: ${running_services[*]}"
  run compose stop --timeout "$stop_timeout" "${running_services[@]}"
}

start_apps() {
  if [[ "$apps_stopped" != true ]]; then
    return 0
  fi

  log "Starting services: ${running_services[*]}"
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
  command -v proxmox-backup-client >/dev/null || fail "proxmox-backup-client not found"
  [[ -f "$compose_file" ]] || fail "Compose file not found: $compose_file"
  [[ -f "$env_file" ]] || fail "Env file not found: $env_file"
  [[ -d "$backup_source" ]] || fail "Backup source not found: $backup_source"
  [[ "$stop_timeout" =~ ^[0-9]+$ ]] || fail "STOP_TIMEOUT must be a whole number"

  if [[ -z "${PBS_REPOSITORY:-}" ]]; then
    [[ -n "${PBS_SERVER:-}" ]] || fail "Set PBS_REPOSITORY or PBS_SERVER"
    [[ -n "${PBS_DATASTORE:-}" ]] || fail "Set PBS_REPOSITORY or PBS_DATASTORE"
  fi

  [[ -n "${PBS_PASSWORD:-}${PBS_PASSWORD_FILE:-}${PBS_PASSWORD_CMD:-}${PBS_PASSWORD_FD:-}" ]] \
    || fail "Set PBS_PASSWORD, PBS_PASSWORD_FILE, PBS_PASSWORD_CMD, or PBS_PASSWORD_FD"
}

run_backup() {
  local -a args=(backup "${backup_archive}:${backup_source}" --change-detection-mode=metadata)

  if [[ -n "${PBS_NAMESPACE:-}" ]]; then
    args+=(--ns "$PBS_NAMESPACE")
  fi

  log "Running proxmox-backup-client backup: ${backup_archive}:${backup_source}"
  run proxmox-backup-client "${args[@]}"
}

main() {
  parse_args "$@"

  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  profiles="${COMPOSE_PROFILES:-core,desktop_apps,maintenance,media,monitoring,programming,reading,others}"
  stop_timeout="${STOP_TIMEOUT:-120}"
  env_file="$(repo_path "${ENV_FILE:-.env}")"
  backup_source="${BACKUP_SOURCE:-/home/ilker/docker}"
  backup_archive="${BACKUP_ARCHIVE:-docker.pxar}"

  if [[ -n "${COMPOSE_FILE:-}" ]]; then
    compose_file="$(repo_path "$COMPOSE_FILE")"
  else
    [[ -n "${MY_HOSTNAME:-}" ]] || fail "MY_HOSTNAME is required when COMPOSE_FILE is not set"
    compose_file="$repo_root/compose/$MY_HOSTNAME.yml"
  fi

  validate_config
  load_running_services

  trap cleanup EXIT

  stop_apps
  run_backup
  log "PBS backup completed"
  start_apps
}

apps_stopped=false
running_services=()
main "$@"

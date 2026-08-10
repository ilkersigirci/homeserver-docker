#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<USAGE
Usage: ${0##*/}

Stops the host stack, backs up the repository with proxmox-backup-client,
and restarts the stack.

Optional environment:
  BACKUP_SOURCE   Default: repository root
  BACKUP_ARCHIVE  Default: docker.pxar
  PBS_NAMESPACE   Passed to proxmox-backup-client as --ns
USAGE
}

cleanup() {
  local status="$?"

  trap - EXIT
  bash "$DOCKER_MANAGE" up || status="$?"
  exit "$status"
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DOCKER_MANAGE="$REPO_ROOT/scripts/docker-manage.sh"

if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  usage
  exit 0
fi

if [[ $# -ne 0 ]]; then
  usage >&2
  exit 1
fi

if ! command -v proxmox-backup-client >/dev/null; then
  printf 'Error: proxmox-backup-client not found\n' >&2
  exit 1
fi

BACKUP_SOURCE="${BACKUP_SOURCE:-$REPO_ROOT}"
if [[ ! -d "$BACKUP_SOURCE" ]]; then
  printf 'Error: backup source not found: %s\n' "$BACKUP_SOURCE" >&2
  exit 1
fi

BACKUP_ARGS=(backup "${BACKUP_ARCHIVE:-docker.pxar}:$BACKUP_SOURCE" --change-detection-mode=metadata)
if [[ -n "${PBS_NAMESPACE:-}" ]]; then
  BACKUP_ARGS+=(--ns "$PBS_NAMESPACE")
fi

bash "$DOCKER_MANAGE" down
trap cleanup EXIT

proxmox-backup-client "${BACKUP_ARGS[@]}"

cleanup

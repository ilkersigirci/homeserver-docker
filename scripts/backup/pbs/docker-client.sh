#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<USAGE
Usage: ${0##*/}

Stops the host stack, runs backupnow through apps/pbs-client.yml,
and restarts the stack.
USAGE
}

cleanup() {
  local status="$?"

  trap - EXIT
  COMPOSE_FILE="$PBS_COMPOSE_FILE" bash "$DOCKER_MANAGE" down || status="$?"
  bash "$DOCKER_MANAGE" up || status="$?"
  exit "$status"
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DOCKER_MANAGE="$REPO_ROOT/scripts/docker-manage.sh"
PBS_COMPOSE_FILE="$REPO_ROOT/apps/pbs-client.yml"

if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  usage
  exit 0
fi

if [[ $# -ne 0 ]]; then
  usage >&2
  exit 1
fi

bash "$DOCKER_MANAGE" down
trap cleanup EXIT

COMPOSE_FILE="$PBS_COMPOSE_FILE" bash "$DOCKER_MANAGE" up
docker exec pbs-client backupnow

cleanup

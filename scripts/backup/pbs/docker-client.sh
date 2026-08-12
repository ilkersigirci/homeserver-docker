#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<USAGE
Usage: ${0##*/}

Stops the host stack, runs the backup defined in apps/pbs-client-hs.yml,
and restarts the stack.
USAGE
}

run_pbs_compose() {
  docker compose \
    --project-name pbs-client \
    --profile maintenance \
    --env-file "$REPO_ROOT/.env" \
    --file "$PBS_COMPOSE_FILE" \
    "$@"
}

cleanup() {
  local status="$?"

  trap - EXIT
  run_pbs_compose down --remove-orphans || status="$?"
  bash "$DOCKER_MANAGE" up || status="$?"
  exit "$status"
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DOCKER_MANAGE="$REPO_ROOT/scripts/docker-manage.sh"
PBS_COMPOSE_FILE="$REPO_ROOT/apps/pbs-client-hs.yml"

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

run_pbs_compose run --rm pbs-client

cleanup

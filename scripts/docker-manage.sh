#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [up|down|update|pull|prune|restart]" >&2
  exit 1
}

[[ $# == 1 ]] || usage
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
: "${MY_HOSTNAME:?Set MY_HOSTNAME to the inventory hostname}"
compose_file="${COMPOSE_FILE:-compose/$MY_HOSTNAME.yml}"
for file in "$compose_file" .env compose/profiles.env; do
  if [[ ! -f "$file" ]]; then
    echo "Missing required file: $file" >&2
    exit 1
  fi
done

compose=(docker compose -f "$compose_file" --env-file .env --env-file compose/profiles.env)
case "$1" in
  up)      "${compose[@]}" up -d ;;
  down)    "${compose[@]}" down --remove-orphans ;;
  pull)    "${compose[@]}" pull ;;
  prune)   docker image prune -f ;;
  update)
    "${compose[@]}" pull
    "${compose[@]}" up -d
    docker image prune -f
    ;;
  restart)
    "${compose[@]}" down --remove-orphans
    "${compose[@]}" up -d
    ;;
  *) usage ;;
esac

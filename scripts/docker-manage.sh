#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ACTION="${1:-}"
PROFILES="${COMPOSE_PROFILES:-core,desktop_apps,maintenance,media,monitoring,programming,reading,others}"
ENV_FILE="${REPO_ROOT}/.env"

# Function to display usage
usage() {
    echo "Usage: $0 [up|down|update|pull|prune|restart]"
    echo "  up         - Start containers"
    echo "  down       - Stop containers"
    echo "  update     - Update containers"
    echo "  pull       - Pull latest images without restarting"
    echo "  prune      - Remove dangling images"
    echo "  restart    - Restart containers"
    exit 1
}

validate_action() {
    case "$ACTION" in
        "up"|"down"|"update"|"pull"|"prune"|"restart")
            ;;
        *)
            usage
            ;;
    esac
}

validate_config() {
    if [ -z "${MY_HOSTNAME:-}" ]; then
        echo "⚠️  MY_HOSTNAME is not set. Please export it in your .bashrc or .zshrc file"
        exit 1
    fi

    # Maintenance scripts can override this to manage standalone Compose files such as PBS.
    COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/compose/${MY_HOSTNAME}.yml}"
    if [[ "$COMPOSE_FILE" != /* ]]; then
        COMPOSE_FILE="${REPO_ROOT}/${COMPOSE_FILE}"
    fi

    if [ ! -f "$COMPOSE_FILE" ]; then
        echo "⚠️  Compose file not found: $COMPOSE_FILE"
        exit 1
    fi

    if [ ! -f "$ENV_FILE" ]; then
        echo "⚠️  Env file not found: $ENV_FILE"
        exit 1
    fi
}

run_compose() {
    COMPOSE_PROFILES="$PROFILES" docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

prune_images() {
    echo "🧹 Cleaning up dangling images..."
    docker image prune -f
}

# Check if command argument is provided
if [ $# -ne 1 ]; then
    usage
fi

validate_action
validate_config

# Change directory to docker folder
cd "$REPO_ROOT"

# Handle commands
case "$ACTION" in
    "up")
        echo "🚀 Starting containers..."
        run_compose up -d
        echo "✅ Containers started successfully!"
        ;;

    "down")
        echo "🔽 Stopping containers..."
        run_compose down --remove-orphans
        echo "✅ Containers stopped successfully!"
        ;;

    "update")
        echo "🔄 Updating containers..."
        run_compose pull
        run_compose up -d
        prune_images
        echo "✅ Update complete!"
        ;;

    "pull")
        echo "🔄 Pulling containers..."
        run_compose pull
        echo "✅ Pull complete!"
        ;;

    "prune")
        prune_images
        echo "✅ Image cleanup complete!"
        ;;

    "restart")
        echo "🔄 Restarting containers..."
        run_compose down --remove-orphans
        run_compose up -d
        echo "✅ Containers restarted successfully!"
        ;;

    *)
        usage
        ;;
esac

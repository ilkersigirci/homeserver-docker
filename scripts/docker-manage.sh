#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ACTION="${1:-}"
PROFILES="${COMPOSE_PROFILES:-core,desktop_apps,maintenance,media,monitoring,programming,reading,others}"
ENV_FILE="${REPO_ROOT}/.env"

# Function to display usage
usage() {
    echo "Usage: $0 [up|down|update|pull|prune|restart|prep-perms]"
    echo "  up         - Start containers"
    echo "  down       - Stop containers"
    echo "  update     - Update containers"
    echo "  pull       - Pull latest images without restarting"
    echo "  prune      - Remove dangling images"
    echo "  restart    - Restart containers"
    echo "  prep-perms - Create/chown bind paths for non-root services"
    exit 1
}

validate_action() {
    case "$ACTION" in
        "up"|"down"|"update"|"pull"|"prune"|"restart"|"prep-perms")
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

    COMPOSE_FILE="${REPO_ROOT}/compose/${MY_HOSTNAME}.yml"

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

prepare_permissions() {
    local script_path="$REPO_ROOT/scripts/prepare-bind-permissions.sh"
    local profile_arg="custom-user"

    if [ "$(id -u)" -eq 0 ]; then
        bash "$script_path" --compose-file "$COMPOSE_FILE" --env-file "$ENV_FILE" --profiles "$profile_arg"
    else
        sudo bash "$script_path" --compose-file "$COMPOSE_FILE" --env-file "$ENV_FILE" --profiles "$profile_arg"
    fi
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

    "prep-perms")
        echo "🔐 Preparing bind-mount permissions for non-root services..."
        prepare_permissions
        echo "✅ Permission bootstrap completed!"
        ;;

    *)
        usage
        ;;
esac

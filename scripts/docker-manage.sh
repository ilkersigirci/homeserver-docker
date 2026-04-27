#!/usr/bin/bash

set -e  # Exit on error

if [ -z "$MY_HOSTNAME" ]; then
    echo "⚠️  MY_HOSTNAME is not set. Please export it in your or .bashrc .zshrc file"
    exit 1
fi

# Configuration
PROFILES="core,desktop_apps,maintenance,media,monitoring,programming,reading,others"
COMPOSE_FILE="compose/$MY_HOSTNAME.yml"
ENV_FILE="$HOME/docker/.env"
COMPOSE_CMD="docker compose -f $COMPOSE_FILE --env-file $ENV_FILE"

# Function to display usage
usage() {
    echo "Usage: $0 [up|down|pull|pull_only|restart|prep-perms]"
    echo "  up         - Start containers"
    echo "  down       - Stop containers"
    echo "  pull       - Update containers"
    echo "  pull_only  - Pull latest images without restarting"
    echo "  restart    - Restart containers"
    echo "  prep-perms - Create/chown bind paths for non-root services"
    exit 1
}

prepare_permissions() {
    local script_path="$HOME/docker/scripts/prepare-bind-permissions.sh"
    local profile_arg="custom-user"

    if [ "$(id -u)" -eq 0 ]; then
        bash "$script_path" --compose-file "$HOME/docker/$COMPOSE_FILE" --env-file "$ENV_FILE" --profiles "$profile_arg"
    else
        sudo bash "$script_path" --compose-file "$HOME/docker/$COMPOSE_FILE" --env-file "$ENV_FILE" --profiles "$profile_arg"
    fi
}

# Check if command argument is provided
if [ $# -eq 0 ]; then
    usage
fi

# Change directory to  docker folder
cd $HOME/docker

# Handle commands
case "$1" in
    "up")
        echo "🚀 Starting containers..."
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD up -d
        echo "✅ Containers started successfully!"
        ;;

    "down")
        echo "🔽 Stopping containers..."
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD down --remove-orphans
        echo "✅ Containers stopped successfully!"
        ;;

    "pull")
        echo "🔄 Updating containers..."
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD pull
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD up -d
        echo "🧹 Cleaning up dangling images..."
        docker image prune -f || echo "⚠️  Warning: Image cleanup failed"
        echo "✅ Update complete!"
        ;;

    "pull_only")
        echo "🔄 Pulling containers..."
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD pull
        echo "✅ Pull complete!"
        ;;

    "restart")
        echo "🔄 Restarting containers..."
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD down --remove-orphans
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD up -d
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

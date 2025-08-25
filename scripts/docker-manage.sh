#!/usr/bin/zsh

set -e  # Exit on error

if [ -z "$MY_HOSTNAME" ]; then
    echo "⚠️  MY_HOSTNAME is not set. Please export it in your or .bashrc .zshrc file"
    exit 1
fi

# Configuration
PROFILES="core,desktop_apps,ml,maintenance,media,monitoring,photo,reading,others"
COMPOSE_CMD="docker compose -f docker-compose.$MY_HOSTNAME.yml --env-file $HOME/docker/.env"

# Function to display usage
usage() {
    echo "Usage: $0 [up|down|pull|restart]"
    echo "  up      - Start containers"
    echo "  down    - Stop containers"
    echo "  pull    - Update containers"
    echo "  restart - Restart containers"
    exit 1
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
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD --profile '!custom-build' pull
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD up -d
        echo "🧹 Cleaning up dangling images..."
        docker image prune -f || echo "⚠️  Warning: Image cleanup failed"
        echo "✅ Update complete!"
        ;;
    
    "restart")
        echo "🔄 Restarting containers..."
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD down --remove-orphans
        COMPOSE_PROFILES=$PROFILES $COMPOSE_CMD up -d
        echo "✅ Containers restarted successfully!"
        ;;
    
    *)
        usage
        ;;
esac

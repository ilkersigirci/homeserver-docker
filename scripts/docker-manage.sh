#!/usr/bin/zsh

set -e  # Exit on error

# Configuration
PROFILES="core,ml,maintenance,media,monitoring,reading"
COMPOSE_CMD="docker compose --env-file $HOME/docker/.env"

# Function to display usage
usage() {
    echo "Usage: $0 [up|down|pull]"
    echo "  up    - Start containers"
    echo "  down  - Stop containers"
    echo "  pull  - Update containers"
    exit 1
}

# Check if command argument is provided
if [ $# -eq 0 ]; then
    usage
fi

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
    
    *)
        usage
        ;;
esac

#!/bin/sh

# Set default values
PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Update group and user IDs if they differ from defaults
if [ "$PGID" != "1000" ]; then
    echo "Changing GID to $PGID"
    groupmod -g $PGID appgroup
fi

if [ "$PUID" != "1000" ]; then
    echo "Changing UID to $PUID"
    usermod -u $PUID appuser
fi

# Fix ownership of any files that might need it
# chown -R appuser:appgroup /config /logs 2>/dev/null || true

# Set default config file if not specified
SCOTTY_CONFIG_FILE=${SCOTTY_CONFIG_FILE:-$HOME/.config/scotty/scotty.toml}

# Execute scotty with config-file argument as appuser
exec su-exec appuser scotty --config "$SCOTTY_CONFIG_FILE" "$@"

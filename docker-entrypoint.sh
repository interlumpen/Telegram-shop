#!/bin/bash
set -e

# Default UID/GID values (common default for first non-root user on Linux)
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "Starting with UID: $PUID, GID: $PGID"

# Create group if it doesn't exist with target GID
if ! getent group botgroup > /dev/null 2>&1; then
    groupadd -g "$PGID" botgroup
else
    # Update GID if different
    CURRENT_GID=$(getent group botgroup | cut -d: -f3)
    if [ "$CURRENT_GID" != "$PGID" ]; then
        groupmod -g "$PGID" botgroup 2>/dev/null || true
    fi
fi

# Check if botuser exists and update UID/GID, or create if doesn't exist
if id botuser > /dev/null 2>&1; then
    # User exists, update UID/GID if different
    CURRENT_UID=$(id -u botuser)
    CURRENT_GID=$(id -g botuser)

    if [ "$CURRENT_UID" != "$PUID" ]; then
        usermod -u "$PUID" botuser 2>/dev/null || true
    fi
    if [ "$CURRENT_GID" != "$PGID" ]; then
        usermod -g botgroup botuser 2>/dev/null || true
    fi
else
    # Create user with specified UID/GID
    useradd -u "$PUID" -g botgroup -m -s /bin/bash botuser
fi

# Ensure directories exist
mkdir -p /app/logs /app/data

# Set ownership on mounted directories (these are the critical ones)
chown botuser:botgroup /app/logs /app/data

# Ensure log files exist and are writable
touch /app/logs/bot.log /app/logs/audit.log 2>/dev/null || true
chown botuser:botgroup /app/logs/bot.log /app/logs/audit.log 2>/dev/null || true

# Set ownership on app directory itself (but not recursively to avoid slowdown)
chown botuser:botgroup /app

echo "Permissions configured. Running as botuser..."

# Run migrations and start bot as botuser using gosu
exec gosu botuser bash -lc "alembic upgrade head && python run.py"

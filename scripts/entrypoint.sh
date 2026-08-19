#!/bin/bash
set -euo pipefail

echo "==> Starting entrypoint..."

# Wait for MariaDB to be ready (if using MariaDB in production)
if [ "${DB_HOST:-}" != "" ] && [ "${DB_HOST:-}" != "localhost" ] && [ "${DB_HOST:-}" != "127.0.0.1" ]; then
    echo "==> Waiting for MariaDB at ${DB_HOST}:${DB_PORT:-3306}..."
    until python -c "
import socket
s = socket.create_connection(('${DB_HOST}', int('${DB_PORT:-3306}')), timeout=2)
s.close()
print('MariaDB port is reachable!')
" 2>/dev/null; do
        echo "    MariaDB not ready, retrying in 2s..."
        sleep 2
    done
    echo "    MariaDB is reachable."
fi

# Run migrations with a lock file to prevent concurrent migration runs
# across multiple replicas. In practice, run migrations as a separate
# one-off step (see docs/deployment.md) rather than in every container.
MIGRATION_LOCK="/tmp/django_migrations.lock"

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    echo "==> Running migrations (RUN_MIGRATIONS=true)..."
    (
        flock -n 9 || { echo "    Another migration is running, skipping."; exit 0; }
        python manage.py migrate --noinput
        echo "    Migrations complete."
    ) 9>"$MIGRATION_LOCK"
fi

# Collect static files (only needed if not already built into the image)
if [ ! -d "/app/staticfiles" ] || [ -z "$(ls -A /app/staticfiles 2>/dev/null)" ]; then
    echo "==> Collecting static files..."
    python manage.py collectstatic --noinput
fi

echo "==> Starting server: $*"
exec "$@"

#!/bin/sh
# Container entrypoint: wait for dependencies, migrate, collect static, then exec.
set -eu

echo "[entrypoint] Running Django system checks..."
python manage.py check --deploy --fail-level ERROR

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[entrypoint] Applying database migrations..."
  python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-true}" = "true" ]; then
  echo "[entrypoint] Collecting static files..."
  python manage.py collectstatic --noinput
fi

echo "[entrypoint] Starting: $*"
exec "$@"

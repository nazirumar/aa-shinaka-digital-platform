#!/usr/bin/env bash
#
# Render start command (native Python runtime).
#
# The Docker image has deploy/entrypoint.sh, but a native-runtime service starts
# straight into the process named by `startCommand`. This script restores the
# same guarantees: apply migrations once (idempotent) before serving, then exec
# Gunicorn so it becomes PID 1 and receives Render's SIGTERM directly.
#
# Static files are already collected by `build.sh` during the build step; this
# script does NOT re-run collectstatic on every boot.
#
set -euo pipefail

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[start] Applying database migrations..."
  python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-false}" = "true" ]; then
  echo "[start] Collecting static files..."
  python manage.py collectstatic --noinput
fi

echo "[start] Starting: $*"
exec "$@"

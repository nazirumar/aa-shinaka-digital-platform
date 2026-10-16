#!/usr/bin/env bash
#
# Controlled database migration for the Docker Compose deployment.
#
#   ./deploy/scripts/db_migrate.sh [--with-backup] [--env-file FILE]
#
# Why this exists: the container entrypoint can migrate on boot, which is unsafe
# once more than one web replica exists. In this deployment every long-running
# service sets RUN_MIGRATIONS=false and migrations are performed by the single
# one-shot `migrate` service. This wrapper runs exactly that service, under a
# host-side lock, so two operators (or a cron job and an operator) can never
# migrate concurrently.
#
# It never rolls back migrations: rollback guidance lives in
# docs/HOSTINGER_VPS_DEPLOYMENT.md ("Safe updates and rollback").

set -euo pipefail

ENV_FILE="${ENV_FILE:-deploy/.env.production}"
WITH_BACKUP=0
COMPOSE_FILE="deploy/docker-compose.yml"
LOCK_FILE="${MIGRATE_LOCK_FILE:-/tmp/aa-shinaka-migrate.lock}"

while [ $# -gt 0 ]; do
  case "$1" in
    --with-backup) WITH_BACKUP=1; shift ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) printf 'db_migrate: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

log() { printf '%s [migrate] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[ -f "$ENV_FILE" ] || fail "env file not found: $ENV_FILE (copy deploy/.env.production.example)"
command -v docker >/dev/null 2>&1 || fail "docker is not installed"

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

# --- Serialise migrations ---------------------------------------------------
# One migration at a time, host-wide. flock is present on Ubuntu by default.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE" || fail "cannot open lock file $LOCK_FILE"
  flock -n 9 || fail "another migration is already running (lock: $LOCK_FILE)"
else
  log "WARNING: flock not found; relying on the single migrate service for safety"
fi

# --- Optional pre-migration backup -----------------------------------------
if [ "$WITH_BACKUP" = "1" ]; then
  log "Taking a pre-migration backup"
  ./deploy/scripts/backup_docker.sh --env-file "$ENV_FILE"
fi

# --- Bring up the dependencies (idempotent; starts nothing else) -----------
log "Ensuring PostgreSQL and Redis are running"
"${COMPOSE[@]}" up -d db redis

# --- Show what is about to be applied --------------------------------------
log "Pending migrations:"
"${COMPOSE[@]}" run --rm --no-deps web python manage.py showmigrations --plan \
  | grep -E '^\[' || log "  (none listed)"

# --- Apply ------------------------------------------------------------------
# A one-shot container (restart: "no") that is the ONLY thing in the stack which
# ever runs `migrate`. It also collects static files once, into the shared
# volume. Long-running services then start with RUN_MIGRATIONS=false.
log "Running the one-shot 'migrate' service"
"${COMPOSE[@]}" up -d --build migrate

log "Waiting for the release step to finish"
if ! "${COMPOSE[@]}" wait migrate; then
  "${COMPOSE[@]}" logs --tail 50 migrate
  fail "the migration container failed; the database may be partially migrated — review before retrying"
fi

log "Migrations and collectstatic completed successfully"

#!/usr/bin/env bash
#
# Staging deploy orchestrator.
#
#   ./deploy/scripts/staging_deploy.sh [git-ref]
#
# Sequence (fails fast, never touches production or DNS):
#   1. preflight (env validation + checks + migration guard + verifier)
#   2. build the image
#   3. take a pre-deploy backup
#   4. apply migrations, collect static
#   5. restart web/worker/beat
#   6. smoke test + host verification
#
# Staging only. It refuses to run against the production compose file.

set -euo pipefail

REF="${1:-$(git rev-parse --abbrev-ref HEAD)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-deploy/.env.staging}"
COMPOSE_FILES=(-f deploy/docker-compose.yml -f deploy/docker-compose.staging.yml)
COMPOSE=(docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}")
BASE_URL="${BASE_URL:-https://staging.EXAMPLE_DOMAIN}"

log() { printf '%s [staging] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

case "$ENV_FILE" in
  *staging*) ;;
  *) echo "staging_deploy: ENV_FILE must be a staging env file (got ${ENV_FILE})" >&2; exit 2;;
esac

log "Preflight"
DJANGO_SETTINGS_MODULE=config.settings.staging "${SCRIPT_DIR}/preflight.sh" "$ENV_FILE"

log "Checking out ${REF}"
git fetch --all --tags
git checkout "$REF"

log "Building image"
"${COMPOSE[@]}" build web

log "Pre-deploy backup"
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a
"${SCRIPT_DIR}/backup.sh" || log "WARNING: backup failed — investigate before proceeding"

log "Applying migrations"
"${COMPOSE[@]}" run --rm web python manage.py migrate --noinput

log "Collecting static files"
"${COMPOSE[@]}" run --rm web python manage.py collectstatic --noinput

log "Restarting services"
"${COMPOSE[@]}" up -d --no-deps web worker beat

log "Smoke test"
BASE_URL="$BASE_URL" "${SCRIPT_DIR}/smoke_test.sh"

log "Host verification"
BASE_URL="$BASE_URL" HOST="${BASE_URL#https://}" "${SCRIPT_DIR}/verify_host.sh" || \
  log "WARNING: host verification reported failures — review before sign-off"

log "Staging deploy complete for ${REF}."

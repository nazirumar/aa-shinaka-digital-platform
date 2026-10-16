#!/usr/bin/env bash
#
# Safe rollback to a previous release.
#
#   ROLLBACK_CONFIRM=yes ./deploy/scripts/rollback.sh <previous-git-ref>
#
# Rolls the CODE back to <previous-git-ref>, rebuilds and restarts the stack, then
# runs the smoke test. It does NOT reverse database migrations: migrations are
# additive and reversing them can destroy data. If a bad migration shipped,
# restore the pre-deploy backup into an isolated database and cut over
# (see docs/DISASTER_RECOVERY.md).

set -euo pipefail

REF="${1:?usage: rollback.sh <previous-git-ref>}"
[ "${ROLLBACK_CONFIRM:-}" = "yes" ] || {
  echo "rollback: set ROLLBACK_CONFIRM=yes to confirm the rollback" >&2
  exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-deploy/.env.production}"
COMPOSE="docker compose --env-file ${ENV_FILE} -f ${COMPOSE_FILE}"
BASE_URL="${BASE_URL:-https://EXAMPLE_DOMAIN}"

log() { printf '%s [rollback] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

log "Current ref: $(git rev-parse --short HEAD). Rolling back to ${REF}"
git fetch --all --tags
git checkout "$REF"

log "Rebuilding image"
$COMPOSE build web

log "Restarting application services (migrations are NOT reversed)"
$COMPOSE up -d --no-deps web worker beat

log "Smoke test"
BASE_URL="$BASE_URL" "${SCRIPT_DIR}/smoke_test.sh" || {
  log "POST-ROLLBACK SMOKE TEST FAILED — escalate per docs/PRODUCTION_RUNBOOK.md"
  exit 1
}

log "Rolled back to ${REF}. Verify migrations match the code (manage.py migrate --check)."

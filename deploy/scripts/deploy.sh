#!/usr/bin/env bash
#
# Deployment helper for the Docker Compose stack.
#
#   ./deploy/scripts/deploy.sh [--env-file FILE] [--ref GIT_REF] [--no-build]
#
# Steps: optional git checkout -> build -> run the single release container
# (system check + collectstatic + migrate) -> start/refresh the app -> smoke
# test. Prints the ref it deployed so you can roll back.
#
# Safety properties
#   * Migrations run in exactly one container, before any app container starts
#     (`depends_on: service_completed_successfully`). A failed migration aborts
#     the rollout instead of starting a half-migrated application.
#   * It never touches DNS and never enables live payments.
#   * It does not delete volumes, images or backups.
#   * `--ref` refuses to check out if the working tree is dirty.

set -euo pipefail

ENV_FILE="${ENV_FILE:-deploy/.env.production}"
REF=""
BUILD=1

while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --no-build) BUILD=0; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) printf 'deploy: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.yml)
BASE_URL="${BASE_URL:-https://EXAMPLE_DOMAIN}"

log() { printf '%s [deploy] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[ -f "$ENV_FILE" ] || fail "env file not found: $ENV_FILE"
[ -f deploy/nginx/conf.d/default.conf ] || fail "nginx config not rendered; run deploy/scripts/render_nginx.sh <domain>"

# --- Optional code update ---------------------------------------------------
if [ -n "$REF" ]; then
  [ -z "$(git status --porcelain)" ] || fail "working tree is dirty; commit or stash before --ref"
  log "Fetching and checking out ${REF}"
  git fetch --all --tags
  git checkout "$REF"
fi

previous_ref="$(git rev-parse --short HEAD)"

# --- Pre-deploy gates (non-destructive) -------------------------------------
log "Running preflight"
./deploy/scripts/preflight.sh "$ENV_FILE" || fail "preflight failed — nothing was deployed"

# --- Build ------------------------------------------------------------------
if [ "$BUILD" = "1" ]; then
  log "Building images"
  "${COMPOSE[@]}" build
fi

# --- Release: check + collectstatic + migrate, in one container -------------
log "Running the release container (system check, collectstatic, migrate)"
"${COMPOSE[@]}" up -d migrate
if ! "${COMPOSE[@]}" wait migrate; then
  log "Migration container output:"
  "${COMPOSE[@]}" logs --tail 50 migrate
  fail "the release step failed; rollout aborted (no app container was started)"
fi

# --- Start / refresh the application ---------------------------------------
log "Starting application services"
"${COMPOSE[@]}" up -d
"${COMPOSE[@]}" ps

# --- Smoke test -------------------------------------------------------------
log "Smoke testing ${BASE_URL}/healthz/"
for _ in 1 2 3 4 5; do
  if curl -fsS --max-time 10 "${BASE_URL}/healthz/" >/dev/null 2>&1; then
    log "Smoke test passed"
    log "Deployed ${previous_ref}. Roll back with: git checkout <previous-ref> && deploy/scripts/deploy.sh"
    exit 0
  fi
  sleep 5
done

log "SMOKE TEST FAILED — investigate and roll back (see docs/PRODUCTION_RUNBOOK.md)"
exit 1

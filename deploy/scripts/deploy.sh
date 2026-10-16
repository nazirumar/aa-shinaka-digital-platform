#!/usr/bin/env bash
#
# Zero-downtime-ish deployment helper (Docker Compose reference).
#
#   ./deploy/scripts/deploy.sh <git-ref>
#
# Steps: fetch ref -> build image -> run migrations -> collect static -> restart
# web/worker -> smoke test. Prints the previous image tag so you can roll back.
# This script never touches DNS and never runs against production automatically.

set -euo pipefail

REF="${1:?usage: deploy.sh <git-ref>}"
COMPOSE="docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml"
BASE_URL="${BASE_URL:-https://EXAMPLE_DOMAIN}"

log() { printf '%s [deploy] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

log "Fetching ${REF}"
git fetch --all --tags
git checkout "$REF"

log "Building image"
$COMPOSE build web

log "Applying migrations"
$COMPOSE run --rm web python manage.py migrate --noinput
$COMPOSE run --rm web python manage.py check --deploy --fail-level ERROR

log "Collecting static files"
$COMPOSE run --rm web python manage.py collectstatic --noinput

log "Restarting application services"
$COMPOSE up -d --no-deps web worker beat

log "Running smoke test"
for i in 1 2 3 4 5; do
  if curl -fsS --max-time 10 "${BASE_URL}/healthz/" >/dev/null 2>&1; then
    log "Smoke test passed"
    log "Deployed ${REF}. Roll back with: git checkout <previous-ref> && deploy.sh <previous-ref>"
    exit 0
  fi
  sleep 5
done

log "SMOKE TEST FAILED — investigate and roll back (see docs/PRODUCTION_RUNBOOK.md)"
exit 1

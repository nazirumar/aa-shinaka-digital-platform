#!/usr/bin/env bash
#
# Non-destructive pre-deploy gate.
#
#   ./deploy/scripts/preflight.sh [ENV_FILE]
#
# Runs, in order and with no destructive side effects:
#   1. environment validation (validate_env.sh)
#   2. Django system checks with the production settings module
#   3. missing-migration guard
#   4. "are there unapplied migrations?" check (migrate --check)
#   5. the deployment verifier (verify_deployment)
#
# It never runs `migrate` for real and never restarts a service. Exits non-zero
# if any step fails, so a deploy pipeline stops before touching the live stack.
#
# Two execution modes, chosen automatically:
#   * container mode — when DATABASE_URL points at the Compose service name
#     `db` (the VPS deployment) the Django checks run inside the application
#     image over the internal network, because `db` does not resolve from the
#     host filesystem;
#   * host mode — otherwise (CI, a developer machine) the checks run through
#     `uv run`, exactly as before.
# Force either with AA_PREFLIGHT_MODE=container|host.

set -uo pipefail

ENV_FILE="${1:-deploy/.env.production}"
SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MODE="${AA_PREFLIGHT_MODE:-auto}"

cd "$REPO_ROOT"

[ -f "$ENV_FILE" ] || { printf 'preflight: env file not found: %s\n' "$ENV_FILE" >&2; exit 2; }

echo "== preflight: validate environment (${ENV_FILE}) =="
"${SCRIPT_DIR}/validate_env.sh" "$ENV_FILE" || exit 1

# --- Choose an execution mode ----------------------------------------------
if [ "$MODE" = "auto" ]; then
  db_host="$(grep -E '^[[:space:]]*DATABASE_URL=' "$ENV_FILE" | tail -n1 \
    | sed -E 's#^[^=]*=[a-z]+://##; s#^[^@]*@##; s#[:/].*##')"
  case "$db_host" in
    db|postgres|database) MODE=container ;;
    *) MODE=host ;;
  esac
fi

if [ "$MODE" = "container" ] && ! command -v docker >/dev/null 2>&1; then
  echo "preflight: container mode requested but docker is unavailable" >&2
  exit 1
fi

if [ "$MODE" = "container" ]; then
  echo "== preflight: running Django checks inside the application image =="
  COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.yml)
  # `run` starts the databases (healthy) but overrides the command; the
  # entrypoint keeps RUN_MIGRATIONS=false so nothing is applied here.
  "${COMPOSE[@]}" run --rm -T \
    -e RUN_COLLECTSTATIC=false \
    --entrypoint sh migrate -c '
      set -e
      echo "-- Django system check (deploy) --"
      python manage.py check --deploy --fail-level ERROR
      echo "-- missing-migration guard --"
      python manage.py makemigrations --check --dry-run
      echo "-- unapplied-migration check (non-destructive) --"
      python manage.py migrate --check
      echo "-- deployment verifier --"
      python manage.py verify_deployment
    ' || exit 1

  echo "preflight: all gates passed (container mode)."
  exit 0
fi

# --- Host mode --------------------------------------------------------------
echo "== preflight: running Django checks on the host (uv) =="
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

export DJANGO_SETTINGS_MODULE="$SETTINGS_MODULE"

echo "== preflight: Django system check (${SETTINGS_MODULE}) =="
uv run python manage.py check --deploy --fail-level ERROR || exit 1

echo "== preflight: missing-migration guard =="
uv run python manage.py makemigrations --check --dry-run || exit 1

echo "== preflight: unapplied-migration check (non-destructive) =="
if ! uv run python manage.py migrate --check; then
  echo "preflight: there are unapplied migrations; run 'deploy/scripts/db_migrate.sh' during the deploy step" >&2
  exit 1
fi

echo "== preflight: deployment verifier =="
uv run python manage.py verify_deployment || exit 1

echo "preflight: all gates passed (host mode)."

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

set -uo pipefail

ENV_FILE="${1:-deploy/.env.production}"
SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "$REPO_ROOT"

echo "== preflight: validate environment (${ENV_FILE}) =="
"${SCRIPT_DIR}/validate_env.sh" "$ENV_FILE" || exit 1

# Load the env file so the management commands see it (does not export to the
# caller's shell beyond this process).
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
  echo "preflight: there are unapplied migrations; run 'manage.py migrate' during the deploy step" >&2
  exit 1
fi

echo "== preflight: deployment verifier =="
uv run python manage.py verify_deployment || exit 1

echo "preflight: all gates passed."

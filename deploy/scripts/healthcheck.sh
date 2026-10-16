#!/usr/bin/env bash
#
# End-to-end health check for monitoring (cron / uptime probe / alerting hook).
#
#   BASE_URL=https://EXAMPLE_DOMAIN ./deploy/scripts/healthcheck.sh
#
# Checks the HTTP liveness probe, then (when running on the host) Redis and the
# Celery worker. Exits non-zero and prints a reason on the first failure.

set -uo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
failures=0

check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "OK   ${name}"
  else
    echo "FAIL ${name}"
    failures=$((failures + 1))
  fi
}

check "http /healthz/" curl -fsS --max-time 10 "${BASE_URL}/healthz/"

if command -v redis-cli >/dev/null 2>&1 && [ -n "${REDIS_URL:-}" ]; then
  check "redis ping" redis-cli -u "$REDIS_URL" ping
fi

if command -v celery >/dev/null 2>&1 && [ -n "${CELERY_BROKER_URL:-}" ]; then
  check "celery ping" celery -A config inspect ping -t 5
fi

if [ "${failures}" -gt 0 ]; then
  echo "healthcheck: ${failures} check(s) failed"
  exit 1
fi
echo "healthcheck: all checks passed"

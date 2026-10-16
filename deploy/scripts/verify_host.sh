#!/usr/bin/env bash
#
# Host-level security verification (run AFTER the stack is up on staging/prod).
#
#   BASE_URL=https://staging.example.com HOST=staging.example.com \
#       ./deploy/scripts/verify_host.sh
#
# Verifies controls that cannot be checked from inside the application:
#   * a valid TLS chain,
#   * HTTP -> HTTPS redirect,
#   * HSTS and nosniff headers on the wire,
#   * /media/ default-deny,
#   * the application port is not publicly reachable.
#
# Exits non-zero if any check fails. Read-only.

set -uo pipefail

BASE_URL="${BASE_URL:-https://staging.example.com}"
BASE_URL="${BASE_URL%/}"
HOST="${HOST:-${BASE_URL#https://}}"
APP_PORT="${APP_PORT:-8000}"
MEDIA_DENY_PATH="${MEDIA_DENY_PATH:-/media/quarantine/probe.txt}"
failures=0

ok()   { echo "OK   $*"; }
bad()  { echo "FAIL $*"; failures=$((failures + 1)); }

echo "Host verification for ${BASE_URL}"

# 1. Valid TLS chain (no -k): a certificate problem must fail here.
if curl -fsS -o /dev/null --max-time 15 "${BASE_URL}/healthz/"; then
  ok "TLS chain valid and /healthz/ reachable over HTTPS"
else
  bad "HTTPS request failed (certificate chain or connectivity)"
fi

# 2. HTTP redirects to HTTPS.
redirect="$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 15 "http://${HOST}/" || echo '000 ')"
case "$redirect" in
  301*|302*|308*) ok "HTTP redirect present (${redirect})";;
  *) bad "HTTP did not redirect to HTTPS (${redirect})";;
esac

# 3. Security headers on the wire.
headers="$(curl -sI --max-time 15 "${BASE_URL}/" || true)"
case "$headers" in
  *[Ss]trict-[Tt]ransport-[Ss]ecurity*) ok "HSTS header present";;
  *) bad "HSTS header missing";;
esac
case "$headers" in
  *[Xx]-[Cc]ontent-[Tt]ype-[Oo]ptions*) ok "nosniff header present";;
  *) bad "X-Content-Type-Options header missing";;
esac

# 4. Private media default-deny.
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${BASE_URL}${MEDIA_DENY_PATH}" || echo 000)"
case "$code" in
  403|404) ok "/media/ default-deny (${code})";;
  *) bad "/media/ is reachable (${code}); private files may be exposed";;
esac

# 5. Application port not publicly reachable.
if command -v nc >/dev/null 2>&1; then
  if nc -z -w 3 "$HOST" "$APP_PORT" 2>/dev/null; then
    bad "application port ${APP_PORT} is publicly reachable (only nginx should be)"
  else
    ok "application port ${APP_PORT} is not publicly reachable"
  fi
else
  echo "SKIP application port check (nc not installed)"
fi

if [ "$failures" -gt 0 ]; then
  echo "verify_host: ${failures} check(s) failed"
  exit 1
fi
echo "verify_host: all checks passed"

#!/usr/bin/env bash
#
# Post-deploy smoke test for the AA Shinaka platform.
#
#   BASE_URL=https://staging.example.com ./deploy/scripts/smoke_test.sh
#
# Read-only: it only issues GETs. Exits non-zero on the first failed expectation
# so a deploy pipeline can stop and roll back.

set -uo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
BASE_URL="${BASE_URL%/}"
failures=0

# expect <path> <expected codes...>   (e.g. expect / 200 301)
expect() {
  local path="$1"; shift
  local expected=("$@")
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${BASE_URL}${path}" || echo 000)"
  local ok=0
  for want in "${expected[@]}"; do
    [ "$code" = "$want" ] && ok=1
  done
  if [ "$ok" = 1 ]; then
    echo "OK   ${path} -> ${code}"
  else
    echo "FAIL ${path} -> ${code} (expected ${expected[*]})"
    failures=$((failures + 1))
  fi
}

echo "Smoke test against ${BASE_URL}"

# expect_private <path> — a private document/route that must NOT be readable
# anonymously. Django auth-gates these; nginx additionally default-denies
# /media/. A 200 here is a security defect, not a cosmetic failure.
expect_private() {
  local path="$1"
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${BASE_URL}${path}" || echo 000)"
  case "$code" in
    200)
      echo "FAIL ${path} -> 200 (private content served anonymously!)"
      failures=$((failures + 1))
      ;;
    301|302|303|401|403|404)
      echo "OK   ${path} -> ${code} (refused anonymously)"
      ;;
    *)
      echo "FAIL ${path} -> ${code} (unexpected response)"
      failures=$((failures + 1))
      ;;
  esac
}

expect /healthz/ 200
expect / 200
expect /shop/ 200
expect /training/ 200
expect /accounts/login/ 200
expect /accounts/register/ 200
expect /robots.txt 200
expect /static/css/app.css 200

# Customer invoices, payment evidence and export documents must never be
# downloadable without authentication.
expect_private /invoices/
expect_private /invoices/AA-000001/
expect_private /invoices/AA-000001/pdf/
expect_private /receipts/AA-000001/
expect_private /receipts/AA-000001/pdf/
expect_private /payments/
expect_private /orders/
expect_private /account/export/
expect_private /account/support/

# Private media must never be served directly by the edge.
MEDIA_DENY_PATH="${MEDIA_DENY_PATH:-/media/quarantine/probe.txt}"
expect "${MEDIA_DENY_PATH}" 403 404
expect_private /media/invoices/probe.pdf
expect_private /media/export-documents/probe.pdf
expect_private /media/payment-evidence/probe.jpg

# The health probe must report a live database.
body="$(curl -s --max-time 15 "${BASE_URL}/healthz/" || true)"
case "$body" in
  *'"status": "ok"'*|*'"status":"ok"'*) echo "OK   /healthz/ reports database ok";;
  *) echo "FAIL /healthz/ body did not report status ok: ${body}"; failures=$((failures + 1));;
esac

if [ "$failures" -gt 0 ]; then
  echo "smoke_test: ${failures} check(s) failed"
  exit 1
fi
echo "smoke_test: all checks passed"

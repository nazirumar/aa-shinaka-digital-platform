#!/usr/bin/env bash
#
# Render the nginx site configuration for a real domain.
#
#   ./deploy/scripts/render_nginx.sh <domain> [--bootstrap] [--reload]
#   ./deploy/scripts/render_nginx.sh --local [--reload]
#
# The repository ships a TEMPLATE with an EXAMPLE_DOMAIN placeholder; it is
# never mounted directly, so no fabricated hostname can end up serving traffic.
# This script substitutes the owner-supplied domain into
# deploy/nginx/conf.d/default.conf (gitignored), which is what nginx mounts.
#
#   --bootstrap   render the HTTP-only config used to obtain the first
#                 certificate (see ssl_bootstrap.sh)
#   --local       render the HTTP-only config used by the LOCAL test stack
#                 (deploy/docker-compose.local.yml). No domain is needed or
#                 accepted: it serves `localhost` over plain HTTP and is never
#                 used on a deployed host.
#   --reload      reload nginx afterwards if the container is running
#
# This script does NOT touch DNS, certificates or any remote system.

set -euo pipefail

DOMAIN=""
BOOTSTRAP=0
LOCAL=0
RELOAD=0

while [ $# -gt 0 ]; do
  case "$1" in
    --bootstrap) BOOTSTRAP=1; shift ;;
    --local) LOCAL=1; shift ;;
    --reload) RELOAD=1; shift ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    -*) printf 'render_nginx: unknown option: %s\n' "$1" >&2; exit 2 ;;
    *) DOMAIN="$1"; shift ;;
  esac
done

SRC_DIR="deploy/nginx"
OUT_DIR="deploy/nginx/conf.d"
OUT="${OUT_DIR}/default.conf"

log() { printf '%s [nginx] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

if [ "$LOCAL" = "1" ]; then
  [ -z "$DOMAIN" ] || fail "--local renders a localhost config; do not pass a domain"
  TEMPLATE="${SRC_DIR}/local.conf"
  log "Rendering LOCAL (HTTP-only) config for localhost"
else
  [ -n "$DOMAIN" ] || fail "usage: render_nginx.sh <domain> [--bootstrap] [--reload] | --local [--reload]"
  case "$DOMAIN" in
    EXAMPLE_DOMAIN|example.com|localhost|'*')
      fail "'$DOMAIN' is a placeholder or invalid; supply the owner-approved domain" ;;
  esac
  # Lowercase hostname, at least one dot, valid label characters.
  if ! printf '%s' "$DOMAIN" | grep -Eq '^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$'; then
    fail "'$DOMAIN' does not look like a valid hostname (e.g. shop.example.com)"
  fi

  if [ "$BOOTSTRAP" = "1" ]; then
    TEMPLATE="${SRC_DIR}/bootstrap.conf"
    log "Rendering BOOTSTRAP (HTTP-only) config for ${DOMAIN}"
  else
    TEMPLATE="${SRC_DIR}/aa-shinaka.conf"
    log "Rendering TLS config for ${DOMAIN}"
  fi
fi
[ -f "$TEMPLATE" ] || fail "template not found: $TEMPLATE"

mkdir -p "$OUT_DIR"
if [ "$LOCAL" = "1" ]; then
  cp "$TEMPLATE" "$OUT"
else
  sed "s/EXAMPLE_DOMAIN/${DOMAIN}/g" "$TEMPLATE" > "$OUT"
fi

# Fail loudly rather than shipping an unsubstituted placeholder.
if grep -q 'EXAMPLE_DOMAIN' "$OUT"; then
  rm -f "$OUT"
  fail "placeholder EXAMPLE_DOMAIN survived rendering; aborting"
fi
log "Wrote ${OUT}"

if [ "$RELOAD" = "1" ]; then
  if docker compose ps nginx 2>/dev/null | grep -q -i 'running\|up'; then
    log "Reloading nginx"
    docker compose exec -T nginx nginx -s reload
  else
    log "nginx is not running; the new config takes effect on next start"
  fi
fi

log "Done. Verify with: docker compose exec nginx nginx -t"

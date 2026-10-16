#!/usr/bin/env bash
#
# Renew TLS certificates and reload nginx if they changed.
#
#   ./deploy/scripts/ssl_renew.sh <domain>
#
# Intended for a daily/twice-daily cron entry (Let's Encrypt certificates are
# valid for 90 days; `certbot renew` is a no-op until ~30 days remain).
# Safe to run often. Does not touch DNS.

set -euo pipefail

DOMAIN="${1:-}"
ENV_FILE="${ENV_FILE:-deploy/.env.production}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.yml)

log() { printf '%s [ssl-renew] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[ -n "$DOMAIN" ] || fail "usage: ssl_renew.sh <domain>"

# Record the certificate fingerprint so we only reload when it actually changes.
before="$(openssl x509 -in deploy/nginx/certs/fullchain.pem -noout -fingerprint -sha256 2>/dev/null || echo none)"

log "Requesting renewal"
"${COMPOSE[@]}" run --rm certbot renew --webroot --webroot-path /var/www/certbot --quiet

LE_DIR="deploy/nginx/certs/live/${DOMAIN}"
if [ -f "${LE_DIR}/fullchain.pem" ]; then
  cp "${LE_DIR}/fullchain.pem" deploy/nginx/certs/fullchain.pem
  cp "${LE_DIR}/privkey.pem" deploy/nginx/certs/privkey.pem
  chmod 600 deploy/nginx/certs/privkey.pem
fi

after="$(openssl x509 -in deploy/nginx/certs/fullchain.pem -noout -fingerprint -sha256 2>/dev/null || echo none)"

if [ "$before" != "$after" ]; then
  log "Certificate changed — reloading nginx"
  "${COMPOSE[@]}" exec -T nginx nginx -s reload
  log "Renewal applied"
else
  log "No change; nothing to reload"
fi

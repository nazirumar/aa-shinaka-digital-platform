#!/usr/bin/env bash
#
# Obtain the first TLS certificate (Let's Encrypt) for the deployment.
#
#   ./deploy/scripts/ssl_bootstrap.sh <domain> <email> [--staging]
#
# Chicken-and-egg problem: the TLS nginx config needs a certificate, but the
# certificate is issued through an ACME HTTP-01 challenge that nginx must serve.
# This script solves it in three phases, each of which is safe to re-run:
#
#   1. render the HTTP-only bootstrap config and start nginx (plus web, which
#      nginx proxies to for /healthz/);
#   2. run the one-shot certbot service in webroot mode;
#   3. render the TLS config and reload nginx.
#
# It does NOT touch DNS and does NOT run against a host you have not already
# prepared. The domain's A/AAAA record must already point at this server and
# ports 80/443 must be reachable, otherwise the ACME challenge fails.
#
#   --staging   use the Let's Encrypt staging CA (untrusted certs) to rehearse
#               issuance safely without burning the production rate limit.

set -euo pipefail

DOMAIN=""
EMAIL=""
ACME_SERVER=0
ENV_FILE="${ENV_FILE:-deploy/.env.production}"

while [ $# -gt 0 ]; do
  case "$1" in
    --staging) ACME_SERVER=1; shift ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    -*) printf 'ssl_bootstrap: unknown option: %s\n' "$1" >&2; exit 2 ;;
    *)
      if [ -z "$DOMAIN" ]; then DOMAIN="$1"; elif [ -z "$EMAIL" ]; then EMAIL="$1"; fi
      shift ;;
  esac
done

log() { printf '%s [ssl] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[ -n "$DOMAIN" ] || fail "usage: ssl_bootstrap.sh <domain> <email> [--staging]"
[ -n "$EMAIL" ] || fail "a contact email is required for Let's Encrypt"
case "$DOMAIN" in EXAMPLE_DOMAIN|example.com) fail "'$DOMAIN' is a placeholder" ;; esac

COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.yml)

log "Phase 1/3 — starting nginx with the HTTP-only bootstrap config"
./deploy/scripts/render_nginx.sh "$DOMAIN" --bootstrap
mkdir -p deploy/nginx/certbot-www deploy/nginx/certs
"${COMPOSE[@]}" up -d db redis
"${COMPOSE[@]}" up -d --build migrate web
"${COMPOSE[@]}" up -d nginx

log "Phase 2/3 — requesting the certificate for ${DOMAIN} and www.${DOMAIN}"
certbot_args=(
  certonly --webroot --webroot-path /var/www/certbot
  -d "$DOMAIN" -d "www.$DOMAIN"
  --email "$EMAIL" --agree-tos --no-eff-email --non-interactive
  --keep-until-expiring
)
if [ "$ACME_SERVER" = "1" ]; then
  log "Using the Let's Encrypt STAGING CA (certificates will not be trusted)"
  certbot_args+=(--server https://acme-staging-v02.api.letsencrypt.org/directory)
fi

# The certbot service mounts ./nginx/certs at /etc/letsencrypt; the live/ paths
# are then copied next to nginx's expected filenames.
"${COMPOSE[@]}" run --rm certbot "${certbot_args[@]}" || fail "certbot failed — check that DNS points here and port 80 is open"

LE_DIR="deploy/nginx/certs/live/${DOMAIN}"
[ -f "${LE_DIR}/fullchain.pem" ] || fail "expected certificate at ${LE_DIR}/fullchain.pem"
cp "${LE_DIR}/fullchain.pem" deploy/nginx/certs/fullchain.pem
cp "${LE_DIR}/privkey.pem" deploy/nginx/certs/privkey.pem
chmod 600 deploy/nginx/certs/privkey.pem
log "Installed certificate into deploy/nginx/certs/"

log "Phase 3/3 — switching nginx to the TLS config"
./deploy/scripts/render_nginx.sh "$DOMAIN" --reload

cat <<EOF

Certificate issued. Remaining manual steps (owner-approved):
  * Add a DNS-record check for www.$DOMAIN (a CNAME/A to this server).
  * Schedule renewal, e.g. in root's crontab:
      0 3 * * * cd $(pwd) && ./deploy/scripts/ssl_renew.sh >> /var/log/aa-shinaka-ssl.log 2>&1
  * Only after HTTPS is verified end-to-end, consider enabling HSTS preload.
EOF

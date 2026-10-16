#!/usr/bin/env bash
#
# Fail-safe environment validation for a deployment.
#
#   ./deploy/scripts/validate_env.sh [ENV_FILE]
#
# Defaults to deploy/.env.production. Verifies that every required variable is
# present and that obvious mistakes (placeholders, weak secrets, wildcard hosts,
# non-HTTPS origins, console email, non-Redis cache, a live Paystack key) are
# caught BEFORE anything is built or restarted. Exits non-zero on any problem and
# never writes to the environment file or the database.

set -uo pipefail

ENV_FILE="${1:-deploy/.env.production}"
fail=0

err() { printf 'validate_env: ERROR: %s\n' "$*" >&2; fail=1; }
info() { printf 'validate_env: %s\n' "$*"; }
warn() { printf 'validate_env: WARNING: %s\n' "$*" >&2; }

[ -f "$ENV_FILE" ] || { printf 'validate_env: env file not found: %s\n' "$ENV_FILE" >&2; exit 2; }

# Raw value for a key (last assignment wins), ignoring comments/blank lines.
get() {
  grep -E "^[[:space:]]*$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

require() {
  local key="$1" val
  val="$(get "$key")"
  if [ -z "${val}" ]; then err "required variable '$key' is empty or missing"; fi
}

REQUIRED=(
  DJANGO_SECRET_KEY
  DJANGO_ALLOWED_HOSTS
  CSRF_TRUSTED_ORIGINS
  DATABASE_URL
  POSTGRES_PASSWORD
  REDIS_PASSWORD
  CACHE_URL
  EMAIL_BACKEND
  EMAIL_HOST
  DEFAULT_FROM_EMAIL
  SITE_URL
)
for key in "${REQUIRED[@]}"; do require "$key"; done

# --- Secret strength --------------------------------------------------------
secret="$(get DJANGO_SECRET_KEY)"
if [ -n "$secret" ]; then
  if [ "${#secret}" -lt 50 ]; then err "DJANGO_SECRET_KEY is too short (${#secret} < 50 characters)"; fi
  case "$secret" in
    *django-insecure*|*change-me*|*CHANGE_ME*) err "DJANGO_SECRET_KEY still looks like a placeholder";;
  esac
fi

# --- Hosts & CSRF origins ---------------------------------------------------
hosts="$(get DJANGO_ALLOWED_HOSTS)"
case "$hosts" in *'*'*) err "DJANGO_ALLOWED_HOSTS must not contain a wildcard";; esac

origins="$(get CSRF_TRUSTED_ORIGINS)"
if [ -n "$origins" ]; then
  IFS=',' read -r -a _origin_list <<< "$origins"
  for origin in "${_origin_list[@]}"; do
    case "$(printf '%s' "$origin" | tr -d ' ')" in
      https://*) ;;
      *) err "CSRF_TRUSTED_ORIGINS entry '$origin' must start with https://";;
    esac
  done
fi

# --- Database / cache / email ----------------------------------------------
case "$(get DATABASE_URL)" in
  postgres://*|postgresql://*) ;;
  "") ;;
  *) err "DATABASE_URL must be a postgres:// URL";;
esac

# --- Database credentials must describe the same database -------------------
# The container is initialised from POSTGRES_*, while Django connects with
# DATABASE_URL. If the two passwords differ, the database comes up healthy and
# every request fails — a slow, confusing outage. Catch it here.
db_url="$(get DATABASE_URL)"
postgres_password="$(get POSTGRES_PASSWORD)"
if [ -n "$db_url" ] && [ -n "$postgres_password" ]; then
  url_password="$(printf '%s' "$db_url" | sed -E 's#^[a-z]+://[^:@/]+:([^@]*)@.*#\1#')"
  if [ "$url_password" != "$postgres_password" ]; then
    err "the password in DATABASE_URL does not match POSTGRES_PASSWORD"
  fi
fi

# --- Cache / Redis ----------------------------------------------------------
case "$(get CACHE_URL)" in
  redis://*|rediss://*) ;;
  "") ;;
  *) err "CACHE_URL must point at Redis (redis:// or rediss://)";;
esac

redis_password="$(get REDIS_PASSWORD)"
if [ -n "$redis_password" ]; then
  # It is embedded in redis:// URLs, so reserved characters would break them.
  case "$redis_password" in
    *[!A-Za-z0-9_]*) err "REDIS_PASSWORD must be URL-safe ([A-Za-z0-9_]); it is embedded in the Redis URLs";;
  esac
  for key in CACHE_URL CELERY_BROKER_URL CELERY_RESULT_BACKEND; do
    value="$(get "$key")"
    if [ -n "$value" ]; then
      case "$value" in
        *":${redis_password}@"*) ;;
        *) err "$key does not embed REDIS_PASSWORD (they must match)";;
      esac
    fi
  done
fi

# --- PostgreSQL transport ---------------------------------------------------
# PostgreSQL runs inside the Compose network with no TLS listener and no
# published port. Requiring SSL there makes psycopg refuse to connect.
if printf '%s' "$(get DB_SSLMODE_REQUIRE)" | grep -qiE '^(1|true|yes)$'; then
  warn "DB_SSLMODE_REQUIRE=True: the bundled postgres container serves no TLS. Set it to False for the Compose deployment (keep True only for a managed remote database)."
fi

email="$(get EMAIL_BACKEND)"
case "$email" in
  *console*|*locmem*|*dummy*) err "EMAIL_BACKEND must be a real delivery backend in a deployment";;
esac
case "$(get EMAIL_HOST)" in localhost|127.0.0.1) err "EMAIL_HOST must be the real mail host, not a loopback address";; esac

# --- Payment safety ---------------------------------------------------------
# Never allow live Paystack keys/mode through this validator. Enabling live
# payments is a separate, owner-approved launch action.
live_mode="$(get PAYSTACK_LIVE_MODE)"
secret_key="$(get PAYSTACK_SECRET_KEY)"
case "$(printf '%s' "$live_mode" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes) err "PAYSTACK_LIVE_MODE is enabled — live payments require explicit owner approval";;
esac
case "$secret_key" in sk_live_*) err "a live Paystack secret key (sk_live_…) must not be configured here";; esac

# --- Placeholders -----------------------------------------------------------
while IFS= read -r line; do
  case "$line" in ''|'#'*) continue;; esac
  case "$line" in
    *EXAMPLE_DOMAIN*|*CHANGE_ME*) err "placeholder value still present: ${line%%=*}";;
  esac
  # A whole-value placeholder such as KEY=<your-value> (but not an email display
  # name like "AA Shinaka <no-reply@example.com>").
  value="${line#*=}"
  case "$value" in '<'*'>') err "placeholder value still present: ${line%%=*}";; esac
done < "$ENV_FILE"

if [ "$fail" -ne 0 ]; then
  printf 'validate_env: %s FAILED validation\n' "$ENV_FILE" >&2
  exit 1
fi

info "$ENV_FILE passed validation."

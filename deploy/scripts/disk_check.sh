#!/usr/bin/env bash
#
# Disk-space and volume growth monitor for the AA Shinaka VPS.
#
#   ./deploy/scripts/disk_check.sh [--threshold PERCENT] [--env-file FILE]
#
# Exits non-zero when a monitored filesystem exceeds the threshold, so cron or
# a monitoring agent can raise an alert BEFORE the database or Docker fills the
# disk. A full disk on a single VPS stops PostgreSQL writes and can corrupt a
# deployment — this is the cheapest guard against it.
#
# Read-only: it never deletes anything.

set -euo pipefail

THRESHOLD="${DISK_USAGE_THRESHOLD:-85}"
ENV_FILE="${ENV_FILE:-deploy/.env.production}"

while [ $# -gt 0 ]; do
  case "$1" in
    --threshold) THRESHOLD="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) printf 'disk_check: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

log() { printf '%s [disk] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

BACKUP_DIR="${BACKUP_DIR:-}"
if [ -f "$ENV_FILE" ] && [ -z "$BACKUP_DIR" ]; then
  BACKUP_DIR="$(grep -E '^[[:space:]]*BACKUP_DIR=' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)"
fi

# Mount points worth watching on a Hostinger KVM VPS.
PATHS=(/ /var /var/lib/docker)
[ -n "$BACKUP_DIR" ] && PATHS+=("$BACKUP_DIR")

fail=0
declare -A SEEN=()

for path in "${PATHS[@]}"; do
  [ -d "$path" ] || continue
  # Parse from the right: the mount point is the last field and the capacity the
  # field before it. Fixed columns break when the device name contains a space
  # (e.g. MSYS) or the mount point is long.
  mount="$(df -P "$path" | awk 'NR==2 {print $NF}')"
  [ -n "${SEEN[$mount]:-}" ] && continue
  SEEN[$mount]=1
  used="$(df -P "$path" | awk 'NR==2 {v=$(NF-1); gsub(/%/,"",v); print v}')"
  avail="$(df -Ph "$path" | awk 'NR==2 {print $(NF-2)}')"
  if [ "${used:-0}" -ge "$THRESHOLD" ]; then
    log "CRITICAL: $mount (${path}) is ${used}% full (${avail} free) — threshold ${THRESHOLD}%"
    fail=1
  else
    log "ok: $mount (${path}) ${used}% used, ${avail} free"
  fi
done

# Docker volume / dangling-image growth is a common silent disk eater.
if command -v docker >/dev/null 2>&1; then
  # `|| true`: with `set -o pipefail` a Docker CLI error (e.g. daemon not
  # running) would otherwise abort this monitor and report a false failure.
  dangling="$(docker image ls -f dangling=true -q 2>/dev/null | wc -l | tr -d ' ' || true)"
  volumes="$(docker volume ls -q 2>/dev/null | wc -l | tr -d ' ' || true)"
  dangling="$(printf '%s' "${dangling:-0}" | tr -dc '0-9')"
  volumes="$(printf '%s' "${volumes:-0}" | tr -dc '0-9')"
  log "docker: ${dangling:-0} dangling image(s), ${volumes:-0} volume(s)"
  if [ "${dangling:-0}" -gt 10 ]; then
    log "WARNING: ${dangling} dangling images — consider 'docker image prune -f'"
  fi
fi

exit "$fail"

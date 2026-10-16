#!/usr/bin/env bash
#
# Encrypted, off-server PostgreSQL backup for the Docker Compose deployment.
#
#   ./deploy/scripts/backup_docker.sh [--env-file FILE] [--no-offsite]
#
# Why a separate script from backup.sh: in this deployment PostgreSQL lives in a
# container, so pg_dump must run inside it. Encryption keys and the off-server
# copy deliberately stay on the HOST (never inside a container), so a compromise
# of the application image does not yield the backups.
#
# Pipeline
#   docker compose exec db pg_dump -Fc  -> verify with pg_restore --list
#     -> encrypt (age preferred, gpg fallback)
#     -> copy off-server (rclone) -> prune local copies -> report disk usage
#
# Exit non-zero on any failure so cron/monitoring raises an alert.
# Never writes to the database. Never deletes anything but expired backups in
# BACKUP_DIR.

set -euo pipefail

ENV_FILE="${ENV_FILE:-deploy/.env.production}"
OFFSITE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --no-offsite) OFFSITE=0; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) printf 'backup_docker: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[ -f "$ENV_FILE" ] || { printf 'backup_docker: env file not found: %s\n' "$ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

BACKUP_DIR="${BACKUP_DIR:-/var/backups/aa-shinaka}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.yml)

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="aa_shinaka_${STAMP}"
RAW="${BACKUP_DIR}/${BASE}.dump"
OUT="${RAW}"

log() { printf '%s [backup] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

mkdir -p "$BACKUP_DIR"
[ -w "$BACKUP_DIR" ] || fail "backup directory is not writable: $BACKUP_DIR"

# --- 1. Dump inside the db container ---------------------------------------
log "Dumping ${POSTGRES_DB:-aa_shinaka} to ${RAW}"
"${COMPOSE[@]}" exec -T db \
  pg_dump -U "${POSTGRES_USER:-aa_shinaka}" -d "${POSTGRES_DB:-aa_shinaka}" \
  --format=custom --no-owner --no-privileges > "$RAW"

[ -s "$RAW" ] || fail "dump is empty — refusing to continue"

# --- 2. Verify the archive is actually restorable --------------------------
# Never trust an unverified backup.
"${COMPOSE[@]}" exec -T db pg_restore --list < "$RAW" > /dev/null \
  || fail "backup archive is not readable by pg_restore"
log "Archive verified ($(du -h "$RAW" | cut -f1))"

# --- 3. Encrypt at rest (age preferred, gpg fallback) ----------------------
if command -v age >/dev/null 2>&1 && [ -n "${BACKUP_AGE_RECIPIENT:-}" ]; then
  log "Encrypting with age"
  age --recipient "$BACKUP_AGE_RECIPIENT" --output "${RAW}.age" "$RAW"
  rm -f "$RAW"
  OUT="${RAW}.age"
elif command -v gpg >/dev/null 2>&1 && [ -n "${BACKUP_GPG_RECIPIENT:-}" ]; then
  log "Encrypting with gpg (recipient ${BACKUP_GPG_RECIPIENT})"
  gpg --yes --trust-model always --encrypt --recipient "$BACKUP_GPG_RECIPIENT" \
      --output "${RAW}.gpg" "$RAW"
  rm -f "$RAW"
  OUT="${RAW}.gpg"
else
  # Loud, not silent: an unencrypted backup on the same disk is not a backup
  # strategy, and the brief requires encrypted off-server copies.
  log "ERROR: no encryption configured — set BACKUP_AGE_RECIPIENT or BACKUP_GPG_RECIPIENT"
  fail "refusing to leave an unencrypted dump (use --no-offsite only for a local rehearsal)"
fi

# --- 4. Copy off-server ----------------------------------------------------
if [ "$OFFSITE" = "1" ]; then
  if command -v rclone >/dev/null 2>&1 && [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
    log "Uploading to ${BACKUP_RCLONE_REMOTE}"
    rclone copy "$OUT" "$BACKUP_RCLONE_REMOTE" --checksum \
      || fail "off-server copy failed — the backup is NOT off-server"
  else
    fail "no rclone remote configured (BACKUP_RCLONE_REMOTE); backups must leave this host"
  fi
fi

# --- 5. Prune local copies -------------------------------------------------
log "Pruning local backups older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -maxdepth 1 -name 'aa_shinaka_*.dump*' -mtime "+${RETENTION_DAYS}" -delete

# --- 6. Disk report --------------------------------------------------------
used="$(df -P "$BACKUP_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
log "Backup complete: ${OUT} ($(du -h "$OUT" | cut -f1)); backup filesystem ${used}% used"
[ "${used:-0}" -lt "${DISK_USAGE_THRESHOLD:-85}" ] \
  || log "WARNING: backup filesystem is ${used}% full (threshold ${DISK_USAGE_THRESHOLD:-85}%)"

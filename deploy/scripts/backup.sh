#!/usr/bin/env bash
#
# Automated PostgreSQL backup for the AA Shinaka platform.
#
#   DATABASE_URL=postgres://user:pass@host:5432/db ./deploy/scripts/backup.sh
#
# Produces a compressed custom-format dump, verifies it is readable, optionally
# encrypts it and copies it off-server, then prunes old local backups.
# Exit non-zero on any failure so monitoring/cron can raise an alert.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/aa-shinaka}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="aa_shinaka_${STAMP}"
RAW="${BACKUP_DIR}/${BASE}.dump"
OUT="${RAW}"

DATABASE_URL="${DATABASE_URL:?DATABASE_URL must be set}"

log() { printf '%s [backup] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

command -v pg_dump >/dev/null 2>&1 || fail "pg_dump not found on PATH"
mkdir -p "$BACKUP_DIR"

log "Dumping database to ${RAW}"
# Custom format (-Fc) supports parallel restore and compression.
pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner --no-privileges --file="$RAW"

# Never trust a backup you have not verified: confirm the archive is readable.
command -v pg_restore >/dev/null 2>&1 && pg_restore --list "$RAW" >/dev/null \
  || fail "backup archive is not readable by pg_restore"

# Optional encryption at rest (age preferred; falls back to gpg if configured).
if command -v age >/dev/null 2>&1 && [ -n "${BACKUP_AGE_RECIPIENT:-}" ]; then
  log "Encrypting with age"
  age --recipient "$BACKUP_AGE_RECIPIENT" --output "${RAW}.age" "$RAW"
  rm -f "$RAW"
  OUT="${RAW}.age"
elif command -v gpg >/dev/null 2>&1 && [ -n "${BACKUP_GPG_RECIPIENT:-}" ]; then
  log "Encrypting with gpg"
  gpg --yes --encrypt --recipient "$BACKUP_GPG_RECIPIENT" --output "${RAW}.gpg" "$RAW"
  rm -f "$RAW"
  OUT="${RAW}.gpg"
else
  log "WARNING: no encryption configured (set BACKUP_AGE_RECIPIENT or BACKUP_GPG_RECIPIENT)"
fi

# Optional off-server copy (rclone remote, e.g. s3/backups/aa-shinaka).
if command -v rclone >/dev/null 2>&1 && [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
  log "Uploading to ${BACKUP_RCLONE_REMOTE}"
  rclone copy "$OUT" "$BACKUP_RCLONE_REMOTE" --checksum
else
  log "WARNING: no off-server copy configured (set BACKUP_RCLONE_REMOTE)"
fi

log "Pruning local backups older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -maxdepth 1 -name 'aa_shinaka_*.dump*' -mtime "+${RETENTION_DAYS}" -delete

log "Backup complete: ${OUT} ($(du -h "$OUT" | cut -f1))"

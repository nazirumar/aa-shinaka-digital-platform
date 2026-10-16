#!/usr/bin/env bash
#
# Restore a backup produced by deploy/scripts/backup.sh into a target database.
#
#   TARGET_DATABASE_URL=postgres://... ./deploy/scripts/restore.sh /path/to/aa_shinaka_*.dump
#
# Safety:
#   * Refuses to run unless RESTORE_CONFIRM=yes (guards against accidents).
#   * Drops and recreates only the schema objects owned by the dump (--clean).
#   * Verifies the archive before touching the database.
#
# For disaster recovery, restore into an ISOLATED database first, verify, then
# point the application at it. See docs/DISASTER_RECOVERY.md.

set -euo pipefail

DUMP="${1:?usage: restore.sh <dump-file>}"
TARGET_DATABASE_URL="${TARGET_DATABASE_URL:?TARGET_DATABASE_URL must be set}"

log() { printf '%s [restore] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[ "${RESTORE_CONFIRM:-}" = "yes" ] || fail "set RESTORE_CONFIRM=yes to confirm this restore"
[ -f "$DUMP" ] || fail "dump file not found: $DUMP"

WORK="$DUMP"
if [ "${DUMP##*.}" = "age" ]; then
  command -v age >/dev/null 2>&1 || fail "age not installed"
  [ -n "${BACKUP_AGE_IDENTITY:-}" ] || fail "BACKUP_AGE_IDENTITY must point at the age identity file"
  WORK="$(mktemp)"
  age --decrypt --identity "$BACKUP_AGE_IDENTITY" --output "$WORK" "$DUMP"
elif [ "${DUMP##*.}" = "gpg" ]; then
  command -v gpg >/dev/null 2>&1 || fail "gpg not installed"
  WORK="$(mktemp)"
  gpg --quiet --decrypt --output "$WORK" "$DUMP"
fi

log "Verifying archive"
pg_restore --list "$WORK" >/dev/null || fail "archive is not readable"

log "Restoring into target database"
pg_restore --dbname="$TARGET_DATABASE_URL" --clean --if-exists --no-owner --no-privileges --jobs=4 "$WORK"

[ "$WORK" != "$DUMP" ] && rm -f "$WORK"
log "Restore complete. Run 'python manage.py migrate --check' and smoke tests next."

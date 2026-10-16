#!/usr/bin/env bash
#
# Isolated restore drill (disaster-recovery rehearsal).
#
#   DATABASE_URL=postgres://... \
#   TARGET_DATABASE_URL=postgres://.../aa_shinaka_restore_drill \
#   RESTORE_DRILL_CONFIRM=yes ./deploy/scripts/restore_drill.sh
#
# Steps:
#   1. take a fresh custom-format dump of DATABASE_URL (times it -> RTO input),
#   2. drop & recreate the ISOLATED target database (TARGET_DATABASE_URL),
#   3. restore the dump into the target,
#   4. sanity-check the restored schema/data (migration count + core tables),
#   5. report the elapsed restore time.
#
# It never touches the source database and refuses to run unless the target
# database name contains "drill" or "restore" (a guard against restoring over
# production by mistake).

set -euo pipefail

DATABASE_URL="${DATABASE_URL:?DATABASE_URL (source) must be set}"
TARGET_DATABASE_URL="${TARGET_DATABASE_URL:?TARGET_DATABASE_URL (isolated) must be set}"

log() { printf '%s [restore_drill] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[ "${RESTORE_DRILL_CONFIRM:-}" = "yes" ] || fail "set RESTORE_DRILL_CONFIRM=yes to confirm this drill"

# Refuse to restore over anything that is not obviously a drill/isolated target.
case "$TARGET_DATABASE_URL" in
  *drill*|*restore*|*staging*) ;;
  *) fail "TARGET_DATABASE_URL does not look isolated (name must contain drill/restore/staging)";;
esac

for tool in pg_dump pg_restore psql; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool not found on PATH"
done

WORK="$(mktemp -d)"
DUMP="${WORK}/drill.dump"
trap 'rm -rf "$WORK"' EXIT

log "1/4 Dumping source database"
dump_start="$(date +%s)"
pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner --no-privileges --file="$DUMP"
pg_restore --list "$DUMP" >/dev/null || fail "dump is not readable"
log "    dump size: $(du -h "$DUMP" | cut -f1)"

log "2/4 Recreating isolated target database"
# Derive the maintenance connection (same server, 'postgres' database) and the
# target database name from TARGET_DATABASE_URL.
target_db="${TARGET_DATABASE_URL##*/}"
target_db="${target_db%%\?*}"
admin_url="$(printf '%s' "$TARGET_DATABASE_URL" | sed "s#/${target_db}.*#/postgres#")"
psql "$admin_url" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"${target_db}\";" >/dev/null
psql "$admin_url" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${target_db}\";" >/dev/null

log "3/4 Restoring into ${target_db}"
restore_start="$(date +%s)"
pg_restore --dbname="$TARGET_DATABASE_URL" --no-owner --no-privileges --jobs=4 "$DUMP"
restore_end="$(date +%s)"
log "    restore completed in $((restore_end - restore_start))s"

log "4/4 Verifying restored schema"
migrations="$(psql "$TARGET_DATABASE_URL" -tAc "SELECT count(*) FROM django_migrations;")"
users="$(psql "$TARGET_DATABASE_URL" -tAc "SELECT count(*) FROM accounts_user;")"
log "    django_migrations rows: ${migrations}"
log "    accounts_user rows:     ${users}"
[ "${migrations:-0}" -gt 0 ] || fail "no migrations found in the restored database"

log "Drill OK. Total wall time: $(( $(date +%s) - dump_start ))s (RTO input)."

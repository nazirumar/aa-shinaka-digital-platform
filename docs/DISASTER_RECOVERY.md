# Disaster Recovery Plan — AA Shinaka Digital Business Platform

**Phase:** 12 · **Owner:** AA Shinaka Operations
**Related:** `docs/PRODUCTION_RUNBOOK.md`, `deploy/scripts/backup.sh`,
`deploy/scripts/restore.sh`.

> No backup is trusted until a restore has been tested. This document defines
> the objectives, the backup design, the restore procedure and the verification
> cadence. Targets are **targets**, not measured results — see the note at the
> end.

---

## 1. Objectives

| Metric | Target | Rationale |
|---|---|---|
| **RPO** (max data loss) | ≤ 24 h | Nightly full dump; WAL archiving would give minutes but is a follow-up. |
| **RTO** (time to restore service) | ≤ 4 h | Restore on a clean host from the latest verified dump + code release. |
| **Backup retention** | 30 days local, 90 days off-site | Enough to cover slow-detected data issues. |

For a **controlled launch** the nightly RPO is acceptable because order volume is
low and every financial movement is also recorded in the payment provider
(Paystack) and in immutable ledger rows. If order volume grows, move to
continuous WAL archiving / a managed Postgres with PITR.

---

## 2. What is backed up

| Asset | Method | Location |
|---|---|---|
| PostgreSQL database | `pg_dump --format=custom`, verified with `pg_restore --list`, optionally encrypted (`age`/`gpg`) | `BACKUP_DIR` + optional rclone off-site remote |
| Uploaded media (`MEDIA_ROOT`) | host/object-storage snapshot (provider-dependent) | provider snapshot bucket |
| Code | Git tags per release (`docs/RELEASE_CHECKLIST.md`) | GitHub |
| Secrets / env | operator password manager (never in the repo) | password manager |
| TLS certificates | certbot/ACM renewal + provider | host / provider |

`deploy/scripts/backup.sh` covers the database leg end-to-end. Media, code and
secrets are host/provider concerns; confirm each during staging.

---

## 3. Backup procedure (database)

```bash
export DATABASE_URL=postgres://USER:PASS@HOST:5432/DB
export BACKUP_DIR=/var/backups/aa-shinaka
export BACKUP_RETENTION_DAYS=30
# Recommended strong extras:
export BACKUP_AGE_RECIPIENT='age1...'      # encrypt at rest
export BACKUP_RCLONE_REMOTE='s3:aa-shinaka-backups'  # off-server copy
./deploy/scripts/backup.sh
```

The script exits non-zero on any failure (missing tool, unreadable archive) so
cron/monitoring can alert. Schedule it with `deploy/systemd/aa-shinaka-backup.timer`
(bare metal) or a cron job / scheduled task (Compose).

---

## 4. Restore procedure (disaster recovery)

> Always restore into an **isolated** database first, verify, then cut over.

1. **Provision** a clean host and a fresh PostgreSQL instance.
2. **Restore the code** at the release tag that matches the dump.
3. **Restore the database** into the isolated instance:

   ```bash
   export TARGET_DATABASE_URL=postgres://USER:PASS@NEWHOST:5432/DB
   export RESTORE_CONFIRM=yes
   # for an encrypted backup also: export BACKUP_AGE_IDENTITY=~/.age/keys.txt
   ./deploy/scripts/restore.sh /var/backups/aa-shinaka/aa_shinaka_<stamp>.dump.age
   ```

4. **Verify** before switching traffic:
   - `uv run python manage.py migrate --check` (schema matches code);
   - `uv run python manage.py check`;
   - row-count spot checks (`orders`, `payment`, `auditlog`);
   - open the admin, a customer order, and a finance report.
5. **Point the app** at the restored database (update `DATABASE_URL`), restart
   web/worker/beat.
6. **Smoke test** with `deploy/scripts/healthcheck.sh` plus a manual login +
   checkout in test mode.
7. **Post-incident:** record the timeline, the dump used, the actual RPO/RTO, and
   any gap, in the incident log.

---

## 5. Failure scenarios

| Scenario | Response |
|---|---|
| DB host lost | Restore latest dump to a new instance (§4). Order/payment data reconciles against Paystack. |
| Corrupt/partial backup | Fall back one retention step; alert. The verify step catches most of these at creation time. |
| Accidental destructive change (e.g. bad migration) | Restore into isolated DB, craft a corrective migration, apply forward — **never** hand-edit committed migrations. |
| Redis lost | Rate-limit counters and Celery queue reset; no durable business data lost (broker only). Restart worker/beat. |
| Media host lost | Restore the provider snapshot; document references are relative. |
| Secret compromise | Rotate `DJANGO_SECRET_KEY` (invalidates sessions/tokens), rotate DB/email/Paystack credentials, redeploy. |

---

## 6. Backup verification schedule

| Frequency | Check |
|---|---|
| Every backup | Script verifies archive readability; monitoring alerts on non-zero exit. |
| Weekly | Operator confirms the off-site copy exists and has a non-zero size. |
| Monthly | **Restore drill** into an isolated DB and run the §4 verification. Record RPO/RTO actually achieved. |
| Before every release | Take and verify a fresh backup immediately before deploy (`deploy/scripts/deploy.sh`). |

> **NOT VERIFIED in this environment:** no live host was provisioned, so no real
> backup has been produced or restored. The scripts and this runbook are the
> deliverable; a restore drill on staging is a launch gate in
> `docs/PRODUCTION_RUNBOOK.md`.

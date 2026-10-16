# Phase 13 Plan — Final Security Hardening & Staging Deployment

**Date:** 2026-10-16  
**Status:** Complete — see `docs/PHASE_13_COMPLETION_REPORT.md`

Phases 1–12 are complete. This phase addresses remaining production-readiness gaps and prepares the application for controlled staging deployment without deploying, enabling live payments, changing DNS, or modifying production data.

## Objectives
1. Staff Multi-Factor Authentication (TOTP) with recovery codes and audit
2. Harden GitHub Actions (enforce mandatory scans)
3. File upload security: size/type validation hardening, quarantine, anti-malware hooks
4. Inventory hardening: explicit warehouse selection and concurrency guarantees
5. Staging deployment preparation (assets, docs, checklists)
6. Payment testing (test mode only)
7. Backup and disaster recovery (scripts + docs + verification)
8. Performance and security testing
9. Final report and status update

## Implementation Strategy
- No rebuild. Extend existing patterns (transactional services, audit logging, rate limiting).
- Avoid introducing heavy dependencies. MFA TOTP will use Python stdlib (hmac, base64, hashlib) with a small fallback implementation rather than new third-party libs.
- Apply least privilege, preserve existing behavior for single-warehouse deployments.
- Every sensitive change must be auditable; privileged operations require capability checks.
- Tests first for new security constraints; run full suite after each major change.

## Outstanding Audit Items to Address
From `docs/PRODUCTION_READINESS_AUDIT.md` (IDs as used there):
- M-3: Multi-warehouse reservations/selection — OPEN (minor). Explicit selection + single-warehouse compat (Step 5).
- M-4: Uploads/malware scanning — OPEN. Quarantine + scan policy (Step 4).
- MFA for privileged staff — not implemented (audit §5). TOTP + recovery codes (Step 2).
- L-1: Analytics `_context_for_page` double-compute — OPEN (performance).
- L-2: Export `active_destinations` naming inconsistency — OPEN (minor).

## Step 1 — Repository Review (Done)
Completed reading: README, final readiness report, audit, runbook, launch checklist, CI, settings, auth, payments, inventory, validators, uploads, tests.

## Step 2 — MFA for Privileged Accounts (Planned)
Target roles: Administrator, Finance staff, Owner (`PRIVILEGED_ROLES`).  
Design:
- `MFADevice` (user, secret_encrypted, is_confirmed, last_used_at, created_at, method=TOTP)
- `MFARecoveryCode` (user, code_hash, used_at, created_at)
- Encryption of TOTP secret using HMAC-based stream cipher keyed by `DJANGO_SECRET_KEY` (dependency-free)
- Enrollment flow: generate QR/code, confirm with valid TOTP, issue recovery codes (one-time display)
- Verification: required for login of privileged users when MFA enabled; or step-up for sensitive actions
- Recovery: verify recovery code, mark used, log audit, allow MFA reset by authorized actor per policy
- Rate limiting on MFA verify/challenges
- Audit: `mfa.enrolled`, `mfa.confirmed`, `mfa.disabled`, `mfa.recovery_used`, `mfa.verified`, `mfa.reset`

Location: `apps/accounts/mfa/` (models, forms, services, utils, urls/views) with URLs under `/accounts/mfa/...` and integration in login view for privileged users.

## Step 3 — GitHub Actions Hardening
Enforce mandatory checks: lint (ruff), format check, `python manage.py check`, migration guard (`makemigrations --check --dry-run`), pytest with postgres, dependency scanning, security tests, static build. Remove `continue-on-error` where appropriate; pin action versions; use `--strict` for `pip-audit` if feasible.

## Step 4 — File Upload Security
Extend existing validators; add quarantine storage (`MEDIA_ROOT/quarantine/`) for uploads that require scanning. Add `ScannedFile` model to track status (PENDING/QUARANTINED/CLEAN/INFECTED/REJECTED), sha256, size, mime/extension, detected_threat, scanned_at. Add authorized release path. Integration points: support attachments, training resources, export documents, analytics uploads. Add safe test fixtures for AV.

## Step 5 — Inventory Hardening
Ensure `place_reservation`/`commit_reservation`/`release_reservation` accept explicit warehouse context where applicable. Add transactions with `select_for_update()` on StockBalance. Add PostgreSQL concurrency tests (multiple threads/processes simulating race). Preserve DEFAULT_WAREHOUSE compatibility.

## Step 6 — Staging Deployment Prep
Update deploy assets (Dockerfile/docker-compose/nginx) as needed. Document env checklist. Add smoke test script. Verify `/media/` deny, TLS headers, reverse proxy trust.

## Step 7 — Payment Testing
Test mode only. Verify init, verify, webhook signature, idempotency, duplicate, expired, failed, refunds/reconciliation with monkeypatching (existing pattern).

## Step 8 — Backup/DR
Add `deploy/scripts/pg_backup.sh` (with encryption hint) and restore guide. Document RPO/RTO, retention. Mark isolated restore test status.

## Step 9 — Testing
Run all tests, E2E A–F, production security, inventory concurrency, MFA, uploads. Record results.

## Step 10 — Final Report
Create `docs/PHASE_13_COMPLETION_REPORT.md` with full evidence. Update `docs/FINAL_PRODUCTION_READINESS_REPORT.md` with new evidence but do NOT change status to "READY FOR CONTROLLED PRODUCTION LAUNCH" until launch gates pass on staging.

Done creating plan. Next: start Step 2 (MFA) and Step 3 (CI hardening) in parallel where possible. Let me begin implementing MFA models and logic.
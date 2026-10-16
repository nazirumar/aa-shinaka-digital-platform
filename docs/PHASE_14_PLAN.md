# Phase 14 Working Plan — Staging Verification & Controlled Production Launch

**Date:** 2026-10-16
**Status:** **COMPLETE** — outcomes in `docs/PHASE_14_STAGING_REPORT.md`; the
go/no-go record is `docs/PRODUCTION_LAUNCH_APPROVAL.md`.
**Constraint reminder:** no rebuild, no React/Next/Vue, no public deploy, no DNS
change, no live Paystack, no production-data migration without explicit approval,
no fabricated verification evidence.

> **Environment reality.** This working environment has **no staging host, no
> domain, no TLS certificate and no server credentials**. Postgres 18 runs
> locally, which makes a subset of checks (migrations, role sync, backup/restore,
> page rendering, local load latency) executable *for real*; everything that
> needs the deployed host stays **NOT VERIFIED** and is listed as a launch gate.

---

## Step 1 — Verify previous phases

- [x] Read `README.md`, readiness report, audit, Phase 13 report, runbook,
      launch content checklist, deploy assets, CI, settings, DB and Celery config.
- [x] Confirmed **0 Critical / 0 open High** findings; Phase 13 delivered and
      committed (`ecbf53d`). No unresolved blocker → deployment preparation may
      continue.

## Step 2 — Staging infrastructure

- [x] Inspect existing deploy assets (`deploy/`).
- [ ] Add an explicit, isolated **staging** profile:
      - `config/settings/staging.py` (production-shaped, hard test-mode Paystack
        guard, never live money).
      - `deploy/.env.staging.example`.
      - `deploy/docker-compose.staging.yml` (separate project name, volumes,
        ports, env file → isolated from production).

## Step 3 — Deployment automation

- [ ] `deploy/scripts/validate_env.sh` — fail-safe environment validation.
- [ ] `deploy/scripts/preflight.sh` — non-destructive pre-deploy gate.
- [ ] `deploy/scripts/smoke_test.sh` — post-deploy HTTP smoke tests.
- [ ] `deploy/scripts/rollback.sh` — documented, safe rollback.
- [ ] `deploy/scripts/verify_host.sh` — host-level security verification.
- [ ] `deploy/scripts/restore_drill.sh` — isolated restore drill.
- [ ] `deploy/scripts/staging_deploy.sh` — orchestrates the above for staging.
- [ ] `manage.py verify_deployment` — environment/database/security verifier.

## Step 4 — Database verification

- [ ] Connectivity, applied migrations, constraints, role groups (10),
      reference-data counts, permissions — via `verify_deployment` (executed
      locally and recorded).

## Steps 5–7 — Public / customer / staff workflow verification

- [ ] Full automated suite (existing coverage) + a new Phase 14 crawl/Access
      matrix where gaps exist; executed locally.
- [ ] Document which workflows are covered by automated tests vs. which need a
      real browser on staging (NOT VERIFIED).

## Step 8 — Paystack test mode

- [ ] Test-mode guard, existing payment contract tests. Real gateway calls are
      **NOT VERIFIED** (no credentials supplied); live payments remain disabled.

## Step 9 — Security verification

- [ ] `manage.py check --deploy`, `verify_deployment`, CI security suite.
      Host controls (TLS/HSTS over the wire, port exposure) **NOT VERIFIED**.

## Step 10 — Backup and restore

- [ ] Real local `pg_dump`/`pg_restore` drill against Postgres 18; record RTO.
      Off-site/encrypted storage and scheduling are host gates (NOT VERIFIED).

## Step 11 — Monitoring

- [ ] Health endpoints, structured logging and the alerting wiring documented;
      test-alert **delivery** is NOT VERIFIED (no provider configured).

## Step 12 — Performance testing

- [ ] Local load run with `deploy/scripts/loadtest.py` against a local server
      (recorded as a local baseline). Staging capacity is NOT VERIFIED.

## Step 13 — Accessibility

- [ ] Template accessibility suite + manual WCAG 2.2 AA checklist; executable
      axe/Lighthouse pass on the host is NOT VERIFIED.

## Step 14 — Business content review

- [ ] `docs/BUSINESS_CONTENT_APPROVAL_CHECKLIST.md` (owner sign-off form).

## Step 15 — Production launch plan

- [ ] `docs/PRODUCTION_LAUNCH_PLAN.md` (DNS/TLS/migration/backup/checklist/
      smoke/rollback/payment activation/incident contacts/owner form).

## Step 16 — Final reports

- [ ] `docs/PHASE_14_STAGING_REPORT.md`.
- [ ] `docs/PRODUCTION_LAUNCH_APPROVAL.md` (PASSED/FAILED/NOT VERIFIED/N-A).

---

## Honesty rules for every artefact in this phase

1. A test is only "passed" if the command actually ran and passed here.
2. Anything host-dependent is **NOT VERIFIED**, never "passed".
3. No invented company content, prices, inventory or achievements.
4. Production deployment requires a **separate explicit approval** — Phase 14
   does not deploy to production, change DNS or enable live Paystack.

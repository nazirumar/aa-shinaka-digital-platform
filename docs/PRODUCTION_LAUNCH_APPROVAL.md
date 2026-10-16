# Production Launch Approval — Go / No-Go Checklist

**Phase:** 14 (staging verification & controlled production launch)
**Date:** 2026-10-16
**Decision owner:** AA Shinaka business owner
**Companion:** `docs/PHASE_14_STAGING_REPORT.md` (evidence), `docs/PRODUCTION_LAUNCH_PLAN.md` (procedure)

Status vocabulary: **PASSED** · **FAILED** · **NOT VERIFIED** · **NOT APPLICABLE**
(with justification). A missing verification is **never** reported as passed.

> **Outcome: NO-GO for production launch at this time.** All code-level gates
> pass; every host-execution gate is **NOT VERIFIED** because no staging host,
> domain or server credentials were available in this environment. Live Paystack
> remains **disabled**. See §C for the exact conditions that flip this to GO.

---

## A. Code, quality and security gates (executed in this environment)

| # | Item | Status | Evidence |
|---|---|---|---|
| A1 | Previous phase (13) complete; no open Critical/High | PASSED | `docs/PHASE_13_COMPLETION_REPORT.md`, `docs/PRODUCTION_READINESS_AUDIT.md` |
| A2 | Full automated test suite | PASSED | `uv run pytest` — 857 passed, 0 failed (local PostgreSQL 18) |
| A3 | Targeted Phase 14 suites (routes, verifier, guards) | PASSED | `tests/test_phase14_routes.py`, `tests/test_verify_deployment.py`, `tests/test_staging_settings.py` (67 tests) |
| A4 | Lint & format | PASSED | `ruff check .` clean; `ruff format --check .` 320 files |
| A5 | Django system check | PASSED | `manage.py check` — no issues |
| A6 | Missing-migration guard | PASSED | `makemigrations --check --dry-run` — no changes |
| A7 | Production `check --deploy` | PASSED | only the deliberate HSTS-preload warning |
| A8 | Static asset build | PASSED | `npm run build:css` → `static/css/app.css` (47,120 bytes) |
| A9 | Living CI pipeline (mandatory, pinned) | PASSED | `.github/workflows/ci.yml` |
| A10 | Staging configuration guard (no live money) | PASSED | live key/mode refused at import; `tests/test_staging_settings.py` |
| A11 | Deployment verifier command | PASSED | `manage.py verify_deployment` (0 FAIL locally) |
| A12 | Deployment scripts fail safely (syntax + validation) | PASSED | `bash -n` clean; `validate_env.sh` rejects placeholders/weak secrets |

## B. Host-execution gates (require a real staging host — NOT VERIFIED)

| # | Item | Status | Notes |
|---|---|---|---|
| B1 | Staging host provisioned (VPS/cloud) | NOT VERIFIED | no host available |
| B2 | Staging stack up (nginx/Gunicorn/Postgres/Redis/Celery worker+beat) | NOT VERIFIED | Compose reference provided |
| B3 | `staging_deploy.sh` executed successfully | NOT VERIFIED | script prepared, not run on a host |
| B4 | TLS terminates correctly; HTTP → HTTPS 301 | NOT VERIFIED | `verify_host.sh` prepared |
| B5 | `/media/` default-deny returns 403/404; `/static/` 200 | NOT VERIFIED | nginx rule present; needs host |
| B6 | Application port not publicly reachable | NOT VERIFIED | needs host |
| B7 | Database on host: connect, migrate, constraints | NOT VERIFIED | verified locally, not on host |
| B8 | Role groups synchronised on host (10) | NOT VERIFIED (local PASSED) | on host |
| B9 | Nigeria locations imported (37 states / 774 LGAs) | NOT VERIFIED | no verified dataset bundled; must use owner-approved source |
| B10 | Public website reviewed on staging (desktop/tablet/mobile) | NOT VERIFIED | local smoke passed; host review pending |
| B11 | Customer workflows exercised on staging (real browser) | NOT VERIFIED | automated coverage passes locally |
| B12 | Staff dashboard + MFA challenged on staging | NOT VERIFIED | automated coverage passes locally |
| B13 | Paystack **test** end-to-end on staging | NOT VERIFIED | no test credentials supplied; live disabled |
| B14 | Security controls verified on the wire | NOT VERIFIED | see `docs/STAGING_TEST_PLAN.md` §6 |
| B15 | Backup produced + restore drill on staging | NOT VERIFIED | local drill PASSED (see §C) |
| B16 | Monitoring wired + safe test alert delivered | NOT VERIFIED | no provider configured |
| B17 | Performance measured on staging | NOT VERIFIED | local baseline only (see report) |
| B18 | WCAG 2.2 AA pass (axe/Lighthouse) on staging | NOT VERIFIED | no browser/host; template suite passes |

## C. Partial results that reduce launch risk (executed, real)

| # | Item | Status | Evidence |
|---|---|---|---|
| C1 | PostgreSQL 18 connectivity + all migrations applied | PASSED (local) | `manage.py verify_deployment` → 0 FAIL; `migrate` applied `accounts_mfa`, `core.0003` |
| C2 | Role groups (10) synchronised | PASSED (local) | `verify_deployment` role_groups PASS |
| C3 | Reference data present but incomplete locally | NOT VERIFIED | 37 states / **450** LGAs locally (partial seed) — must re-import from a verified source |
| C4 | Backup + restore drill (real `pg_dump`/`pg_restore`) | PASSED (local) | dump 920K; restore 14 s; total 25 s; restored DB passed `migrate --check`; 54 migrations / 16 users |
| C5 | Local HTTP smoke (public routes) | PASSED (local) | `smoke_test.sh` all checks passed |
| C6 | Local load baseline | PASSED (local, not capacity) | ~3.9 rps, p50 ~1.2 s, 0% errors on 4 read paths (Windows dev server) |
| C7 | Login rate limiting observed | PASSED (local) | load run produced HTTP 429s on `/accounts/login/` |
| C8 | Malware scanning / quarantine | PASSED (code) | 32-test suite; EICAR rejected + quarantined |

## D. Business content and payments (owner-gated)

| # | Item | Status | Notes |
|---|---|---|---|
| D1 | Business content approved by owner | NOT VERIFIED | `docs/BUSINESS_CONTENT_APPROVAL_CHECKLIST.md` — all rows PENDING |
| D2 | Live Paystack enabled | NOT APPLICABLE | deliberately off; requires separate written approval |
| D3 | DNS changed to production | NOT APPLICABLE | not performed |
| D4 | Production data migrated | NOT APPLICABLE | not performed |

---

## Decision

**NO-GO.** The following conditions must be met before this changes to **GO for
controlled production launch**:

1. Provision an isolated staging host and execute `docs/STAGING_TEST_PLAN.md`
   end to end; record results in `docs/PHASE_14_STAGING_REPORT.md`
   (B1–B14, B16, B17, B18 → PASSED).
2. Produce a backup on staging and complete a restore drill there (B15);
   configure encryption + off-site copy and a backup-failure alert.
3. Import verified Nigeria locations (37 states / 774 LGAs) from an
   owner-approved source (B9/C3).
4. Wire monitoring and deliver a safe test alert (B16).
5. The owner signs `docs/BUSINESS_CONTENT_APPROVAL_CHECKLIST.md` (D1) and
   `docs/PRODUCTION_LAUNCH_PLAN.md` §11.
6. A **separate** explicit approval is given for live Paystack (D2), after the
   §9 payment activation checklist passes.

Only then may `docs/FINAL_PRODUCTION_READINESS_REPORT.md` move from
**READY FOR STAGING** to **READY FOR CONTROLLED PRODUCTION LAUNCH**.

### Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Business owner | | NO-GO (pending staging execution) | |
| Operations | | | |
| Finance | | | |

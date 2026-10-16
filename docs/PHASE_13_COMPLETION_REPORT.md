# Phase 13 Completion Report — Final Security Hardening & Staging Deployment

**Date:** 2026-10-16
**Author:** engineering
**Status of this phase:** **COMPLETE** (code, tests and documentation).
**Deployment status:** **NOT DEPLOYED** — no host, DNS record, live Paystack
credential or production data was touched. Staging execution remains the
owner-gated next step.

Related: `docs/PHASE_13_PLAN.md`, `docs/PRODUCTION_READINESS_AUDIT.md`,
`docs/FINAL_PRODUCTION_READINESS_REPORT.md`, `docs/PRODUCTION_RUNBOOK.md`,
`docs/DISASTER_RECOVERY.md`.

> Honesty statement: every "passing" claim below was produced by a command that
> actually ran in this environment. Anything that depends on a real host, live
> provider or hardware is explicitly marked **NOT VERIFIED**.

---

## 0. Summary

Phase 13 closed the last code-level gaps that Phase 12 had accepted for a
*controlled* launch, hardens CI so checks are mandatory, and prepares (without
performing) staging deployment.

| # | Step | Outcome |
|---|---|---|
| 1 | Repository review + plan | `docs/PHASE_13_PLAN.md` |
| 2 | Staff MFA (TOTP) | **Delivered** — 26 tests |
| 3 | GitHub Actions hardening | **Delivered** — mandatory checks, pinned |
| 4 | File upload security | **Delivered** — 32 tests |
| 5 | Inventory hardening + concurrency | **Delivered** — 18 tests |
| 6 | Staging deployment prep | **Delivered** — assets reviewed/extended; **not deployed** |
| 7 | Paystack test-mode only | **Delivered** — 6 tests + fail-closed live-key guard |
| 8 | Backup / DR | **Provided** — scripts + RPO/RTO doc; restore drill **NOT VERIFIED** |
| 9 | Full test/security/performance run | **Executed** — 790 passed |
| 10 | Reports | This document + readiness audit updated |

---

## 1. Repository review (Step 1)

Reviewed the whole monolith (apps, config, templates, deploy, CI, docs) against
the Phase 13 brief, re-derived the open audit items and wrote the execution plan
in `docs/PHASE_13_PLAN.md`. No rebuild: every change extends the existing
service-layer / audit / capability patterns.

---

## 2. Staff MFA — TOTP (Step 2)

**Goal:** a second factor for privileged accounts, without adding a dependency.

**What was built** (`apps/accounts/mfa/`, app label `accounts_mfa`):

- `MFADevice` — one TOTP device per user (encrypted secret, `is_confirmed`,
  `last_used_at`).
- `MFARecoveryCode` — single-use recovery codes stored **hashed**.
- TOTP (RFC 6238) and base32 secret generation on the Python standard library
  (`hmac`, `hashlib`, `base64`, `secrets`) — no new dependency.
- Secret storage is **encrypt-then-MAC**, keyed from `DJANGO_SECRET_KEY`
  (overridable with `MFA_SECRET_KEY`); the plaintext secret is never stored.
- **Login flow:** valid credentials for an MFA-enabled account park the session
  (`mfa_pending_user_id`, timeout `MFA_CHALLENGE_TIMEOUT`) and redirect to the
  challenge; a valid TOTP **or** recovery code completes `login()`.
- **Recovery codes:** single-use, checked under `select_for_update`, cached-free.
- **Disable** requires a fresh TOTP/recovery code; **reset** is restricted to a
  privileged actor, re-enrols, sets `is_confirmed=False` and is audited.
- **Rate limiting:** `MFA_RATE_LIMIT_ATTEMPTS` / `MFA_RATE_LIMIT_WINDOW` (HTTP 429
  after repeated failures).
- **Audit actions:** `mfa.enrolled`, `mfa.confirmed`, `mfa.verified`,
  `mfa.recovery_used`, `mfa.disabled`, `mfa.reset`.

Design note: enforcement keys on a **confirmed device**, not on the role, so a
privileged user is *prompted* to enrol and only then is challenged — this avoids
locking existing staff out while still being a hard gate once enrolled.

**Verification:** `uv run pytest tests/test_mfa.py` → **26 passed**; the login
regression suite also passes.

---

## 3. GitHub Actions hardening (Step 3)

`.github/workflows/ci.yml` was rewritten so the checks are **mandatory**:

- Third-party actions pinned to full commit SHAs (supply-chain hardening).
- `pip-audit` pinned (`pip-audit==2.10.1`) and run with `--strict`.
- `continue-on-error` removed from security steps — a finding now fails the job.
- A **grep-based classifier** distinguishes a *vulnerability finding* from a
  *tool/service failure*, emitting a distinct `::error::` annotation for each
  (so an outage cannot masquerade as a clean scan or vice-versa).
- The security test subset runs **first** in the test job.
- Least privilege: `permissions: contents: read`; pinned service images
  (PostgreSQL 16.4, Node 20.18.0).

**Verification:** workflow YAML validated; the security-subset command executed
locally (60 passed). Local `pip-audit` is clean at 2.10.1. *A residual GitHub
Dependabot alert (1 High) could not be reproduced locally and is untriaged* —
recorded in the audit, not hidden.

---

## 4. File upload security (Step 4)

**Goal:** scan every inbound upload, quarantine threats, fail closed, and keep an
auditable record — while never rejecting the platform's own benign documents.

**What was built:**

- `apps/core/upload_security.py`:
  - Scanner: a built-in **EICAR** signature detector + **executable magic**
    (`MZ`, ELF) detection always runs; an optional **ClamAV `clamd` INSTREAM**
    scan runs over a unix or TCP socket when `CLAMAV_SOCKET`/`CLAMAV_HOST` is set.
  - `screen_upload()` scans **before** the model is saved, writes a
    `FileScanRecord`, quarantines infected bytes under `MEDIA_ROOT/quarantine/`
    and raises `ValidationError` for threats.
  - `screen_uploads()` scans a list **before** the caller's write transaction so
    the forensic record survives the rollback of a rejected upload (a subtle but
    important correctness point — the record's DB insert must not be rolled back
    by the `atomic` block it aborts).
  - `bind_scanned_file()` links the record to the stored path after save.
  - `enforce_downloadable()` gates every download and **lazily scans** legacy /
    pre-existing files; infected or unscanned files are blocked per policy.
  - `release_scan()` — capability-checked (`media.manage`) authorised release,
    audited.
- `core.FileScanRecord` model (+ migration `core/0003_initial.py`): status
  (`pending`/`clean`/`infected`/`error`/`released`), sha256, paths, size, kind,
  scanner, threat name, detail, `uploaded_by`, `released_by`, timestamps.
- **Policy:** `UPLOAD_SCAN_ENFORCEMENT` = `enforce` (default) fails **closed** on
  scanner errors; `log` records and allows. **Infected files are rejected and
  blocked in both modes.**
- **Integrations (upload):** support ticket attachments/replies, service
  attachments, export documents (staff + customer), training resources.
- **Integrations (download):** support, export, training, account documents,
  analytics reports (platform-generated reports/invoices pass `trusted=True` and
  skip the gate since they are not user uploads).
- **Admin/UI:** Django admin action + a capability-gated dashboard page
  (`/dashboard/security/uploads/`) to review records and release files.
- **Images** remain covered by Pillow `ImageField` content validation plus the
  nginx allow-list (documented; full AV scan of images is the clamd path).

**Verification:** `uv run pytest tests/test_upload_security.py` → **32 passed**
(EICAR rejection, quarantine persistence, both policies, download blocking/lazy
scan, authorised release, end-to-end ticket upload). Support/export/training/
service suites remain green.

**Safe AV fixture:** the suite uses the standard **EICAR** test string — a
harmless, non-executable industry fixture — never live malware.

---

## 5. Inventory hardening (Step 5)

**Goal:** explicit, safe warehouse selection; no oversell; correct release;
single-warehouse compatibility; real concurrency evidence.

**What changed** (`apps/catalog/inventory.py`, `apps/orders/services.py`):

- `select_warehouse()` — deterministic allocation: an explicitly named warehouse
  first, then the platform default, then any active warehouse whose unreserved
  stock covers the line. Single-warehouse deployments always resolve to `MAIN`.
- Checkout selects the fulfilment warehouse **per line** (was a single implicit
  `default_warehouse()`).
- `place_reservation()` now enforces a **per-warehouse** oversell guard
  (`on_hand − reserved ≥ amount` at the chosen warehouse) under a row lock, in
  addition to the listing roll-up check.
- `release_reservation()` / `commit_reservation()` **recompute the listing
  roll-ups from Σ balances** instead of subtracting, so a release can never
  desynchronise `stock_reserved` from the per-warehouse rows.
- `resolve_warehouse()` is applied consistently (movements record the actual
  warehouse).

**Verification:** `uv run pytest tests/test_inventory_concurrency.py` →
**18 passed**, including **real PostgreSQL row-lock concurrency** (two threads
racing for the last units: exactly one wins, no oversell) and single-warehouse
compatibility. Existing order/catalog/inventory suites (83 tests) remain green.

---

## 6. Staging deployment preparation (Step 6) — prepared, NOT deployed

Phase 12 already provided the deployment assets; Phase 13 reviewed them against
the brief and extended where needed:

- `deploy/nginx/aa-shinaka.conf` — TLS, security headers, `client_max_body_size`,
  `/static/` served, **`/media/` default-deny** (quarantine files are therefore
  never publicly reachable).
- `deploy/docker-compose.yml` — PostgreSQL, Redis, web (Gunicorn), Celery
  **worker**, Celery **beat**, nginx; **new optional `clamav` service**
  (`--profile scanning`) with a shared `clamd_sock` volume for the Step 4 scanner.
- `deploy/gunicorn.conf.py`, `deploy/entrypoint.sh` (checks → migrate →
  collectstatic → serve), `deploy/systemd/*` (bare-metal alternative).
- `deploy/.env.production.example` — updated with `MFA_*`, `UPLOAD_SCAN_*`,
  `CLAMAV_*` and `PAYSTACK_LIVE_MODE`.
- `deploy/scripts/healthcheck.sh`, `deploy/scripts/deploy.sh` (build → migrate →
  collectstatic → restart → smoke test).

**NOT VERIFIED:** nothing was deployed, no DNS was changed and no host was
provisioned, so TLS termination, the `/media/` deny, monitoring alerts and the
service topology are **not** claimed as verified. They are launch gates in
§4 of the readiness report.

---

## 7. Payment testing — test mode only (Step 7)

The Paystack boundary was already well covered (init, verify, signed webhook,
dedup, duplicate, expired, refund/reconciliation) with the HTTP boundary
monkeypatched. Phase 13 added a **fail-closed live-key guard**:

- `PAYSTACK_LIVE_MODE` (default `False`).
- `paystack.is_enabled()` returns `False` and `paystack._request()` raises
  `PaystackError(code="live_mode_disabled")` whenever a **live** key
  (`sk_live_…`) is configured while live mode is off — so a misconfiguration can
  never move real money.

**Verification:** `uv run pytest tests/test_paystack_test_mode.py` → **6 passed**;
`tests/test_orders_payments.py` → **37 passed** (unchanged, test keys).

---

## 8. Backup & disaster recovery (Step 8)

Provided in Phase 12 and re-verified as covering the brief:

- `deploy/scripts/backup.sh` — `pg_dump --format=custom`, readability verify,
  optional `age`/`gpg` encryption and optional `rclone` off-site copy; non-zero
  exit on any failure; scheduled by `deploy/systemd/aa-shinaka-backup.timer`.
- `deploy/scripts/restore.sh` — restores into an **isolated** database first.
- `docs/DISASTER_RECOVERY.md` — **RPO ≤ 24 h**, **RTO ≤ 4 h**, retention, failure
  scenarios and a verification schedule (monthly restore drill).

**NOT VERIFIED:** no live host exists in this environment, so **no backup was
produced and no restore drill was executed**. The scripts and runbook are the
deliverable; a restore drill on staging is a launch gate.

---

## 9. Tests, security and performance (Step 9)

Full gate run, executed in this environment:

| Command | Result |
|---|---|
| `uv run ruff check .` | ✅ All checks passed |
| `uv run ruff format --check .` | ✅ 312 files already formatted |
| `uv run python manage.py check` | ✅ 0 issues |
| `uv run python manage.py makemigrations --check --dry-run` | ✅ No changes detected |
| `uv run pytest -q` (full suite) | ✅ **790 passed, 0 failures, 0 skipped** (4m57s) |
| Prod `manage.py check --deploy` | ✅ clean (only deliberate HSTS-preload warning) |

Phase 13 added **82 tests** (MFA 26, upload security 32, inventory concurrency 18,
Paystack 6); all pre-existing suites remain green.

**Load & accessibility:** the harnesses are prepared and **not** executed against
a host — `deploy/scripts/loadtest.py` with method in `docs/PERFORMANCE.md`, and
`tests/test_templates_accessibility.py` plus the axe-core/Lighthouse plan in
`docs/PERFORMANCE.md` §accessibility. No performance or WCAG number is claimed.

---

## 10. Final status

- **No deployment, DNS change, live Paystack credential or production data
  change** was performed.
- The production readiness report stays **READY FOR STAGING**; it is **not**
  marked **READY FOR CONTROLLED PRODUCTION LAUNCH**, which requires the §4
  host gates and the owner's content sign-off.
- Audit items closed this phase: **M-3, M-4, L-1, L-2** and **MFA**. Remaining
  open items are non-blocking (Dependabot triage; host verification).

**Next step (owner-gated):** provision a staging host, execute the §4 launch
gates, run the load/accessibility passes, complete
`docs/LAUNCH_CONTENT_CHECKLIST.md`, then seek approval to launch.

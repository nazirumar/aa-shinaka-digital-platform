# Phase 14 Staging Report — Staging Verification & Controlled Production Launch

**Date:** 2026-10-16
**Author:** engineering
**Status of this phase:** **COMPLETE** (configuration, automation, tests and
documentation).
**Deployment status:** **NOT DEPLOYED** — no staging host, domain, TLS
certificate, server credential, live Paystack credential or production data was
available or touched.

Related: `docs/PHASE_14_PLAN.md`, `docs/STAGING_TEST_PLAN.md`,
`docs/PRODUCTION_LAUNCH_PLAN.md`, `docs/PRODUCTION_LAUNCH_APPROVAL.md`,
`docs/BUSINESS_CONTENT_APPROVAL_CHECKLIST.md`,
`docs/FINAL_PRODUCTION_READINESS_REPORT.md`, `deploy/README.md`.

> **Honesty statement.** Every "PASSED" claim below was produced by a command
> that actually ran in this environment, and the environment is named on each
> row. Anything that needs a deployed host, a live gateway or a browser is
> **NOT VERIFIED** and is carried as an explicit launch gate. Nothing here is
> reported as passing on the strength of a script existing.

---

## 0. Environment reality

| Capability | Available here? |
|---|---|
| PostgreSQL 18.6 (local service) | **Yes** — real DB checks, migrations, backup/restore drill |
| Python 3.12 (uv), Node 24, Tailwind | **Yes** |
| Staging host / domain / TLS / credentials | **No** |
| Redis / Celery broker | **No** (locmem cache; eager Celery) |
| Desktop browser (axe/Lighthouse) | **No** (not connected) |
| Paystack test credentials | **No** |

Consequently, this phase delivers everything that does not require a host, proves
the host-independent parts for real, and marks the rest **NOT VERIFIED** with the
exact procedure required to close each one (`docs/STAGING_TEST_PLAN.md`).

---

## 1. Step 1 — Verify previous phases

**Outcome: PASSED.**

- Read `README.md`, `docs/FINAL_PRODUCTION_READINESS_REPORT.md`,
  `docs/PRODUCTION_READINESS_AUDIT.md`, `docs/PHASE_13_COMPLETION_REPORT.md`,
  `docs/PRODUCTION_RUNBOOK.md`, `docs/LAUNCH_CONTENT_CHECKLIST.md`, the `deploy/`
  assets, `.github/workflows/ci.yml`, the settings modules and the database/Celery
  configuration.
- **0 Critical, 0 open High** findings. Phase 13 is delivered and committed
  (`ecbf53d`). No unresolved blocker, so deployment preparation may continue.
- `git status` clean at the start of the phase.

No critical/high issue required stopping and reporting.

## 2. Step 2 — Staging infrastructure

**Outcome: DELIVERED (not deployed).**

| Artefact | Purpose |
|---|---|
| `config/settings/staging.py` | Production-shaped settings; **fails at import** on a live Paystack key or `PAYSTACK_LIVE_MODE=True`; short HSTS so a broken TLS setup is rollback-safe. |
| `config/settings/_guards.py` | Pure, unit-tested guard functions shared by settings and the verifier. |
| `deploy/.env.staging.example` | Full staging environment template (test keys only). |
| `deploy/docker-compose.staging.yml` | Isolation: distinct project name `aa-shinaka-staging`, `.env.staging`, ports 8080/8443 (co-hostable with production). |

The service topology is the existing reference (nginx + Gunicorn + PostgreSQL +
Redis + Celery worker + beat) with private-media default-deny and an optional
ClamAV profile. Nothing assumes a provider, domain or credential: all come from
the environment.

**Proven here:** `config.settings.staging` imports cleanly with test keys and
raises `ImproperlyConfigured` with an `sk_live_…` key (both exercised directly).

## 3. Step 3 — Deployment automation

**Outcome: DELIVERED; scripts syntax-checked and the validator exercised.**

| Script | Role |
|---|---|
| `deploy/scripts/validate_env.sh` | Fail-safe env validation (placeholders, weak secret, wildcard host, non-HTTPS origins, console email, non-Redis cache, live Paystack). |
| `deploy/scripts/preflight.sh` | Non-destructive gate: validate env → `check --deploy` → missing-migration guard → `migrate --check` → `verify_deployment`. |
| `deploy/scripts/smoke_test.sh` | Post-deploy HTTP smoke test (incl. media deny + DB-ok probe). |
| `deploy/scripts/verify_host.sh` | Host security verification (TLS chain, redirect, headers, media deny, port exposure). |
| `deploy/scripts/staging_deploy.sh` | Staging orchestrator (preflight → build → backup → migrate → collectstatic → restart → smoke → host verify). |
| `deploy/scripts/rollback.sh` | Safe code rollback; deliberately does **not** reverse migrations. |
| `deploy/scripts/restore_drill.sh` | Isolated restore rehearsal with an isolation guard on the target DB name. |
| `manage.py verify_deployment` | Environment/DB/security verifier (see §4). |

**Proven here:**
- All shell scripts pass `bash -n` (Git Bash).
- `validate_env.sh` **fails** on the staging template (empty secret, placeholders
  such as `EXAMPLE_DOMAIN`, `CHANGE_ME`) and **passes** on a synthetic valid file.
- `smoke_test.sh` passes against a live local server (see §5).
- `restore_drill.sh` executes a real drill (see §10).

Every script is non-destructive by default: no `migrate` without an explicit
deploy step, no DNS action, no service action without confirmation.

## 4. Step 4 — Database verification

**Outcome: PASSED (local PostgreSQL 18), NOT VERIFIED on a staging host.**

`manage.py verify_deployment` (new, tested) produced **0 FAIL** locally:

| Check | Result |
|---|---|
| PostgreSQL connection | PASS — `PostgreSQL 18.6 on x86_64-windows` |
| Database engine | PASS — `postgresql` |
| All migrations applied | PASS — up to date (applied `accounts_mfa.0001`, `core.0003`) |
| Role groups synchronised | PASS — 10 present |
| Cache read/write | PASS — locmem |
| MEDIA_ROOT writable | PASS |
| Quarantine directory | PASS |
| SecurityMiddleware | PASS |
| SECRET_KEY strong | PASS |
| ALLOWED_HOSTS explicit | PASS |

**Finding (carried):** the local reference data is **37 states / 450 LGAs** —
partial. The verifier reports this as **WARN**; importing the full 37/774 set from
a **verified source** is a host gate (B9). No dataset is bundled and none was
fabricated.

Management commands (`sync_roles`, `import_nigeria_locations`, `seed_data`) are
present and covered by the suite. `makemigrations --check` reports no changes.

## 5. Step 5 — Public website testing

**Outcome: PASSED (local HTTP smoke), NOT VERIFIED on a staging host.**

Live crawl against the local server (`smoke_test.sh`, all checks passed) and a
direct route crawl:

```
/                200      /about/          200      /contact/        200
/services/       200      /news/           200      /faqs/           200
/shop/           200      /training/       200      /cart/           200
/accounts/register/  200  /accounts/password-reset/ 200
/robots.txt      200      /sitemap.xml     200      /healthz/        200
/states/         200      /media/quarantine/… 404 (deny)
```

`/accounts/login/` returned **429** during the load run — that is the login rate
limiter working, not an error (see §9, §12).

A consolidated automated crawl (`tests/test_phase14_routes.py`) asserts the key
public pages return 200 and that no listed route produces a server error.

## 6. Step 6 — Customer workflow testing

**Outcome: PASSED via the automated suite (local); live staging NOT VERIFIED.**

Registration, email verification, login/logout, password reset, the account
dashboard, profile, address book, cart, checkout, orders, payments, service
requests, export enquiries, training enrolments, support tickets and
notifications are covered by the existing per-phase suites (`test_auth_flow`,
`test_registration`, `test_customer_account`, `test_portal`, `test_orders_*`,
`test_services`, `test_export`, `test_training`, `test_support`,
`test_notifications`, `test_e2e`). Object-level ownership boundaries are asserted
(a customer cannot open another customer's order/document).

The live browser walkthrough in `docs/STAGING_TEST_PLAN.md` §3 remains to be run
on the host.

## 7. Step 7 — Staff dashboard testing

**Outcome: PASSED via the automated suite (local); live staging NOT VERIFIED.**

Role-capability enforcement, staff management, catalogue/inventory, order &
payment management, service/export/training/support handling, analytics and the
audit log are covered by the suite (`test_permissions`,
`test_staff_management`, `test_catalog_*`, `test_inventory_*`,
`test_orders_dashboard`, `test_analytics`, `test_audit`, `test_cms_dashboard`,
`test_mfa`). `tests/test_phase14_routes.py` additionally crawls every staff entry
point as the owner and asserts no server errors and no login redirects.

MFA for privileged accounts is enforced in code and tested (26-test suite); the
live TOTP challenge on the host is part of `docs/STAGING_TEST_PLAN.md` §4.

## 8. Step 8 — Paystack test mode

**Outcome: guard PASSED; live gateway NOT VERIFIED.**

- Staging **refuses** a live key or live mode at import (proven directly).
- The runtime payment path still fails closed on a live key while live mode is
  off (`apps/orders/paystack.py` + `tests/test_paystack_test_mode.py`).
- The payment contract suite (`tests/test_orders_payments.py`, 37 tests) covers
  success, failure, cancellation, duplicate webhooks, bad signatures, amount
  mismatch and late-settlement review — against a stubbed provider.
- **No real Paystack test transaction was made** — no credentials were supplied.
  This is a launch gate (B13). Live payments remain **disabled**.

## 9. Step 9 — Security verification

**Outcome: code-level checks PASSED; host controls NOT VERIFIED.**

| Check | Result |
|---|---|
| `manage.py check --deploy` (prod settings) | PASS — only the deliberate HSTS-preload warning |
| `manage.py verify_deployment` security checks | PASS (local) |
| Secure/HttpOnly cookies, SSL redirect, HSTS, nosniff, SecurityMiddleware | PASS in prod/staging settings |
| Login/form rate limiting | PASS — observed HTTP 429 in the load run |
| MFA for privileged staff | PASS — 26 tests |
| Upload malware scanning / quarantine | PASS — 32 tests (EICAR rejected + quarantined) |
| `validate_env.sh` rejects weak/placeholder secrets | PASS |

Host controls (TLS chain, redirect over the wire, `/media/` deny, non-public app
port) require the host and are **NOT VERIFIED**; `verify_host.sh` is prepared.

**Hygiene finding:** the repository root `.env` contains `DJANGO_SECURE_SSL_REDIRECT=False`
(a development value). Real environment variables win over `.env`
(`environ.Env.read_env` uses `setdefault`), so a correctly-configured host is
unaffected — but a root `.env` **must not exist on the host**. Documented as a
launch gate in `docs/PRODUCTION_LAUNCH_PLAN.md` §3.

## 10. Step 10 — Backup and restore

**Outcome: PASSED for the local drill; off-site/encrypted/scheduled on the host NOT VERIFIED.**

A **real** backup + restore drill was executed with PostgreSQL 18:

| Measurement | Value |
|---|---|
| Source | local `aa_shinaka` |
| Dump format / size | custom-format (`pg_dump -Fc`) / **920 KB** |
| Restore target | isolated `aa_shinaka_drill` |
| Restore time | **14 s** |
| Total drill wall time | **25 s** (RTO input) |
| Restored rows | 54 `django_migrations`, 16 `accounts_user` |
| Integrity | restored DB passed `manage.py migrate --check` (exit 0) |

The drill database was dropped afterwards. Scripts: `backup.sh` (verify +
optional age/gpg encryption + off-site copy + retention), `restore.sh`,
`restore_drill.sh`. Off-site storage, encryption keys and the nightly timer are
host configuration.

## 11. Step 11 — Monitoring

**Outcome: endpoints/logging ready; test-alert delivery NOT VERIFIED.**

- `/healthz/` reports database status (200 ok / 503) and is covered by
  `healthcheck.sh` for external probes.
- Structured JSON logging and observability helpers exist
  (`config/observability.py`); `docs/MONITORING.md` documents the signals.
- **No monitor/provider is configured here**, so a delivered test alert is a
  launch gate (B16). The procedure (including a forced DB-outage 503 test and a
  backup-failure alert) is in `docs/STAGING_TEST_PLAN.md` §8.

## 12. Step 12 — Performance testing

**Outcome: local baseline captured; staging capacity NOT VERIFIED.**

`deploy/scripts/loadtest.py` against the local **development** server
(DEBUG=True, single process, no caching/proxy) — a functional baseline, **not**
capacity:

| Run | Requests | Throughput | p50 | p95 | Max | Errors |
|---|---:|---:|---:|---:|---:|---:|
| 20 s, 5 workers, 4 read paths | 83 | 3.9 rps | 1.22 s | 2.40 s | 3.03 s | 0.0% |
| 20 s, 5 workers, +login | 97 | 4.7 rps | 0.94 s | 2.17 s | 3.44 s | 0.0% (8× 429 rate-limit) |

A real staging run (120 s, concurrency 20, authenticated checkout) and a
documented capacity limit are required (`docs/STAGING_TEST_PLAN.md` §9). No claim
is made about production capacity on hardware this has not run against.

## 13. Step 13 — Accessibility

**Outcome: automated template checks PASSED; axe/Lighthouse NOT VERIFIED.**

- `tests/test_templates_accessibility.py` passes (lang, viewport, skip link,
  form labels, CSRF, generic error `role="alert"`, dashboard landmarks).
- No desktop browser is connected, so an axe-core/Lighthouse run could not be
  executed. The exact commands and the manual WCAG 2.2 AA checklist are in
  `docs/STAGING_TEST_PLAN.md` §10.

## 14. Step 14 — Business content review

**Outcome: DELIVERED (owner sign-off PENDING).**

`docs/BUSINESS_CONTENT_APPROVAL_CHECKLIST.md` is a sign-off form covering company
identity/legal, legal pages, catalogue & pricing, warehousing/shipping, service
divisions, export, training, payments, communications, locations and coverage.
**All rows are PENDING** — no business content was invented, and no inventory or
customer records were fabricated. This is a launch gate (D1).

## 15. Step 15 — Production launch plan

**Outcome: DELIVERED.**

`docs/PRODUCTION_LAUNCH_PLAN.md` specifies domain/DNS, TLS, production env,
database migration, backup-before-launch, the deployment checklist, smoke tests,
rollback, the separate payment-activation checklist, incident contacts and the
owner approval form. Nothing in it was executed against production.

## 16. Step 16 — Final reports

**Outcome: DELIVERED.**

- This report.
- `docs/PRODUCTION_LAUNCH_APPROVAL.md` — the go/no-go decision record
  (**NO-GO**, pending host execution).

---

## Consolidated status

| Step | Item | Status |
|---|---|---|
| 1 | Previous-phase verification | **PASSED** |
| 2 | Staging infrastructure (config/assets) | **DELIVERED** (deploy NOT VERIFIED) |
| 3 | Deployment automation | **DELIVERED** (host run NOT VERIFIED) |
| 4 | Database verification | **PASSED** (local) / host NOT VERIFIED |
| 5 | Public website | **PASSED** (local smoke) / host NOT VERIFIED |
| 6 | Customer workflows | **PASSED** (automated) / live NOT VERIFIED |
| 7 | Staff dashboard | **PASSED** (automated) / live NOT VERIFIED |
| 8 | Paystack test mode | **PASSED** (guard/tests) / live gateway NOT VERIFIED |
| 9 | Security verification | **PASSED** (code) / host controls NOT VERIFIED |
| 10 | Backup & restore | **PASSED** (local drill) / host + off-site NOT VERIFIED |
| 11 | Monitoring | **PARTIAL** / test alert NOT VERIFIED |
| 12 | Performance | **LOCAL BASELINE** / staging capacity NOT VERIFIED |
| 13 | Accessibility | **PASSED** (template suite) / axe NOT VERIFIED |
| 14 | Business content | **DELIVERED** / owner sign-off PENDING |
| 15 | Production launch plan | **DELIVERED** |
| 16 | Final reports | **DELIVERED** |

### Automated gates executed (results)

| Command | Result |
|---|---|
| `uv run pytest` | **857 passed, 0 failed** (local PostgreSQL 18) |
| `uv run ruff check .` | Clean |
| `uv run ruff format --check .` | 320 files formatted |
| `uv run python manage.py check` | No issues |
| `uv run python manage.py makemigrations --check --dry-run` | No changes detected |
| `uv run python manage.py check --deploy --fail-level ERROR` | Only the deliberate HSTS-preload warning |
| `npm run build:css` | `static/css/app.css` (47,120 bytes) |
| `manage.py verify_deployment` | 0 FAIL locally |
| `bash -n` on all deploy scripts | Clean |
| `restore_drill.sh` | Real drill OK (25 s) |

## What is explicitly NOT verified (launch gates)

1. Staging host provisioned and stack running.
2. Staging deploy executed; TLS; HTTP→HTTPS; HSTS on the wire; `/media/` deny on
   the host; app port not public.
3. Database migrated on the host; **Nigeria locations imported (37 states /
   774 LGAs)** from a verified source.
4. Customer and staff workflows exercised in a real browser on the host (incl.
   the live MFA TOTP challenge).
5. A real Paystack **test** end-to-end payment; webhook from the real provider.
6. Backup produced on the host, encryption + off-site copy, restore drill there,
   and a backup-failure alert.
7. Monitoring wired and a safe test alert delivered.
8. Staging performance run and a documented capacity limit.
9. axe/Lighthouse WCAG 2.2 AA pass.
10. Owner approval of business content; a **separate** approval for live Paystack.

## Conclusion

Phase 14 is complete as far as this environment allows. Every host-independent
gate passed for real (857 tests, lint/format/check/migrations, prod
`check --deploy`, a real backup/restore drill, a live local smoke test and a local
load baseline). The platform remains **READY FOR STAGING** — it is **not** ready
to be quoted as production-launch ready until the gates above are executed on a
staging host and the owner signs off. **No production deployment, DNS change,
live Paystack activation or production-data migration was performed.** Per the
brief, work stops here pending approval.

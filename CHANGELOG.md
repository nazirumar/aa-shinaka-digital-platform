# Changelog

All notable changes to the AA Shinaka Digital Business Platform.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] — Expanded development seed data (every module)

### Added

- **Always-on reference data for the previously-empty modules.** A plain
  `seed_data` run now also seeds catalogue `ProductVariant`s, three analytics
  `ScheduledReport`s (inventory stock, low-stock and service requests) and a
  `NotificationPreference` row per seeded user. All are idempotent and go
  through the service layer.
- **`--with-demo-records` now covers every domain.** The flag previously created
  only orders, service requests, enrolments and export enquiries; it now also
  exercises the full transactional workflows: CMS contact enquiries; support
  tickets with staff replies and resolution; in-app notifications; the complete
  consultancy, farm-project, marketing and storage service lifecycles plus a
  service quotation; training attendance → assessment → lesson completion →
  certificate; the export quotation → order → verified payment → compliance →
  shipment → delivery chain; order settlement, status transitions and shipment;
  and bulk quotation requests. Each section is isolated, so one failing workflow
  is recorded as a note and never aborts the run.
- **`tests/test_seed_data.py`** — new tests assert a plain run creates the new
  reference data (and stays idempotent) and that a `--with-demo-records` run
  populates every module, reports no silently-skipped workflow, and re-runs
  without duplicating records.

### Changed

- **`seed_data` help text and run report** now describe the full module coverage.
  The command remains development-only (`DEBUG`) and idempotent.

## [Unreleased] — Fix: invalid default cache URL

### Fixed

- **The app crashed at import whenever `CACHE_URL` was not set.** The settings
  default was `locmem://`, but django-environ 0.14 only accepts the
  `locmemcache://` scheme and raises
  `ImproperlyConfigured: Invalid cache schema locmem` for `locmem://`. Every
  environment that did not set `CACHE_URL` — a fresh clone using `.env.example`,
  a container started without that variable, CI — died during Django settings
  import. `config/settings/base.py` now defaults to `locmemcache://`;
  `.env.example` and `.github/workflows/ci.yml` use the same valid scheme.
  A focused regression test (`tests/test_settings_defaults.py`) validates the
  cache URL in `base.py`, `.env.example` and `ci.yml` against django-environ.

## [Unreleased] — Local Docker development stack

### Added

- **Root-level `docker-compose.yml`** so `docker compose config` and
  `docker compose up` work from the repository root (previously Compose had to be
  pointed at `deploy/docker-compose.yml` with `-f`). Runs the development shape —
  Django `runserver`, PostgreSQL, Redis, a Celery worker and Celery beat — with
  persistent `pgdata`/`redisdata` volumes, health checks, an explicit `migrate`
  gate and Paystack forced to test mode. Reuses `deploy/Dockerfile` and does not
  touch any `deploy/` production file.
- **`docs/LOCAL_DOCKER_DEVELOPMENT.md`** — how the root dev stack and the
  production-shaped `deploy/` local-test stack differ, and the exact commands for
  each.

## [Unreleased] — Pre-hosting deployment readiness

### Added

- **Local-test Compose stack** (`deploy/docker-compose.local.yml`,
  `deploy/.env.local.example`, `deploy/nginx/local.conf`,
  `config/settings/local.py`): runs the whole production shape (nginx, Gunicorn,
  PostgreSQL, Redis, Celery worker + beat) on a laptop plus a **Mailpit** capture
  inbox at `http://localhost:8025`, site on `http://localhost:8080`.
  `config.settings.local` inherits production and relaxes *only* the plain-HTTP
  controls (non-`Secure` cookies, no SSL redirect, `http://` CSRF origin);
  `DEBUG` stays `False` and Paystack stays test-mode. Nothing but the local
  overlay selects it.
- **`render_nginx.sh --local`** to render the HTTP-only local site config.
- **`tests/test_ci_security_gate.py`** — 9 tests pinning the CI dependency-scan
  target, its un-waivable failure modes, finding classification against
  pip-audit's real wording, full-SHA action pinning and the mandatory jobs.
- **`docs/PRE_HOSTING_READINESS_REPORT.md`** — the 16-task pre-hosting
  readiness report with real evidence and an explicit NOT VERIFIED list.

### Fixed

- **CI dependency scan audited the wrong environment.** `uvx … pip-audit`
  (targetless) scanned pip-audit's own 29 tool dependencies, never the project's.
  The workflow now exports the lock and audits it with `-r`, with an empty-export
  guard.
- **CI mis-classified real findings.** The regex missed pip-audit's actual
  "Found N known vulnerabilities" wording, labelling a genuine finding as a tool
  failure. It now matches the real wording and excludes the clean phrase.
- **`deploy/.env.local.example` was git-ignored** by the broad `.env.*` rule;
  added to the `.gitignore` whitelist.

### Changed

- `tests/test_phase15_deploy.py` — +12 local-stack deployment-invariant tests
  (60 total).
- `.dockerignore` — explicit `deploy/.env.local*` exclusions.

## [Unreleased] — Phase 15: Hostinger VPS deployment preparation

### Added

- **Production Compose stack for a single-host VPS** (`deploy/docker-compose.yml`):
  web (Gunicorn), PostgreSQL, Redis, one Celery worker, one Celery beat and nginx,
  with `restart` policies, health checks, per-service CPU/memory limits, JSON log
  rotation, and a `frontend` bridge network plus an `internal: true` `backend`
  network. Only nginx publishes host ports.
- **Single controlled release step**: a one-shot `migrate` service runs
  `check`/`collectstatic`/`migrate`; `web`/`worker`/`beat` set
  `RUN_MIGRATIONS=false` and wait on `service_completed_successfully`, so
  concurrent migrations are impossible.
- **Deployment scripts**: `db_migrate.sh` (host-locked controlled migration),
  `backup_docker.sh` (in-container `pg_dump`, host-side encryption + upload),
  `disk_check.sh` (disk/Docker growth monitor), `host_hardening.sh` (SSH keys,
  ufw, fail2ban, unattended upgrades; dry-run unless `--apply`),
  `render_nginx.sh` (refuses placeholder domains), `ssl_bootstrap.sh` and
  `ssl_renew.sh`.
- **nginx bootstrap config** (`deploy/nginx/bootstrap.conf`) to solve the ACME
  chicken-and-egg before the first certificate exists.
- **`.dockerignore`** so `.env`, deployment env files, `media/`, `staticfiles/`,
  TLS material, `.git`, `node_modules/`, `.venv/`, `tests/` and `docs/` never
  enter the image; plus **`.gitattributes`** pinning LF for every file executed on
  the Linux host (`*.sh`, `*.conf`, `Dockerfile`, `*.yml`, `*.service`,
  `*.timer`), because a CRLF shell script fails on the VPS with
  `bad interpreter: /usr/bin/env bash^M`.
- **`docs/HOSTINGER_VPS_DEPLOYMENT.md`** — the full Ubuntu 24.04 + Docker Compose
  host procedure (provisioning, SSH, hardening, DNS/TLS, migration, backups,
  monitoring, rollback, troubleshooting).
- **`tests/test_phase15_deploy.py`** — 48 deployment-invariant tests over the
  rendered Compose model and the env templates (network isolation, single
  migrator, single beat, limits, health checks, persistent volumes, secret
  hygiene, env-file isolation).

### Fixed

- **Staging could load production secrets.** Compose *appends* `env_file` lists
  when an override file is merged, so the staging overlay's `env_file` never
  replaced the production one — staging required `deploy/.env.production` to
  exist and would inherit any variable staging did not itself define. The env
  file is now selected by interpolation (`APP_ENV_FILE`, defaulting to
  `.env.production`), and the staging overlay declares no `env_file` at all.
- **`disk_check.sh` parsed the device column incorrectly** when a device name
  contained spaces, and a failing `docker` probe under `set -o pipefail` made the
  monitor always exit non-zero.
- **`validate_env.sh`** now requires `POSTGRES_PASSWORD`/`REDIS_PASSWORD`, checks
  that `DATABASE_URL` and the Redis URLs embed the matching passwords and are
  URL-safe, and warns when `DB_SSLMODE_REQUIRE=True` (which the bundled
  PostgreSQL, having no TLS listener, cannot satisfy).

### Security

- `.env.production.example` no longer ships `POSTGRES_PASSWORD` unset (which made
  `docker compose config` fail) and defaults `DB_SSLMODE_REQUIRE=False` for the
  internal Docker network.
- `smoke_test.sh` now asserts that invoices, receipts, payment evidence and
  export/support documents are not anonymously reachable.

### Verification (Phase 15, executed locally)

- `ruff check` + `ruff format --check` clean; `manage.py check` clean;
  `makemigrations --check` clean; full pytest suite green.
- `docker compose config` exits 0 for both the production file and the staged
  production+staging overlay (client-side; the Docker daemon is unavailable here).
- `validate_env.sh` accepts a valid env and rejects a bad one; `render_nginx.sh`
  refuses placeholder/malformed hosts; `disk_check.sh` returns the correct exit
  codes; the smoke test passes against the local dev server with every private
  route returning 302.
- **NOT VERIFIED:** image build, host hardening, TLS issuance, host restore drill,
  monitoring alerts, staging performance/axe and a real Paystack test transaction
  — all require a real host and owner-supplied credentials.

## [Phase 13–14] — security hardening, staging verification & launch readiness

### Added

- **Staff TOTP MFA** (`apps/accounts/mfa/`, label `accounts_mfa`): dependency-free
  TOTP, encrypt-then-MAC secret storage, single-use hashed recovery codes,
  rate-limited challenge/verify, capability-gated disable/reset.
- **Upload malware scanning & quarantine** (`apps/core/upload_security.py`,
  `FileScanRecord`): scan-before-store, fail-closed enforcement, admin review and
  audited release; optional ClamAV backend in the Compose reference stack.
- **`config.settings.staging`** and pure guards (`config/settings/_guards.py`):
  staging refuses a live Paystack key or live mode at import time.
- **`manage.py verify_deployment`**: read-only environment/DB/security verifier
  (connection, migrations, role groups, reference data, cache, storage, security
  settings, Paystack guard) with PASS/FAIL/WARN output and JSON report.
- **Deployment automation**: `validate_env.sh`, `preflight.sh`, `smoke_test.sh`,
  `verify_host.sh`, `staging_deploy.sh`, `rollback.sh`, `restore_drill.sh`;
  `deploy/.env.staging.example`, `deploy/docker-compose.staging.yml`.
- **Launch documentation**: `PHASE_14_STAGING_REPORT.md`,
  `PRODUCTION_LAUNCH_APPROVAL.md`, `PRODUCTION_LAUNCH_PLAN.md`,
  `STAGING_TEST_PLAN.md`, `BUSINESS_CONTENT_APPROVAL_CHECKLIST.md`.
- **Tests**: MFA (26), upload security (32), inventory concurrency (18), Paystack
  test-mode (6), staging guards / `verify_deployment` / route inventory (67).

### Changed

- **Inventory** selects an explicit warehouse, guards per-warehouse oversell and
  recomputes roll-ups from Σ balances (multi-warehouse correctness).
- **CI hardened**: actions pinned to commit SHAs, `pip-audit` pinned with
  `--strict`, mandatory (non-blocking) checks.

### Security

- Paystack live-key fail-closed guard (`sk_live_` refused unless
  `PAYSTACK_LIVE_MODE=True`); staging profile forbids live money outright.
- Analytics double-compute (L-1) and export selector naming (L-2) resolved.

### Verification (Phase 14, executed locally)

- Full suite **857 passed, 0 failed**; lint/format/check/migrations clean;
  production `check --deploy` clean; CSS build.
- Real PostgreSQL backup/restore drill: restore 14 s (25 s total); restored DB
  passed `migrate --check`.
- Live local HTTP smoke test passed; local load baseline captured.
- **No** staging deploy, DNS change, live Paystack key or production data change.

## [Phase 12] — production security, QA, deployment & launch readiness

### Security

- Added `@require_POST` to ten staff dashboard actions that mutated state over
  `GET` (export destinations, export quotations/compliance; training
  categories/courses/instructors/assignments/assessments) — closes a CSRF-bypass
  path. (Audit H-1.)
- Payment webhook now honours the `PAYSTACK_ENABLED` kill switch: when payments
  are disabled the event is recorded as `ignored` and never settles an order.
  (Audit H-3.)
- Hardened settings: `CSRF_COOKIE_HTTPONLY`, `SECURE_CONTENT_TYPE_NOSNIFF`,
  `SECURE_CROSS_ORIGIN_OPENER_POLICY`, and explicit upload-size/number limits.
- Production settings rewritten to fail fast on insecure configuration
  (weak/short `SECRET_KEY`, wildcard/empty `ALLOWED_HOSTS`, non-HTTPS
  `CSRF_TRUSTED_ORIGINS`, non-Redis cache, console/locmem/dummy email backend).
- Production adds HSTS (preload off by default), secure/HttpOnly/SameSite
  cookies, `SECURE_SSL_REDIRECT`, `X-Forwarded-Proto` trust, WhiteNoise manifest
  static storage, explicit password hashers and structured JSON logging.
- nginx reference config default-denies `/media/` and allow-lists only public
  prefixes; private documents are served only through authorised Django views.
  (Audit H-2.)
- Added a 23-test production security suite (`tests/test_production_security.py`)
  covering GET-mutation rejection, auth redirects, webhook signature/kill-switch,
  duplicate-event idempotency, object-level boundaries, CSRF cookie behaviour and
  production settings fail-fast.

### Fixed

- Cancelling a **paid** order through the generic status transition now returns
  committed stock to the ledger (previously only active holds were released).
  (Audit M-1.)
- `ProductListing.primary_image` is memoised per instance, removing an N+1 on
  catalogue cards. (Audit M-2.)

### Added

- End-to-end scenario suite (`tests/test_e2e.py`): purchase → payment →
  confirmed; consultancy → quotation; export enquiry → order; training
  enrolment → payment; support ticket lifecycle; analytics report → download.
- Dedicated test settings module (`config/settings/test.py`) with fast password
  hashing, eager Celery, in-memory email and a temporary `MEDIA_ROOT`.
- Deployment assets under `deploy/` (Dockerfile, Compose stack, gunicorn config,
  entrypoint, nginx site, systemd units, backup/restore/healthcheck/deploy
  scripts, production env template) and a dependency-free load tester.
- CI pipeline (`.github/workflows/ci.yml`): lint/format, system + migration
  checks, asset build, tests with coverage, dependency audit and a production
  `check --deploy`.
- Safe error templates (`400.html`, `404.html`, `500.html`).
- Documentation: production readiness audit, disaster recovery, runbook,
  monitoring, data protection, launch content checklist, performance &
  accessibility, release checklist, and the final readiness report.
- Added `gunicorn` as a production server dependency.

### Notes

- Payments remain in **test mode**; no live credentials, DNS changes or customer
  data were introduced by this phase.
- Known accepted gaps (see the final readiness report): no MFA for privileged
  staff yet, no malware scanning, multi-warehouse reservations default to the
  single MAIN warehouse, and deployment-dependent controls (TLS, `/media/`
  deny, backups) require verification on the host.

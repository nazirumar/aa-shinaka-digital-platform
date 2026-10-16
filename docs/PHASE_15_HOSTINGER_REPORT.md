# Phase 15 — Hostinger VPS Deployment: Completion Report

**Status: DELIVERED AS CONFIGURATION / AUTOMATION / TESTS / DOCUMENTATION.**
The platform has **not** been deployed. No server was provisioned, no DNS record
was created or changed, no TLS certificate was issued, no live Paystack
credential was used and no production data was touched. Every gate that requires
a real host is therefore recorded as **NOT VERIFIED** — never as passed.

- Repository: `aa-shinaka-digital-platform`
- Baseline: `master` @ `7c13f64` (Phase 14), preceded by `ecbf53d` (Phase 13) —
  both re-confirmed **COMPLETE** before this phase began.
- Host target: **Hostinger KVM VPS, Ubuntu 24.04 LTS**, Docker Compose.
- Owner-supplied prerequisites (domain, Paystack test keys, SMTP, SSH key) were
  **not** available in this environment.

---

## 1. Objective

Prepare — but do not execute — a production-grade Docker Compose deployment of
the AA Shinaka platform on a single Hostinger KVM VPS: production settings driven
by environment variables, a reproducible build and startup, security hardening,
persistent database and media storage with encrypted off-server backups,
domain/HTTPS readiness (without inventing DNS), Paystack kept in test mode, and a
full local quality-gate run. Deliver a step-by-step host guide and this report,
then **stop at the staging deployment approval gate**.

---

## 2. What was delivered

### 2.1 Stack — `deploy/docker-compose.yml`

| Service | Role | Host ports | Health check | Limits |
|---|---|---|---|---|
| `nginx` | TLS termination, static/media, rate limiting | `80`, `443` | ✔ | 0.5 CPU / 128 MB |
| `web` | Gunicorn (WSGI) | none | ✔ | 1.5 CPU / 1 GB |
| `worker` | Celery worker | none | — | 1.5 CPU / 1 GB |
| `beat` | Celery beat (**exactly one**) | none | — | 0.25 CPU / 256 MB |
| `migrate` | One-shot: `check` → `collectstatic` → `migrate` | none | — | 1.0 CPU / 768 MB |
| `db` | PostgreSQL 16 (internal only) | **none** | ✔ (`pg_isready`) | 1.0 CPU / 1 GB |
| `redis` | Redis, `requirepass` (internal only) | **none** | ✔ (`redis-cli ping`) | 0.5 CPU / 256 MB |
| `clamav` | Optional upload scanner (`--profile scanning`) | none | — | — |
| `certbot` | Optional ACME client (`--profile tls`) | none | — | — |

Design rules enforced:

- **Network isolation.** Two networks: `frontend` (bridge, has egress) and
  `backend` (`internal: true`). `db` and `redis` sit **only** on `backend` and
  publish **no** host ports. `web`/`worker`/`beat`/`migrate` join both; `nginx`
  joins only `frontend`.
- **Exactly one migrator.** Every long-running service sets
  `RUN_MIGRATIONS=false`; `web`/`worker`/`beat` declare
  `depends_on: migrate: condition: service_completed_successfully`. The
  `migrate` service has `restart: "no"`. Two containers can never migrate
  concurrently.
- **Exactly one Celery beat.** Documented and test-enforced; `--scale beat=N`
  is explicitly forbidden because it would double-fire every periodic task.
- **Persistence.** Named volumes `pgdata`, `media`, `staticfiles`, `redisdata`
  (and `clamd_sock`) outlive container recreation. `docker compose down -v` is
  called out as destructive.
- **Operational hygiene.** `restart: unless-stopped` (except `migrate`),
  `init: true`, `no-new-privileges` on application services, per-service
  `logging` with size/file rotation, and per-service CPU/memory limits.

### 2.2 Environment configuration

`deploy/.env.production.example` is the canonical template: `DEBUG=False`,
`SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`,
`POSTGRES_*`, `REDIS_PASSWORD` + cache/Celery URLs, SMTP, Paystack **test mode**,
HTTPS/secure-cookie toggles, logging and static/media paths, `GUNICORN_*`,
`BACKUP_*`, `DISK_USAGE_THRESHOLD`, `DOMAIN`/`HTTP_PORT`/`HTTPS_PORT` and
`APP_ENV_FILE`. **No secret is committed** — only the templates are tracked.

`deploy/.env.staging.example` mirrors it for the isolated staging profile with
`APP_ENV_FILE=.env.staging`.

### 2.3 Scripts (`deploy/scripts/`)

New in Phase 15:

| Script | Purpose |
|---|---|
| `db_migrate.sh` | Controlled migration: single container, host-side lock, optional pre-migration backup, abort on failure. |
| `backup_docker.sh` | `pg_dump` **inside** the db container, then encrypt + upload **on the host** — encryption keys and off-server credentials never enter a container. Retention-aware. |
| `disk_check.sh` | Disk usage + Docker growth monitor; cron-friendly; exits non-zero past `DISK_USAGE_THRESHOLD`. |
| `host_hardening.sh` | SSH key-only auth, non-root admin, `ufw`, `fail2ban`, `unattended-upgrades`. **Dry-run by default**; requires `--apply`; refuses to disable password auth until a key exists. |
| `render_nginx.sh` | Renders the active nginx site config for the owner domain; refuses `EXAMPLE_DOMAIN` placeholders and malformed hosts. |
| `ssl_bootstrap.sh` | HTTP bootstrap config → ACME HTTP-01 → switch to TLS. Supports `--staging` to rehearse. |
| `ssl_renew.sh` | Certificate renewal + nginx reload. |

Extended: `validate_env.sh` (requires `POSTGRES_PASSWORD`/`REDIS_PASSWORD`,
checks `DATABASE_URL`/Redis URLs embed the matching URL-safe passwords, warns on
`DB_SSLMODE_REQUIRE=True`), `preflight.sh` (container/host auto-detection),
`deploy.sh` (preflight → build → single release step → up → smoke),
`smoke_test.sh` (adds private-document access assertions).

### 2.4 nginx

`deploy/nginx/aa-shinaka.conf`: TLS template with `server_tokens off`, CSP and
security headers, a dotfile deny, **default-deny `/media/`** with explicit
allow-lists for public catalogue/CMS/training prefixes only, rate-limit zones
(`aa_auth`, `aa_api`, `aa_conn`) applied to authentication and API paths, and a
`/healthz/` endpoint. `deploy/nginx/bootstrap.conf` serves HTTP-only to solve the
ACME chicken-and-egg. The rendered config lives in the gitignored
`deploy/nginx/conf.d/`.

### 2.5 Image hygiene

`.dockerignore` keeps `.env`, `deploy/.env.*`, `media/`, `staticfiles/`,
`deploy/nginx/{certs,conf.d,certbot-www}/`, TLS material, `.git`,
`node_modules/`, `.venv/`, `tests/` and `docs/` out of the build context, so
neither secrets nor host state can enter the image.

`.gitattributes` pins LF for every file that is executed on the Linux host
(`*.sh`, `*.conf`, `Dockerfile`, `*.yml`, `*.service`, `*.timer`, env files). A
shell script that reaches the VPS with CRLF fails with
`bad interpreter: /usr/bin/env bash^M`; the repository index is already fully
LF-normalised, and this removes the dependency on any one machine's
`core.autocrlf` setting.

### 2.6 Tests — `tests/test_phase15_deploy.py`

48 test cases (33 functions, several parametrized) covering the rendered Compose
model (`docker compose config --format json`) plus always-run text/env checks:
network isolation, "only nginx publishes ports", "db/redis have no ports",
"backend is internal", single-migrator and single-beat invariants, restart
policies, log rotation, health checks, resource limits, persistent named volumes,
`no-new-privileges`, secret hygiene, and **environment-file isolation** between
staging and production.

### 2.7 Documentation

- `docs/HOSTINGER_VPS_DEPLOYMENT.md` — 19 sections: owner prerequisites, VPS
  setup, SSH, Docker verification, repo deployment, env vars, service startup,
  database init/controlled migration, superuser, `sync_roles`, Nigeria import,
  domain, SSL, backups/recovery, monitoring, safe updates/rollback, post-deploy
  checklist, troubleshooting and the outstanding deployment gates.
- `deploy/README.md`, `README.md`, `AGENTS.md` and `CHANGELOG.md` updated.

---

## 3. Defects found and fixed during this phase

1. **Staging could load production secrets (high).** Compose *appends* `env_file`
   lists when an override file is merged, so the staging overlay's `env_file`
   never replaced the production one — staging both required
   `deploy/.env.production` to exist and inherited any variable staging did not
   define. Fixed by selecting the file through interpolation
   (`${APP_ENV_FILE:-.env.production}`); the staging overlay now declares **no**
   `env_file`, and staging renders successfully with no production env file
   present. Pinned by tests, including a canary-variable end-to-end test.
2. **`docker compose config` failed out of the box.** `POSTGRES_PASSWORD` was
   absent from the template, so interpolation `${POSTGRES_PASSWORD:?}` aborted.
   Fixed in the template.
3. **`DB_SSLMODE_REQUIRE=True` would break the bundled PostgreSQL**, which
   exposes no TLS listener. Production default retained, but the Compose
   template / internal-network guidance sets `False` and `validate_env.sh`
   warns.
4. **`web` self-migrated on boot**, risking concurrent migrations. Replaced with
   the single one-shot `migrate` service and `RUN_MIGRATIONS=false`.
5. **`disk_check.sh` mis-parsed the device column** when a device name contained
   a space, and a failing `docker` probe under `set -o pipefail` made the monitor
   always exit non-zero. Both fixed and verified by exit code.
6. **Missing `.dockerignore`** would have let `.env`, `media/` and `.git` enter
   the image.

---

## 4. Verification performed (real results, executed locally)

| Check | Command | Result |
|---|---|---|
| Lint | `uv run ruff check .` | **PASSED** — All checks passed |
| Format | `uv run ruff format --check .` | **PASSED** — 327 files already formatted |
| Django check | `uv run python manage.py check` | **PASSED** — no issues (0 silenced) |
| Migration guard | `uv run python manage.py makemigrations --check --dry-run` | **PASSED** — no changes detected |
| Full test suite | `uv run pytest` | See §5 |
| Deployment tests | `uv run pytest tests/test_phase15_deploy.py` | **PASSED** — 48 passed |
| Production Compose model | `docker compose --env-file deploy/.env.production.example -f deploy/docker-compose.yml config` | **PASSED** — exit 0 |
| Staging Compose model | `docker compose --env-file deploy/.env.staging.example -f … -f deploy/docker-compose.staging.yml config` | **PASSED** — exit 0, with `deploy/.env.production` **absent** |
| Env validation (good) | `validate_env.sh` on a synthetic valid env | **PASSED** |
| Env validation (bad) | `validate_env.sh` on a mismatch/live-key env | **PASSED** — correctly rejected |
| nginx render guard | `render_nginx.sh EXAMPLE_DOMAIN` | **PASSED** — refused placeholder |
| nginx render | `render_nginx.sh <valid host>` | **PASSED** — correct `server_name` |
| Disk monitor | `disk_check.sh` | **PASSED** — correct 0/1 exit codes |
| Smoke test (local) | smoke test against the local dev server | **PASSED** — 23/23, every private route 302 |

Rendered topology confirmed from the Compose model: services
`beat, db, migrate, nginx, redis, web, worker`; networks
`frontend` (public) + `backend` (`internal: true`); volumes
`media, pgdata, redisdata, staticfiles`; only `nginx` publishes `80`/`443`.

**Private-document access.** The smoke test verifies that `/invoices/`,
`/invoices/<num>/`, `/invoices/<num>/pdf/`, `/receipts/<num>/`,
`/receipts/<num>/pdf/`, `/payments/`, `/orders/`, `/account/export/`,
`/account/support/` all return `302` for anonymous users, and `/media/*` returns
`404`. Customer invoices, payment evidence and export documents are therefore not
anonymously downloadable at the application layer; the nginx template
additionally default-denies `/media/` on the host.

---

## 5. Full test suite

- Baseline before Phase 15: **857 passed** (documented in Phase 14).
- `tests/test_phase15_deploy.py`: **48 passed** (33 functions; several parametrized).
- **Final full-suite run — `uv run pytest -q -p no:randomly`:
  `905 passed, 14 warnings in 343.50s`.** Zero failures, zero errors. The 14
  warnings are pre-existing Django 6.0 deprecation notices and one
  pytest collection warning unrelated to this phase.

Final gate summary: `ruff check` **clean** · `ruff format --check` **clean**
(328 files) · `manage.py check` **clean** · `makemigrations --check` **no changes**
· `pytest` **905 passed** · `docker compose config` **exit 0** (production and
staging) · `npm run build:css` **exit 0**.

---

## 6. Step-by-step status (the 16-step brief)

| # | Step | Status | Justification |
|---|---|---|---|
| 1 | Audit existing deployment assets | **PASSED** | Six concrete defects found and fixed (§3); `uv.lock` confirms `psycopg-binary`, so no system build deps are needed. |
| 2 | Production Docker Compose stack | **PASSED (config) / NOT VERIFIED (runtime)** | Model validates via `docker compose config`; image build and `up` are NOT VERIFIED — no Docker daemon. |
| 3 | Environment-based production settings | **PASSED** | Template satisfies `config.settings.prod`; validation script enforces it. |
| 4 | Reproducible build & startup | **PASSED (config) / NOT VERIFIED (execution)** | Single release step, pinned `uv.lock`, rendered nginx; build not executed. |
| 5 | Security (SSH, firewall, HTTPS, MFA, scanning, rate limits, audit) | **PASSED (config+code) / NOT VERIFIED (host)** | MFA and upload scanning are Phase 13 code with tests; host hardening, ufw/SSH/fail2ban and TLS are scripted but not executed on a host. |
| 6 | Database, storage & backups | **PASSED (config) / NOT VERIFIED (host drill)** | Persistent named volumes; encrypted off-server backup script; restore guidance. Off-server drill NOT VERIFIED (no off-server target). |
| 7 | Domain / HTTPS preparation | **NOT APPLICABLE / NOT VERIFIED** | No owner domain exists; no DNS record invented or changed. Scripts render and validate only when a real domain is supplied. |
| 8 | Paystack kept in test mode | **PASSED (guard) / NOT VERIFIED (live transaction)** | `config.settings.staging` and the live-key guard refuse live mode; webhook signature/idempotency/kill-switch have automated tests. A real test-mode checkout is NOT VERIFIED (no test keys). |
| 9 | Ruff / checks / migrations / tests | **PASSED** | §4 and §5. |
| 10 | Deployment guide | **PASSED** | `docs/HOSTINGER_VPS_DEPLOYMENT.md`. |
| 11 | Do not invent DNS / no public changes | **PASSED** | No DNS API used; no changes made anywhere. |
| 12 | Do not delete data; preserve features | **PASSED** | No destructive command run; full suite green. |
| 13 | Error handling / rollback | **PASSED (config)** | `rollback.sh`, migration-rollback guidance, health-gated deploy. |
| 14 | Staging configuration | **PASSED (config)** | Isolated project/DB/Redis/volumes/ports; isolation defect fixed and tested. |
| 15 | Staging smoke tests | **PASSED (local) / NOT VERIFIED (staging host)** | Smoke test passes locally; no staging host exists to run it against. |
| 16 | Stop at approval gate | **PASSED** | Awaiting owner approval; nothing deployed. |

---

## 7. Explicitly NOT VERIFIED (requires a real host / owner inputs)

These are carried forward as deployment gates. They must not be reported as
passed, and Phase 15 does not claim them:

1. Docker **image build** and `docker compose up` (no running Docker daemon;
   WSL is broken on this workstation).
2. `nginx -t` and actual TLS termination / certificate renewal.
3. Host provisioning, SSH hardening, `ufw`, `fail2ban`, unattended upgrades.
4. TLS issuance for the real domain, and the public DNS change itself.
5. The **host restore drill** from an off-server encrypted backup.
6. Monitoring wiring and a delivered test alert.
7. Staging performance baseline and the axe/Lighthouse accessibility pass.
8. A real Paystack **test-mode** transaction end-to-end (checkout, webhook,
   duplicate webhook, refund, finance reconciliation) — no test keys available.
9. **Nigeria location import:** no verified dataset was supplied. The local dev
   database holds only 37 states / 450 LGAs (partial); the required 37 states +
   774 LGAs import remains unverified.
10. Business-content sign-off.

---

## 8. Deployment blockers (owner action required)

Before any host execution can begin, the owner must supply:

- A Hostinger KVM VPS (Ubuntu 24.04) **or** approval to provision one.
- The **production domain** and approval to create/change its DNS records.
- Provider SMTP credentials.
- **Paystack test-mode** keys (live keys are refused until a later explicit
  approval).
- An SSH public key for the non-root admin user.

Nothing in this phase connected to a server, deployed anything publicly, enabled
live Paystack, or altered data. The platform remains **READY FOR STAGING**.

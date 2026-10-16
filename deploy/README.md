# Deployment assets — AA Shinaka platform (Phase 15)

Production deployment configuration for a **Hostinger KVM VPS on Ubuntu 24.04
LTS** (Docker Compose), with a bare-metal `systemd` alternative. Nothing here
deploys automatically, changes DNS, or enables live payments.

The step-by-step host procedure lives in
[`../docs/HOSTINGER_VPS_DEPLOYMENT.md`](../docs/HOSTINGER_VPS_DEPLOYMENT.md);
what was actually verified (and what could not be) lives in
[`../docs/PHASE_15_HOSTINGER_REPORT.md`](../docs/PHASE_15_HOSTINGER_REPORT.md).

## What is here

| Path | Purpose |
|---|---|
| `Dockerfile` | Multi-stage image: Tailwind build + Python runtime (uv + Gunicorn), non-root. |
| `.dockerignore` | Keeps secrets, host state and dev caches out of the image. |
| `docker-compose.yml` | Full stack with internal networks, limits, health checks and log rotation. |
| `docker-compose.staging.yml` | Staging override: distinct project name, non-standard ports. |
| `docker-compose.local.yml` | Local-test override: production shape on a laptop, plus a Mailpit inbox. |
| `gunicorn.conf.py` | WSGI server config (behind nginx), environment-driven. |
| `entrypoint.sh` | Optional checks/migrations/collectstatic before the service command. |
| `.env.production.example` | Every production variable, with no secrets. |
| `.env.staging.example` | Staging template (test-mode Paystack only). |
| `.env.local.example` | Local-test template (plain HTTP, Mailpit, test-mode Paystack). |
| `nginx/aa-shinaka.conf` | TLS template: static/media, default-deny media, rate limits, security headers. |
| `nginx/bootstrap.conf` | HTTP-only config used to obtain the first certificate. |
| `nginx/local.conf` | HTTP-only site for the local-test stack (same media default-deny). |
| `nginx/conf.d/` | Render target for the active site config (gitignored). |
| `systemd/*.service`, `*.timer` | Bare-metal alternative to Compose. |
| `scripts/backup.sh` | Bare-metal verified, optionally-encrypted PostgreSQL backup. |
| `scripts/backup_docker.sh` | Compose backup: `pg_dump` in the container, encrypt + upload on the host. |
| `scripts/restore.sh`, `scripts/restore_drill.sh` | Restore, and isolated restore rehearsal. |
| `scripts/db_migrate.sh` | **Controlled migration** (single container, host lock, optional pre-backup). |
| `scripts/validate_env.sh` | Fail-safe environment validation before any build/restart. |
| `scripts/preflight.sh` | Non-destructive pre-deploy gate (env + checks + migrations + verifier). |
| `scripts/deploy.sh` | Preflight, build, single release step, start, smoke test. |
| `scripts/staging_deploy.sh` | Staging orchestrator (preflight, backup, migrate, smoke). |
| `scripts/rollback.sh` | Safe code rollback (no migration reversal). |
| `scripts/render_nginx.sh` | Render the site config for the owner-approved domain (or `--local`). |
| `scripts/ssl_bootstrap.sh`, `scripts/ssl_renew.sh` | Issue and renew Let's Encrypt certificates. |
| `scripts/host_hardening.sh` | SSH/ufw/fail2ban/unattended-upgrades (dry-run by default). |
| `scripts/disk_check.sh` | Disk and Docker-growth monitor (cron-friendly). |
| `scripts/smoke_test.sh` | Post-deploy HTTP + private-document access smoke test. |
| `scripts/verify_host.sh` | Host security verification (TLS, redirect, media deny, ports). |
| `scripts/loadtest.py` | Dependency-free read-only load tester. |

## Stack topology

```
                 ┌──────────── public ────────────┐
  :80/:443  nginx (TLS terminates here)
                 └───────┬────────────────────────┘
                    frontend network
                         │
        ┌────────────────┼─────────────────┐
      web            worker             beat
   (Gunicorn)      (Celery)        (Celery beat ×1)
        └────────────────┼─────────────────┘
                  backend network (internal: true)
                         │
                    db (PostgreSQL)   redis
```

* **Only nginx publishes host ports.** PostgreSQL and Redis have no `ports:` and
  live on the `backend` network, which is `internal: true`.
* **Exactly one container migrates.** Every long-running service sets
  `RUN_MIGRATIONS=false`; the one-shot `migrate` service runs the system check,
  `collectstatic` and `migrate`, and `web`/`worker`/`beat` wait for it with
  `depends_on: service_completed_successfully`.
* **Exactly one Celery beat.** Never `--scale beat=N` — two schedulers
  double-fire every periodic task.
* Named volumes `pgdata`, `media` and `staticfiles` outlive `docker compose down`.
  Never run `docker compose down -v` in production.

## Quick start (Compose)

```bash
cp deploy/.env.production.example deploy/.env.production   # fill it in
./deploy/scripts/validate_env.sh deploy/.env.production    # must pass
./deploy/scripts/render_nginx.sh yourdomain.com            # owner-approved domain
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml up -d --build
```

Then, once the stack is healthy:

```bash
./deploy/scripts/db_migrate.sh --with-backup     # controlled migration
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py sync_roles
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py createsuperuser
```

Issue TLS **after DNS points here and the owner approves**:

```bash
./deploy/scripts/ssl_bootstrap.sh yourdomain.com ops@yourdomain.com --staging  # rehearse
./deploy/scripts/ssl_bootstrap.sh yourdomain.com ops@yourdomain.com            # real
```

## Environment file selection

Compose **appends** `env_file` lists when override files are merged, so the
overlay cannot replace a hard-coded path. The base file therefore interpolates
the name — `${APP_ENV_FILE:-.env.production}` — and:

* production sets `APP_ENV_FILE=.env.production` (the default);
* staging sets `APP_ENV_FILE=.env.staging` in `deploy/.env.staging` and the
  overlay declares **no** `env_file` at all;
* local sets `APP_ENV_FILE=.env.local` in `deploy/.env.local`, likewise with no
  `env_file` in the overlay.

This keeps the three environments' secrets genuinely separate. `tests/test_phase15_deploy.py`
pins the behaviour down.

## Local test stack (no VPS required)

The production-shaped stack runs on a development machine with a thin overlay —
same image, same services (nginx, Gunicorn, PostgreSQL, Redis, Celery worker +
beat), plus a **Mailpit** capture inbox so real email delivery is exercised
without sending mail:

```bash
cp deploy/.env.local.example deploy/.env.local
./deploy/scripts/render_nginx.sh --local
docker compose --env-file deploy/.env.local \
  -f deploy/docker-compose.yml -f deploy/docker-compose.local.yml up -d --build
# Site  : http://localhost:8080
# Inbox : http://localhost:8025
```

It runs `config.settings.local` — the production settings with **only** the
plain-HTTP controls relaxed (non-`Secure` cookies, no SSL redirect, `http://`
CSRF origin). `DEBUG` stays `False`, Redis is the real cache, document scanning
uses the real policy (`UPLOAD_SCAN_ENFORCEMENT=log` tolerates a missing ClamAV),
and Paystack stays **test-mode only**. The plain-HTTP allowances are unreachable
from production/staging: no other Compose file selects that module, and
`tests/test_phase15_deploy.py` pins that down.

## Staging (isolated from production)

Staging runs the same image shape on a separate project, database, Redis and
media volume, with **test-mode Paystack only** (`config.settings.staging`
refuses a live key or live mode at import time).

```bash
cp deploy/.env.staging.example deploy/.env.staging   # fill every value
./deploy/scripts/validate_env.sh deploy/.env.staging
./deploy/scripts/staging_deploy.sh <git-ref>
```

The staging overlay publishes nginx on ports 8080/8443 so it can share a host
with production without a clash.

## Pre-deploy and verification

```bash
./deploy/scripts/preflight.sh deploy/.env.production            # non-destructive gate
BASE_URL=https://yourdomain.com ./deploy/scripts/smoke_test.sh  # post-deploy smoke
BASE_URL=https://yourdomain.com ./deploy/scripts/verify_host.sh
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py verify_deployment
```

> **Host hygiene:** ensure no root `.env` file exists on the host. Settings read
> a local `.env` as a fallback, and the repository's `.env` holds development
> values (including `DJANGO_SECURE_SSL_REDIRECT=False`). Real environment
> variables take precedence, but the fallback must not be present.

Nothing here deploys automatically, enables live Paystack credentials or changes
DNS. See `docs/PRODUCTION_RUNBOOK.md`, `docs/PRODUCTION_LAUNCH_PLAN.md`,
`docs/STAGING_TEST_PLAN.md` and `docs/DISASTER_RECOVERY.md`.

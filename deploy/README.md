# Deployment assets — AA Shinaka platform (Phases 12–14)

Reference deployment configuration for an **approved Linux VPS or compatible
cloud host**. Nothing here deploys automatically and nothing assumes a hosting
provider: replace the `EXAMPLE_DOMAIN` placeholders with the owner-approved
production domain.

## What is here

| Path | Purpose |
|---|---|
| `Dockerfile` | Multi-stage image: Tailwind build + Python runtime (uv + Gunicorn). |
| `docker-compose.yml` | Reference stack: PostgreSQL, Redis, web, Celery worker, beat, nginx. |
| `docker-compose.staging.yml` | Staging override: distinct project name, `.env.staging`, non-standard ports (isolation). |
| `gunicorn.conf.py` | WSGI server config (behind nginx). |
| `entrypoint.sh` | Runs checks, migrations and collectstatic before Gunicorn. |
| `.env.production.example` | Every production environment variable, with no secrets. |
| `.env.staging.example` | Staging environment template (test-mode Paystack only). |
| `nginx/aa-shinaka.conf` | TLS termination, static/media serving, default-deny media. |
| `systemd/*.service`, `*.timer` | Bare-metal alternative to Compose. |
| `scripts/backup.sh` / `restore.sh` | Verified, optionally-encrypted PostgreSQL backups. |
| `scripts/restore_drill.sh` | Isolated restore rehearsal (RTO input). |
| `scripts/healthcheck.sh` | External health probe for monitoring/cron. |
| `scripts/validate_env.sh` | Fail-safe environment validation before any build/restart. |
| `scripts/preflight.sh` | Non-destructive pre-deploy gate (env + checks + migrations + verifier). |
| `scripts/smoke_test.sh` | Post-deploy HTTP smoke test. |
| `scripts/verify_host.sh` | Host security verification (TLS, redirect, media deny, ports). |
| `scripts/deploy.sh` | Build, migrate, collectstatic, restart, smoke test. |
| `scripts/staging_deploy.sh` | Staging orchestrator (preflight, backup, migrate, smoke). |
| `scripts/rollback.sh` | Safe code rollback (no migration reversal). |
| `scripts/loadtest.py` | Dependency-free read-only load tester. |

## Two supported topologies

1. **Docker Compose** (recommended when Docker is available). Uses
   `deploy/docker-compose.yml` and `deploy/nginx/`.
2. **Bare metal** (`nginx` + `systemd`). Uses `deploy/systemd/*.service` and the
   same nginx config; put the app in `/srv/aa-shinaka` with a `.venv`.

## First deploy (Compose)

```bash
cp deploy/.env.production.example deploy/.env.production
# edit deploy/.env.production (secrets, hosts, TLS)
./deploy/scripts/validate_env.sh deploy/.env.production   # must pass
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml exec web python manage.py sync_roles
docker compose -f deploy/docker-compose.yml exec web python manage.py createsuperuser
```

Issue TLS certificates for the real domain (certbot/ACM) and place
`fullchain.pem` / `privkey.pem` in `deploy/nginx/certs/`.

> **Host hygiene:** ensure no root `.env` file exists on the host. Settings read
> a local `.env` as a fallback, and the repository's `.env` holds development
> values. Real environment variables (the Compose `env_file` / systemd
> `EnvironmentFile`) take precedence, but the fallback must not be present.

## Staging (isolated from production)

Staging runs the same image shape on a separate project, database, Redis and
media volume, with **test-mode Paystack only** (`config.settings.staging`
refuses a live key or live mode at import time).

```bash
cp deploy/.env.staging.example deploy/.env.staging   # fill every value
./deploy/scripts/validate_env.sh deploy/.env.staging
./deploy/scripts/staging_deploy.sh <git-ref>
```

The staging override publishes nginx on ports 8080/8443 so it can share a host
with production without a clash.

## Pre-deploy and verification

```bash
./deploy/scripts/preflight.sh deploy/.env.production          # non-destructive gate
BASE_URL=https://DOMAIN ./deploy/scripts/smoke_test.sh        # post-deploy smoke
BASE_URL=https://DOMAIN HOST=DOMAIN ./deploy/scripts/verify_host.sh
docker compose ... exec web python manage.py verify_deployment
```

Nothing here deploys automatically, enables live Paystack credentials or
changes DNS. See `docs/PRODUCTION_RUNBOOK.md`,
`docs/PRODUCTION_LAUNCH_PLAN.md` and `docs/DISASTER_RECOVERY.md`.

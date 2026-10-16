# Deployment assets — AA Shinaka platform (Phase 12)

Reference deployment configuration for an **approved Linux VPS or compatible
cloud host**. Nothing here deploys automatically and nothing assumes a hosting
provider: replace the `EXAMPLE_DOMAIN` placeholders with the owner-approved
production domain.

## What is here

| Path | Purpose |
|---|---|
| `Dockerfile` | Multi-stage image: Tailwind build + Python runtime (uv + Gunicorn). |
| `docker-compose.yml` | Reference stack: PostgreSQL, Redis, web, Celery worker, beat, nginx. |
| `gunicorn.conf.py` | WSGI server config (behind nginx). |
| `entrypoint.sh` | Runs checks, migrations and collectstatic before Gunicorn.
| `.env.production.example` | Every production environment variable, with no secrets.
| `nginx/aa-shinaka.conf` | TLS termination, static/media serving, default-deny media.
| `systemd/*.service`, `*.timer` | Bare-metal alternative to Compose.
| `scripts/backup.sh` / `restore.sh` | Verified, optionally-encrypted PostgreSQL backups.
| `scripts/healthcheck.sh` | External health probe for monitoring/cron.
| `scripts/deploy.sh` | Build → migrate → collectstatic → restart → smoke test.

## Two supported topologies

1. **Docker Compose** (recommended when Docker is available). Uses
   `deploy/docker-compose.yml` and `deploy/nginx/`.
2. **Bare metal** (`nginx` + `systemd`). Uses `deploy/systemd/*.service` and the
   same nginx config; put the app in `/srv/aa-shinaka` with a `.venv`.

## First deploy (Compose)

```bash
cp deploy/.env.production.example deploy/.env.production
# edit deploy/.env.production (secrets, hosts, TLS)
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml exec web python manage.py sync_roles
docker compose -f deploy/docker-compose.yml exec web python manage.py createsuperuser
```

Issue TLS certificates for the real domain (certbot/ACM) and place
`fullchain.pem` / `privkey.pem` in `deploy/nginx/certs/`.

Nothing here deploys automatically, enables live Paystack credentials or
changes DNS. See `docs/PRODUCTION_RUNBOOK.md` and `docs/DISASTER_RECOVERY.md`.

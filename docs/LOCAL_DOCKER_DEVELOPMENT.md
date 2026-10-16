# Local development with Docker Compose

This project has **two** Docker Compose setups, for two different jobs. Knowing
which one you want explains the otherwise confusing
`no configuration file provided: not found`.

## Why `docker compose config` said "no configuration file provided"

Compose only auto-discovers a file named `compose.yaml`, `compose.yml`,
`docker-compose.yaml` or `docker-compose.yml` in the **current directory** (or a
parent). The deployment Compose files live under `deploy/`, so running
`docker compose config` from the repository root found nothing.

## The two stacks

| | Root development stack | Deployment stack |
|---|---|---|
| File | `docker-compose.yml` (repo root) | `deploy/docker-compose.yml` (+ `.staging` / `.local` overlays) |
| Purpose | Everyday local development | Production / staging / production-shaped local test |
| Runs | `manage.py runserver` (auto-reload) | Gunicorn behind nginx |
| Settings | `config.settings.dev` | `config.settings.prod` / `.staging` / `.local` |
| Public entry point | Django dev server on `:8000` | nginx (TLS) |
| Use it on a real host? | **Never** | Yes (that is its purpose) |

Neither file replaces or modifies the other. The root file is unhardened and is
for a laptop only.

## 1. Root development stack (quickest way to run the app)

From the **repository root**:

```bash
docker compose config          # validate / render the model
docker compose up --build      # build the image and start everything
docker compose logs -f web     # follow the app log
docker compose down            # stop (database/uploads are kept)
docker compose down -v         # stop AND delete the database/uploads
```

Application: <http://localhost:8000>

Services: `db` (PostgreSQL 16), `redis` (Redis 7), `migrate` (one-shot
`manage.py migrate`), `web` (Django dev server), `worker` (Celery) and `beat`
(Celery beat). Only `web` is published to the host.

Source reload: `web` bind-mounts `apps/`, `config/`, `templates/`, `locale/` and
`manage.py`, so edits are picked up by the reloader. The image's virtualenv is
never shadowed. Celery's `worker`/`beat` do **not** hot-reload — restart them
(`docker compose restart worker beat`) after changing task code.

### Configuration

Every value is an environment variable with a development default, so the stack
starts with no configuration at all. Override any of them through the shell or
by adding them to the repository-root `.env` file (which Compose reads for
`${...}` interpolation):

| Variable | Default | Meaning |
|---|---|---|
| `WEB_PORT` | `8000` | Host port the dev server is published on. |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `aa_shinaka` / `aa_shinaka` / `aa_shinaka_dev_pw` | Database credentials (must agree across `db` and the app). |
| `DJANGO_SECRET_KEY` | insecure dev value | Django secret key. |
| `CELERY_CONCURRENCY` | `2` | Celery worker concurrency. |
| `PAYSTACK_ENABLED` | `false` | Leave off unless testing payments. |
| `PAYSTACK_SECRET_KEY` / `PAYSTACK_PUBLIC_KEY` | empty | Use **`sk_test_`/`pk_test_`** only. |

### Safety

* **Payments stay in test mode.** `PAYSTACK_LIVE_MODE` is hard-set to `false` in
  the file; a live key is refused by the application, exactly as in production.
* **The database and Redis are never published** on a host port.
* **No secret is hardcoded** and the root `.env` (gitignored) is never baked
  into an image.
* Use `docker compose down -v` to reset local data; plain `down` keeps it.

## 2. Deployment stack (production / staging / production-shaped local test)

These live under `deploy/` and are the real, hardened deployment artifacts. See
[`deploy/README.md`](../deploy/README.md) for the full description. Quick
reference:

```bash
# Production (needs deploy/.env.production and a rendered nginx config)
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml up -d --build

# Staging
docker compose --env-file deploy/.env.staging -f deploy/docker-compose.yml -f deploy/docker-compose.staging.yml up -d --build

# Production-shaped local test (nginx + Gunicorn + Mailpit inbox), no VPS needed
cp deploy/.env.local.example deploy/.env.local
./deploy/scripts/render_nginx.sh --local
docker compose --env-file deploy/.env.local -f deploy/docker-compose.yml -f deploy/docker-compose.local.yml up -d --build
```

To validate any of them **without starting containers** (client-side only):

```bash
docker compose -f deploy/docker-compose.yml config
```

## What has been verified

`docker compose config` renders the root development stack successfully from the
repository root (client-side; no daemon, no build). Image builds and running
containers are **not** asserted here — run `docker compose up --build` to verify
those on your machine.

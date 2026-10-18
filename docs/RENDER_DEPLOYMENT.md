# Deploying on Render (Blueprint)

This is an alternative to the self-managed VPS deployment
([`HOSTINGER_VPS_DEPLOYMENT.md`](HOSTINGER_VPS_DEPLOYMENT.md)). It uses the
same container image (`deploy/Dockerfile`) and the same production settings
(`config.settings.prod`), but replaces the Compose `db` and `redis` containers
with a **Render Postgres** database and a **Render Key Value** instance.

`render.yaml` (repository root) is the Blueprint that defines the whole stack:

| Resource | Type | Purpose |
|---|---|---|
| `aa-shinaka-web` | Web (Docker) | Django + Gunicorn, public HTTPS |
| `aa-shinaka-worker` | Worker (Docker) | Celery: order expiry, reconciliation, notifications, reports |
| `aa-shinaka-beat` | Worker (Docker) | Celery beat scheduler — **exactly one instance** |
| `aa-shinaka-redis` | Key Value | Cache (rate limiting) + Celery broker/results |
| `aa-shinaka-db` | Postgres 16 | Application database |

Everything is pinned to the **frankfurt** region (closest Render region to
Nigeria). All resources must share a region so they can talk over Render's
private network.

Nothing here deploys a VPS, changes DNS or enables live payments. Paystack stays
disabled (`PAYSTACK_ENABLED=false`, `PAYSTACK_LIVE_MODE=false`).

## Why the Blueprint looks the way it does

These are deliberate choices that match this codebase's production guards:

* **`render.yaml`, not `render.yml`.** Render auto-detects a root file named
  `render.yaml`. A different filename is only used if you set the *Blueprint
  Path* in the dashboard. If you rename it to `render.yml`, set that path.
* **`DJANGO_SECRET_KEY` is prompted, not generated.** Render's "generate value"
  produces a 44-character base64 string, but `config.settings.prod` refuses a
  key shorter than 50 characters. So the key is `sync: false` on the web
  service and shared to the worker/beat services with `fromService`.
* **Gunicorn binds `0.0.0.0:10000`.** Render routes public traffic to the `PORT`
  environment variable, which defaults to `10000`. `deploy/gunicorn.conf.py`
  already reads `GUNICORN_BIND`, so no code change is needed.
* **Migrations run once** via `preDeployCommand`; every service sets
  `RUN_MIGRATIONS=false`. Static files are collected in the web entrypoint
  (`RUN_COLLECTSTATIC=true`) because Render has no shared volume.
* **`DB_SSLMODE_REQUIRE=true`.** Render's internal Postgres connections support
  TLS with self-signed certificates; `sslmode=require` encrypts without
  verifying the CA.
* **`/healthz/`** is the health check. Render treats `2xx`/`3xx` as healthy, so
  the HTTPS redirect (`SECURE_SSL_REDIRECT`) does not break it. The view also
  runs `SELECT 1`, so a broken database fails the check.

## Setup

1. In the Render dashboard choose **New → Blueprint**, connect the GitHub repo
   and select the branch (`master`). Render reads `render.yaml`.
2. When prompted, provide the two secrets:
   * **`DJANGO_SECRET_KEY`** — generate at least 50 characters:
     ```bash
     python -c "import secrets; print(secrets.token_urlsafe(64))"
     ```
     (The worker and beat services inherit this value automatically.)
   * **`EMAIL_HOST_PASSWORD`** — your SMTP password, or leave blank if the relay
     needs no authentication.
3. Apply the Blueprint. Render provisions the database, Key Value instance and
   the three services, runs migrations once, collects static files and starts
   Gunicorn.

## After the first deploy

1. **Look up the web URL.** If Render assigned a different `onrender.com`
   subdomain than `aa-shinaka-web.onrender.com` (a suffix is added only when the
   name is taken), update `DJANGO_ALLOWED_HOSTS` in the environment group, or the
   health check will return `400`.
2. **Replace the placeholders** marked `# EDIT` in `render.yaml`:
   `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `EMAIL_HOST`,
   `EMAIL_HOST_USER`, `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL`, `OPS_EMAIL`. Edit the
   file (and push) or the environment group — Blueprint values are authoritative
   and are re-applied on every sync.
3. **Add your custom domain** in the web service's *Settings → Custom Domains*,
   then add it to `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
   (the origin must be `https://…`) and set `SITE_URL`.
4. **Create the owner account** from the web service's *Shell* tab:
   ```bash
   python manage.py createsuperuser
   ```
   (`sync_roles` already ran via `initialDeployHook`; run it again by hand if you
   ever change the role table.)

## Media files

Container filesystems are **ephemeral** on Render, so uploaded files are lost on
each deploy. Options:

* Attach a **persistent disk** to the web service (see the commented block in
  `render.yaml`). A disk is single-service and is not shared with the worker, and
  its mount path must be writable by the container's non-root `app` user.
* Use **object storage** (recommended once there is more than one instance or
  the worker also writes media).

The worker does not write media for the default configuration
(`ANALYTICS_EXPORT_ASYNC=false` renders reports in the web process), so a
web-only disk is usually sufficient to start.

## Scope

This Blueprint is configuration only. It does **not**:

* deploy to, or replace, the VPS stack in `deploy/`;
* change DNS or issue certificates (Render manages TLS for its domains);
* enable live Paystack credentials or process real payments;
* mark the deployment production-approved — that remains an owner decision, as
  recorded in [`PRODUCTION_LAUNCH_APPROVAL.md`](PRODUCTION_LAUNCH_APPROVAL.md).

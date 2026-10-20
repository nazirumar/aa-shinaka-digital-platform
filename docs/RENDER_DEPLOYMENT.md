# Deploying on Render (Blueprints)

This is an alternative to the self-managed VPS deployment
([`HOSTINGER_VPS_DEPLOYMENT.md`](HOSTINGER_VPS_DEPLOYMENT.md)). It uses the
same container image (`deploy/Dockerfile`) and the same production settings
(`config.settings.prod`), but replaces the Compose `db` and `redis` containers
with **Render Postgres** and a **Render Key Value** instance.

Two Blueprints exist. Pick the one that matches the plan you are paying for —
they are separate files on purpose so a free demo never degrades the production
definition.

| Blueprint | Plan | Resources |
|---|---|---|
| [`render.yaml`](../render.yaml) | Paid | web + Celery worker + Celery beat + Postgres + Key Value |
| [`render.free.yaml`](../render.free.yaml) | Free | web + free Postgres + free Key Value (no workers) |

Both use `config.settings.prod`: `DEBUG=False`, secure cookies, HSTS, HTTPS
redirect, the Paystack live-key guard and upload-scan enforcement are all
unchanged. Neither enables live payments (`PAYSTACK_ENABLED=false`,
`PAYSTACK_LIVE_MODE=false`).

---

## What the free profile changes and why

Render Free has hard limits that shape the free Blueprint:

* **No background workers or cron jobs.** `CELERY_ENABLED=false` makes
  `.delay()` execute inline in the web process, so notification delivery still
  happens instead of being queued into a broker that nobody consumes.
* **Free Key Value is in-memory (25 MB) and loses data on restart.** Queueing
  work there would silently lose it, which is the other reason Celery stays
  disabled.
* **No pre-deploy command.** Render only offers pre-deploy commands on paid
  services, so the free Blueprint sets `RUN_MIGRATIONS=true`: `start.sh` runs
  `migrate` before Gunicorn. Safe because there is exactly one free instance.
  Static files are collected once by `build.sh` at build time.
* **No persistent disk.** Uploads are lost on every deploy/restart (see
  [Media files](#media-files)).
* **Outbound SMTP (ports 25/465/587) is blocked.** Email must go over HTTPS;
  the free Blueprint uses the Resend backend (see [Email](#email)).
* **Free Postgres is deleted 30 days after creation** unless the workspace is
  upgraded, and free web services sleep after 15 minutes idle.

Because beat is gone, an external scheduler must trigger the periodic jobs (see
[Scheduled jobs fallback](#scheduled-jobs-fallback)).

---

## Why the paid Blueprint looks the way it does

| Resource | Type | Purpose |
|---|---|---|
| `aa-shinaka-web` | Web (Docker) | Django + Gunicorn, public HTTPS |
| `aa-shinaka-worker` | Worker (Docker) | Celery: order expiry, reconciliation, notifications, reports |
| `aa-shinaka-beat` | Worker (Docker) | Celery beat scheduler — **exactly one instance** |
| `aa-shinaka-redis` | Key Value | Cache (rate limiting) + Celery broker/results |
| `aa-shinaka-db` | Postgres 16 | Application database |

Everything is pinned to **frankfurt** (closest Render region to Nigeria) so all
resources share the private network.

* **`render.yaml`, not `render.yml`.** Render auto-detects `render.yaml`; any
  other filename requires setting the *Blueprint Path* in the dashboard.
* **`DJANGO_SECRET_KEY` is prompted.** Render's "generate value" is 44
  characters, but `config.settings.prod` rejects anything shorter than 50, so
  the key is `sync: false` on web and shared to worker/beat with `fromService`.
* **Gunicorn binds `$PORT`.** `deploy/gunicorn.conf.py` uses `GUNICORN_BIND`
  when set, otherwise `0.0.0.0:$PORT` (Render defaults `PORT` to `10000`).
* **Migrations run once.** Paid: via `preDeployCommand`, with every service on
  `RUN_MIGRATIONS=false`. Free: from the entrypoint, since pre-deploy commands
  are not available. Static files are always collected in the web entrypoint.
* **`DB_SSLMODE_REQUIRE=true`.** Render's internal Postgres supports TLS with
  self-signed certificates; `sslmode=require` encrypts without CA verification.
* **`/healthz/`** is the health check. Render treats `2xx`/`3xx` as healthy, so
  the HTTPS redirect does not break it. The view runs `SELECT 1`, and only
  reveals the exception text while `DEBUG=True`.

---

## Environment variables

Everything is environment-driven; no secret is committed. `.env.example` is the
template for local use.

### Render-injected (do not set these by hand)

| Variable | Meaning |
|---|---|
| `RENDER` | `true` on Render. |
| `PORT` | Public HTTP port (default `10000`); Gunicorn binds it. |
| `RENDER_EXTERNAL_HOSTNAME` | The service's `onrender.com` hostname. `prod.py` appends it to `DJANGO_ALLOWED_HOSTS`. |
| `RENDER_EXTERNAL_URL` | `https://<service>.onrender.com`. `prod.py` adds it to `CSRF_TRUSTED_ORIGINS`. |

### Non-secret settings

Set as Blueprint defaults and editable in the file or the environment group:
`DJANGO_SETTINGS_MODULE`, `DJANGO_DEBUG=false`, `DJANGO_ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `GUNICORN_*`, `FORWARDED_ALLOW_IPS`,
`DB_CONN_MAX_AGE`, `DB_ATOMIC_REQUESTS`, `DB_SSLMODE_REQUIRE`, `CELERY_ENABLED`,
transport-security values (`DJANGO_SECURE_SSL_REDIRECT`,
`DJANGO_SECURE_HSTS_SECONDS`, `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`,
`DJANGO_SECURE_HSTS_PRELOAD`, `USE_X_FORWARDED_HOST`, `WHITENOISE_MAX_AGE`),
rate-limit and MFA windows, `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL`,
`OPS_EMAIL`, upload-scan values, order/analytics values and the Paystack flags.

### Secrets (prompted once, `sync: false`)

| Variable | Notes |
|---|---|
| `DJANGO_SECRET_KEY` | ≥ 50 characters. `python -c "import secrets; print(secrets.token_urlsafe(64))"`. |
| `SCHEDULED_JOBS_TOKEN` | Free profile only. ≥ 32 characters; enables the jobs endpoint. |
| `RESEND_API_KEY` | Free profile only. Resend HTTPS API key. |
| `EMAIL_HOST_PASSWORD` | Paid profile only, and only if the SMTP relay authenticates. |

`DATABASE_URL`, `CACHE_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` are
wired from the managed Postgres/Key Value resources — never typed in.

---

## Database

* `DATABASE_URL` is parsed by `django-environ`; both `postgres://` and
  `postgresql://` work, and a `?sslmode=…` query parameter is passed through as
  a psycopg option. `connect_timeout=10` and `sslmode=require` are merged in
  with `setdefault`, so an explicit value in the URL always wins.
* Use the **internal** connection string (the Blueprint does). External
  connections are slower and require `sslmode=require`; Render rejects
  `sslmode=disable` for them.
* Connectivity is checked two ways: `manage.py verify_deployment` (read-only)
  and `/healthz/` (runs `SELECT 1`). A broken database returns `503`.
* `DB_CONN_MAX_AGE=600` keeps connections warm; the free Postgres plan allows
  100 connections, far above a Gunicorn worker's needs.

## Redis, Celery and periodic jobs

* `CACHE_URL` must be a `redis://` / `rediss://` URL in production; `prod.py`
  refuses anything else. It backs rate limiting, MFA and the jobs throttle.
* Celery uses the same Key Value instance for broker and results. Result values
  expire after one day (`CELERY_RESULT_EXPIRES`) to protect small instances.
* Reliability when a worker *is* deployed: `acks_late`, `reject_on_worker_lost`,
  `prefetch=1`, infinite broker reconnection. A task whose worker is `SIGKILL`ed
  during a deploy is requeued, not lost.
* When **no worker** is deployed, set `CELERY_ENABLED=false`; dispatch happens
  inline. Nothing is silently queued.

### Scheduled jobs fallback

Celery beat runs these; without beat they must be triggered externally. Both
entry points call the same idempotent functions:

```bash
python manage.py run_scheduled_jobs            # human-readable
python manage.py run_scheduled_jobs --json     # for logs/parsers
python manage.py run_scheduled_jobs --fail-on-error
```

```
POST https://<service>.onrender.com/internal/scheduled-jobs/
X-Scheduled-Jobs-Token: <SCHEDULED_JOBS_TOKEN>
```

The endpoint is disabled (404) when no token is configured, requires an exact
constant-time token match (403 otherwise), accepts `POST` only (405), and is
throttled via the cache (`SCHEDULED_JOBS_MIN_INTERVAL`, default 60s → 429). Jobs
run: order-reservation expiry, payment reconciliation (skipped while Paystack is
disabled), training reminders, scheduled reports, export cleanup and pending
notification delivery. One failing job never stops the others; partial failure
returns `207`. In production the token must be at least 32 characters or the app
refuses to start.

Point cron-job.org (or any HTTPS cron) at it every 15–30 minutes. On the free
plan this also wakes the sleeping service.

## Email

* Paid plans can use SMTP (`EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`).
* **Render Free blocks outbound SMTP.** Use the dependency-free HTTPS backend:

  ```dotenv
  EMAIL_BACKEND=config.email_backends.ResendEmailBackend
  RESEND_API_KEY=re_...
  DEFAULT_FROM_EMAIL=AA Shinaka <no-reply@your-verified-domain>
  ```

  `config.settings.prod` refuses the Resend backend without a key and still
  rejects console/locmem/dummy backends. The backend sends via
  `https://api.resend.com/emails`, supports HTML alternatives and attachments,
  and logs only the exception type/HTTP status — never recipients, bodies or the
  key. SendGrid/Postmark/Mailgun offer equivalent APIs if you prefer another
  provider.

## Media files

Container filesystems are **ephemeral** on Render: uploaded files (product
images, documents, quarantine copies, report exports) are lost on every
deploy/restart, and are not shared between the web service and any worker.

* `DJANGO_MEDIA_ROOT` (blank by default → `<repo>/media`) lets you point media at
  an absolute path so a **persistent disk** can be mounted (`/app/media`, or
  `/var/lib/aa-shinaka/media`).
* A disk is single-service, disables zero-downtime deploys, and is **not
  available on Free**.
* Recommended past a demo/single instance: **object storage** (S3-compatible /
  Cloudinary). `STORAGES["default"]` is a plain `FileSystemStorage`, so switching
  requires a storage backend and credentials — see `docs/ARCHITECTURE.md`.
* Because upload bytes are re-checked on download, losing a quarantined file
  makes its download fail closed. Database rows that reference vanished files
  must be cleaned up after a deploy.

## Error handling

`templates/500.html` is intentionally **self-contained**: no template
inheritance, no context variables, no `{% %}` tags, no static-file lookups and no
database access (inline CSS only). A 500 is often caused by a database or
static-manifest failure, so the error page must render when those are broken. The
previous version extended `base.html`, which made the error page itself able to
fail and mask the original exception.

The original exception is logged separately by Django's `django.request` logger
(level `ERROR` in `config.settings.prod`), with the full traceback in the
structured JSON output. `request` context is logged as JSON. The 500 page is
therefore a user-facing fallback; the real cause is always in the logs. `400`,
`403` and `404` still extend `base.html` (they render under normal request
context) and are covered by regression tests.

## Static files

Static assets are compiled to `static/css/app.css` by Tailwind and collected
into `STATIC_ROOT` (`staticfiles/`), then served by **WhiteNoise** with
`CompressedManifestStaticFilesStorage`. The manifest (`staticfiles.json`) is
required at request time: if collection never runs, every page that uses
`{% static %}` raises `ValueError: Missing staticfiles manifest entry` and
returns HTTP 500.

Two build paths produce the manifest, and both fail loudly if a step breaks:

* **Docker (`render.yaml`, paid):** the `assets` stage compiles the CSS and the
  web entrypoint (`deploy/entrypoint.sh`) runs `collectstatic` before Gunicorn.
* **Native Python runtime (`render.free.yaml`, and any dashboard-built Python
  service):** Render runs `./build.sh` as the **build command**, which installs
  Python and Node dependencies, compiles Tailwind, runs
  `collectstatic` under `config.settings.prod` and verifies that
  `staticfiles/staticfiles.json` contains `css/app.css`. `./start.sh` then
  applies migrations (idempotent) and execs Gunicorn.

`build.sh` is strict (`set -euo pipefail`) and checks its own outputs, so a
missing CSS bundle or manifest fails the deploy instead of surfacing as a 500.

> **Native runtime build command / start command (exact values):**
>
> * Build command: `./build.sh`
> * Start command: `./start.sh gunicorn config.wsgi:application --config deploy/gunicorn.conf.py`

> **If a service is already deployed on the native Python runtime and 500s with
> `Missing staticfiles manifest entry for 'css/app.css'`,** Render's auto
> build command never ran `collectstatic`. In the Render Dashboard open the
> service, go to **Settings → Build & Deploy**, and set the commands above
> (Build Command `./build.sh`; Start Command
> `./start.sh gunicorn config.wsgi:application --config deploy/gunicorn.conf.py`),
> then trigger **Manual Deploy → Deploy latest commit**. No code change is
> needed beyond the ones already in this repo.

---

## Setup (paid `render.yaml`)

1. **New → Blueprint**, connect the GitHub repo, branch `master`. Render reads
   `render.yaml`.
2. Provide the prompted secrets: `DJANGO_SECRET_KEY` (≥ 50 chars) and, if your
   relay authenticates, `EMAIL_HOST_PASSWORD`.
3. Apply. Render provisions Postgres, Key Value and the three services, runs
   migrations once, collects static files and starts Gunicorn.

## Setup (free `render.free.yaml`)

1. **New → Blueprint**, then set **Blueprint Path** to `render.free.yaml`.
2. Provide the prompted secrets: `DJANGO_SECRET_KEY`, a ≥ 32-character
   `SCHEDULED_JOBS_TOKEN` and a `RESEND_API_KEY`.
3. Apply. `build.sh` compiles CSS and collects static files during the build;
   `start.sh` migrates and starts Gunicorn.
4. Create an account with the `onrender.com` cron-job.org schedule above.

> **Not using a Blueprint?** Create the service as a **Python 3** web service and
> set the Build/Start commands exactly as shown in
> [Static files](#static-files). Rendering's Python runtime includes Node/npm,
> so `build.sh` can compile Tailwind.

## After the first deploy (both profiles)

1. **Check the web URL.** If Render suffixed the subdomain, `prod.py` already
   trusts the real hostname and URL, but update `SITE_URL` (and `DEFAULT_FROM_EMAIL`
   links) so outbound email points at the right place.
2. **Replace every `# EDIT` placeholder** (hosts/origins, `SITE_URL`, email
   addresses/provider) in the Blueprint file or the environment group; Blueprint
   values are re-applied on each sync.
3. **Add a custom domain** in *Settings → Custom Domains*, then add it to
   `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` (`https://…`) and set
   `SITE_URL`.
4. **Create the owner account** from the web service *Shell* tab (paid only):
   `python manage.py createsuperuser`. On free, create it with a one-off
   management action or seed command reachable from the app.
5. **Run the verifier** and confirm no `FAIL`:
   ```bash
   python manage.py verify_deployment
   ```

## Verification checklist

Run locally with safe, non-secret values before syncing:

```bash
npm ci && npm run build:css                # produces static/css/app.css
uv run python manage.py check --deploy     # with DJANGO_SETTINGS_MODULE=config.settings.prod
uv run python manage.py collectstatic --noinput
uv run python manage.py run_scheduled_jobs --json
uv run pytest -q
```

`collectstatic` under production settings requires the compiled stylesheet, so
build the CSS first (or run `./build.sh`, which does both).

`check --deploy` should report no `ERROR`-level issues; the only expected warning
is HSTS preload being off by design (`DJANGO_SECURE_HSTS_PRELOAD=false`).

---

## Deployment readiness report

A full task-by-task audit (database, cache, hosts, error handling, Celery,
payments, media, email, HTTPS, static files, tests, `check --deploy` and the
environment variables) is in
[`RENDER_DEPLOYMENT_READINESS_REPORT.md`](RENDER_DEPLOYMENT_READINESS_REPORT.md).
Summary:

### Confirmed fixes

0. **`collectstatic` no longer aborts the deploy.** WhiteNoise's manifest storage
   parsed the Tailwind *source* (`@import "tailwindcss"`) as a missing file URL;
   the source now lives outside the collected `static/` tree in
   `assets/css/app.css`.
1. **500 page cannot crash.** `templates/500.html` is context-free, tag-free and
   database-free; regression tests render it with zero queries.
2. **Original 500 is identifiable.** `django.request` logs the exception with a
   traceback independently of the error page.
3. **Host header false-400s removed.** `prod.py` appends
   `RENDER_EXTERNAL_HOSTNAME` / `RENDER_EXTERNAL_URL` to hosts and CSRF origins.
4. **Health probes honour HTTPS.** Both the Dockerfile and Compose health checks
   send `X-Forwarded-Proto: https` (so `SECURE_SSL_REDIRECT` no longer makes the
   container look unhealthy) and read `$PORT`.
5. **Gunicorn follows `$PORT`** unless `GUNICORN_BIND` is set.
6. **No silent task loss.** Notification dispatch already fell back to inline;
   `CELERY_ENABLED=false` extends that to every `.delay()`, and Celery now uses
   `acks_late` / `reject_on_worker_lost` / `prefetch=1`.
7. **Periodic jobs survive without beat.** `run_scheduled_jobs` command plus a
   token-protected, throttled HTTP endpoint, with a documented external cron.
8. **HTTPS email option shipped.** `ResendEmailBackend` (stdlib only) plus a
   production guard that requires a key when it is selected.
9. **Ephemeral media documented and made configurable** via `DJANGO_MEDIA_ROOT`.
10. **`/healthz/` no longer leaks database errors** unless `DEBUG=True`.
11. **Free-profile Blueprint added** (`render.free.yaml`) without touching the
    paid production Blueprint.
12. **Native-runtime 500 fixed.** The live service runs Render's auto-detected
    Python build, which never ran `collectstatic`, so the manifest was missing
    and every `{% static %}` page raised. `build.sh` (build command) compiles
    Tailwind and collects static files with production settings and verifies the
    manifest; `start.sh` (start command) migrates and execs Gunicorn. Both the
    free Blueprint and any dashboard-created Python service can use them.

### Remaining blockers (need people/credentials, not code)

1. **Free Postgres expires after 30 days** — not suitable for real data. Upgrade
   to a paid database (or use the paid Blueprint) before storing anything.
2. **Free web services sleep and cold-start**; the external cron wakes them, but
   the first request after idle is slow.
3. **Media is not durable on Free, and disks are single-service on paid.**
   Object storage is the real fix.
4. **`SITE_URL`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, the email
   sender/provider and `DEFAULT_FROM_EMAIL` still contain placeholders** and must
   be set to the real domain/provider.
5. **Free plan has no Shell**, so `createsuperuser` must be run another way.
6. **Nothing is deployed by this change** — no VPS, DNS, TLS or live Paystack
   credential has been touched, and `verify_deployment` has not been run against
   a real Render environment.

### Exact deployment instructions

Paid: create the Blueprint from `render.yaml`, supply `DJANGO_SECRET_KEY` (≥ 50)
and optionally `EMAIL_HOST_PASSWORD`, approve, then run step 1–5 of
*After the first deploy*.

Free: create the Blueprint with **Blueprint Path** `render.free.yaml`, supply
`DJANGO_SECRET_KEY`, `SCHEDULED_JOBS_TOKEN` (≥ 32) and `RESEND_API_KEY`, approve,
then add the cron-job.org POST schedule and finish *After the first deploy*.

---

## Scope

These Blueprints are configuration only. They do **not** deploy to or replace the
VPS stack in `deploy/`, change DNS or issue certificates, enable live Paystack
credentials, or mark the deployment production-approved — that remains an owner
decision, recorded in [`PRODUCTION_LAUNCH_APPROVAL.md`](PRODUCTION_LAUNCH_APPROVAL.md).

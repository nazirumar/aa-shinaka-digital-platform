# Deployment Readiness Report — Render Free Stabilization

**Scope:** audit and stabilize the Django application so it deploys reliably to
**Render's Free plan** without weakening production security.

**Status:** configuration, code and tests delivered, plus a follow-up fix for the
first live deploy (the native-Runtime build never produced the static manifest, so
every page 500'd; `build.sh`/`start.sh` now supply the build and start commands).
The follow-up changes are committed but **not yet redeployed**. No DNS was changed
and no live payment credential was enabled. Live gates (a real Render account, a
real `onrender.com` hostname and a real email sender) remain **NOT VERIFIED**.

See [`RENDER_DEPLOYMENT.md`](RENDER_DEPLOYMENT.md) for the operator walkthrough.

---

## 1. Database — `DATABASE_URL` parsing and PostgreSQL connectivity

* `DATABASE_URL` is parsed by `django-environ`; `postgres://` and
  `postgresql://` both work, percent-encoded credentials are decoded, and a
  `?sslmode=…` query parameter is passed through as a psycopg option.
* `connect_timeout=10` and `sslmode=require` (unless `DB_SSLMODE_REQUIRE=false`)
  are merged in with `setdefault`, so an explicit URL value always wins.
* Connectivity is verified two ways: `manage.py verify_deployment` (read-only)
  and `/healthz/`, which runs `SELECT 1` and returns `503` when the database is
  unreachable.
* **Verified by test** (`tests/test_render_deployment.py`): URL parsing, password
  decoding, `sslmode` passthrough and the `DB_SSLMODE_REQUIRE=false` escape.
* `psycopg[binary]>=3.2` (3.3.6 installed) is a declared dependency.

## 2. Cache and Redis dependencies

* `CACHE_URL` resolves through `env.cache`; both `redis://` and `rediss://` map
  to Django's built-in `django.core.cache.backends.redis.RedisCache`.
* `config.settings.prod` **refuses anything that is not a Redis URL** — locmem
  cannot work across processes.
* `redis>=5.2` (6.4.0 installed) and `celery[redis]>=5.4` are declared, so the
  cache backend and broker both have their driver.
* **Verified by test**: the cache backend name contains `redis`.

## 3. `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`

* `DJANGO_ALLOWED_HOSTS` is required and `"*"` is rejected.
* `config.settings.prod` now appends Render's injected
  `RENDER_EXTERNAL_HOSTNAME` to `ALLOWED_HOSTS` and `RENDER_EXTERNAL_URL` to
  `CSRF_TRUSTED_ORIGINS`, so a generated `onrender.com` subdomain never causes a
  400 — without relaxing the wildcard ban or the https-only rule.
* **Verified by test**: the hostname/URL are trusted and an origin is not
  duplicated when it is already configured.

## 4. Custom HTTP 500 template

* `templates/500.html` is now fully standalone: **no** inheritance, **no**
  context variables, **no** template tags, **no** static-file lookups and **no**
  database access (inline CSS only). A 500 is often caused by a database or
  static-manifest failure, so the page must render when those are broken.
* **Verified by test**: the file contains no `{{`, `{%` or `extends`, and it
  renders with an empty context while issuing **zero** database queries.

## 5. The original 500 exception

* The original exception is logged independently of the error page: Django's
  `django.request` logger records the exception **with its traceback**, at
  `ERROR` level in production.
* **Verified by test**: a view raising `RuntimeError("original-boom")` produces a
  `500`, the standalone page, and a log record whose formatted message is
  `Internal Server Error …`, whose `exc_info` contains `original-boom`, and whose
  `status_code` is `500`.

## 6. Celery tasks and silent loss of business-critical work

* Only two dispatch categories use `.delay()`: notification delivery (which
  **already** fell back to inline delivery on failure) and report exports.
* **New `CELERY_ENABLED` (default `true`).** When `false`,
  `CELERY_TASK_ALWAYS_EAGER=True`, so `.delay()` runs inline. This is the free
  plan's mode: work still happens instead of being queued to a broker that no
  process consumes (and that loses data on restart — free Key Value is in-memory).
* **New reliability flags** for when a worker *is* deployed: `acks_late`,
  `reject_on_worker_lost`, `prefetch=1`, broker reconnect-on-startup and
  `CELERY_RESULT_EXPIRES=86400`. A task whose worker is killed during a deploy is
  requeued, not dropped.
* **New `run_scheduled_jobs`** command and a token-protected, cache-throttled
  `POST /internal/scheduled-jobs/` endpoint run the same idempotent functions
  Celery beat runs (order expiry, payment reconciliation, training reminders,
  scheduled reports, export cleanup, notification delivery). Payment
  reconciliation is skipped while Paystack is disabled.
* **Verified by test**: eager inline mode, the reliability flags, the command,
  and the endpoint's disabled/bad-token/GET/success/throttle behaviour.

## 7. Paystack live payments remain disabled

* `PAYSTACK_ENABLED=false` and `PAYSTACK_LIVE_MODE=false` in both Blueprints;
  the test environment and the `.env` template keep them off.
* **Verified by test**: production settings resolve both flags to `False`.

## 8. Uploaded media and the ephemeral filesystem

* Container filesystems on Render are **ephemeral**: uploads are lost on every
  deploy/restart and are not shared between web and worker. This is a hard limit
  on Free (no disks at all) and disks are single-service on paid.
* `MEDIA_ROOT` is now overridable via `DJANGO_MEDIA_ROOT` so a persistent disk
  can be mounted; an empty value safely falls back to `<repo>/media`.
* Recommended past a single-instance demo: object storage (S3-compatible /
  Cloudinary). `STORAGES["default"]` is a plain `FileSystemStorage`, so this is a
  configuration change, not a code change.
* **Verified by test**: the media root follows `DJANGO_MEDIA_ROOT`.

## 9. Email — SMTP and a supported HTTPS option

* Paid plans can use SMTP. **Render Free blocks outbound SMTP (25/465/587).**
* New `config.email_backends.ResendEmailBackend` delivers over Resend's HTTPS API
  using **only the standard library** (no new dependency). It supports HTML
  alternatives and attachments and logs only the exception type/HTTP status —
  never recipients, bodies or the key.
* `config.settings.prod` rejects console/locmem/dummy backends; it now requires
  `EMAIL_HOST` only for the SMTP backend and `RESEND_API_KEY` for the API
  backend. SendGrid/Postmark/Mailgun are equivalent alternatives.
* **Verified by test**: the key requirement, acceptance with a key, the posted
  payload/headers, and non-silent failure handling.

## 10. HTTPS proxy handling, secure cookies and HSTS

* `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` — Render's
  proxy sets this header, so Django knows the request is HTTPS.
* `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
  `SECURE_HSTS_SECONDS` and the HSTS subdomain flag are on; HSTS preload is
  deliberately off until the domain is verified.
* **Fixed:** the Dockerfile and Compose health checks now send
  `X-Forwarded-Proto: https` and read `$PORT`, so `SECURE_SSL_REDIRECT` no longer
  makes the container look unhealthy. Gunicorn binds `$PORT` when
  `GUNICORN_BIND` is unset.
* **Verified by test**: `check --deploy --fail-level ERROR` passes with a
  Render-like environment, and the transport-security settings resolve as
  intended.

## 11. Static files and the WhiteNoise manifest

* **Found and fixed a real deploy blocker.** WhiteNoise's
  `CompressedManifestStaticFilesStorage` parses every collected `.css` file; the
  Tailwind **source** `static/src/app.css` contains `@import "tailwindcss"`,
  which it interpreted as a missing file URL `src/tailwindcss`, aborting
  `collectstatic` — and therefore the container entrypoint on Render and the VPS.
* The source now lives in `assets/css/app.css`, **outside** the collected
  `static/` tree. `package.json`, `deploy/Dockerfile`, `.gitignore`, the docs and
  two tests follow it.
* **Verified by hand and by test**: `collectstatic` under production settings
  copies 129 files, post-processes 385, writes `staticfiles.json`, hashes
  `static/css/app.css` and collects **no** source. The manifest storage backend
  is asserted by test.
* **Follow-up fix: the native-Render 500.** The live service runs Render's
  auto-detected Python build/start commands, not the Docker entrypoint, so
  `collectstatic` never ran and `staticfiles.json` was missing — every page
  raised `ValueError: Missing staticfiles manifest entry for 'css/app.css'`. The
  native runtime now uses `build.sh` (compile CSS → `collectstatic` → verify the
  manifest contains `css/app.css`) as the build command and `start.sh` (migrate →
  exec Gunicorn) as the start command. `render.free.yaml` carries both; the CI
  test job builds the CSS so the regression test runs against the real asset.

## 12. Regression tests

* New `tests/test_render_deployment.py` (29 tests) covers the database URL
  parsing/SSL options, Redis cache + WhiteNoise manifest, Render host/CSRF trust,
  transport security, the Paystack kill switch, the Celery fallback (eager +
  reliability), the sentinel-token guard, the Resend backend, the crash-proof 500
  page, the original-exception logging, the scheduler command/endpoint, the
  media-root override, the `build.sh`/`start.sh` contents and rendering the
  public and staff layouts with `DEBUG=False` under the real
  `CompressedManifestStaticFilesStorage` (the exact production failure mode).
* Existing theme/sidebar tests were updated to the new Tailwind source path.

## 13. `check --deploy` with production settings

Run with safe, non-secret values:

```
$ DJANGO_SETTINGS_MODULE=config.settings.prod python manage.py check --deploy
System check identified 2 issues (0 silenced).

WARNINGS:
?: (security.W009) Your SECRET_KEY has less than 50 characters …   # fake test key artefact
?: (security.W021) You have not set the SECURE_HSTS_PRELOAD setting to True. …
```

* **No `ERROR`-level issues.** `W021` is the deliberate
  `DJANGO_SECURE_HSTS_PRELOAD=false` choice; `W009` is an artefact of the short,
  low-entropy placeholder key used only for this local check.
* `manage.py check` and `makemigrations --check --dry-run` are both clean.

## 14. Render environment variables

Documented without exposing secrets in [`RENDER_DEPLOYMENT.md`](RENDER_DEPLOYMENT.md):
the Render-injected variables (do not set by hand), the non-secret settings, and
the prompted secrets (`DJANGO_SECRET_KEY` ≥ 50 chars, `SCHEDULED_JOBS_TOKEN`
≥ 32 chars, `RESEND_API_KEY`, optional `EMAIL_HOST_PASSWORD`). Connection URLs
come from the managed resources — never typed in.

---

## Test status

| Command | Result |
|---|---|
| `uv run ruff check .` | **PASS** (all checks passed) |
| `uv run ruff format --check .` | **PASS** (340 files already formatted) |
| `uv run pytest` | **961 passed, 1 failed** |
| `uv run python manage.py check` | **PASS** (no issues) |
| `uv run python manage.py makemigrations --check --dry-run` | **PASS** (no changes) |

The single failure is
`tests/test_phase15_deploy.py::test_render_nginx_script_renders_the_local_config`:
a `timeout=60` on a `bash` subprocess that runs in ~30 s in isolation but exceeds
60 s under full-suite load on Windows. It **passes when run alone**, touches
files this change does not modify (it renders nginx fixtures into a temp repo and
never reads `render.yaml`), and is a pre-existing environmental flake, not a
regression.

---

## Confirmed fixes

1. `collectstatic` (and therefore the container entrypoint / Render deploy) no
   longer aborts on the Tailwind source.
2. `templates/500.html` renders with no context, tags, static lookups or queries.
3. The original 500 exception is always logged with its traceback.
4. Render's injected hostname/URL are auto-trusted without weakening the guards.
5. Docker/Compose health probes honour HTTPS and `$PORT`; Gunicorn follows
   `$PORT`.
6. No silent loss of business-critical work when no worker runs
   (`CELERY_ENABLED=false`, inline) and no silent loss when one does
   (`acks_late`, `reject_on_worker_lost`, prefetch 1).
7. Periodic jobs survive without beat (command + token-protected endpoint).
8. HTTPS email delivery option shipped and guarded.
9. Media root is configurable for a persistent disk; the ephemeral risk is
   documented.
10. `/healthz/` no longer leaks database errors unless `DEBUG=True`.
11. A free-tier Blueprint was added without touching the paid production one.

## Remaining blockers (people/credentials, not code)

1. **Free Postgres is deleted 30 days after creation** — upgrade before storing
   real data.
2. **Free web services sleep after 15 minutes**; the external cron wakes them but
   the first request is slow.
3. **Media is not durable on Free** (and disks are single-service on paid);
   object storage is the real fix.
4. **Placeholders remain** in `SITE_URL`, `DJANGO_ALLOWED_HOSTS`,
   `CSRF_TRUSTED_ORIGINS`, the email sender/provider and `DEFAULT_FROM_EMAIL`.
5. **Free has no Shell**, so `createsuperuser` must be run another way.
6. **Nothing was deployed**, no DNS changed, no live Paystack credential used;
   `verify_deployment` has not run against a real Render environment.

## Exact deployment instructions

**Paid (`render.yaml`):** New → Blueprint, connect the repo (branch `master`),
supply `DJANGO_SECRET_KEY` (≥ 50 chars) and optionally `EMAIL_HOST_PASSWORD`,
Apply, then complete the post-deploy checklist (set real host/origin, `SITE_URL`
and email values; add a custom domain; create the owner account; run
`verify_deployment`).

**Free (`render.free.yaml`):** New → Blueprint, set **Blueprint Path** to
`render.free.yaml`, supply `DJANGO_SECRET_KEY`, a ≥ 32-char
`SCHEDULED_JOBS_TOKEN` and a `RESEND_API_KEY`, Apply, add a cron-job.org schedule
posting to `https://<service>.onrender.com/internal/scheduled-jobs/` with the
`X-Scheduled-Jobs-Token` header every 15–30 minutes, then complete the same
checklist.

This report is configuration and verification only. It does not mark the
deployment production-approved; that remains an owner decision recorded in
[`PRODUCTION_LAUNCH_APPROVAL.md`](PRODUCTION_LAUNCH_APPROVAL.md).

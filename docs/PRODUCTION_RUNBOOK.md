# Production Runbook — AA Shinaka Digital Business Platform

**Phase:** 12. Audience: the operator on call. Nothing here deploys
automatically and nothing changes DNS or enables live Paystack credentials.

> Companion documents: `docs/DISASTER_RECOVERY.md`, `docs/MONITORING.md`,
> `docs/RELEASE_CHECKLIST.md`, `docs/PRODUCTION_LAUNCH_PLAN.md`,
> `docs/STAGING_TEST_PLAN.md`, `docs/PRODUCTION_LAUNCH_APPROVAL.md`,
> `deploy/README.md`.

> **Phase 14 tooling.** Pre-deploy and verification are largely automated now:
> `deploy/scripts/validate_env.sh` (env safety), `preflight.sh` (non-destructive
> gate), `smoke_test.sh` (post-deploy HTTP checks), `verify_host.sh` (TLS/headers/
> media-deny/ports), `restore_drill.sh` (isolated restore rehearsal) and
> `manage.py verify_deployment` (environment/DB/security report). Staging uses
> `deploy/docker-compose.staging.yml` + `.env.staging` with
> `DJANGO_SETTINGS_MODULE=config.settings.staging` (test-mode Paystack only).

---

## 1. Topology

```
client ──TLS──▶ nginx (deploy/nginx/aa-shinaka.conf) ──▶ Gunicorn (web:8000)
                                   │                         │
                                   │                         ├─ PostgreSQL
                                   └── static / media        ├─ Redis (cache + Celery broker)
                                                             ├─ Celery worker
                                                             └─ Celery beat
```

Two supported installations: **Docker Compose** (`deploy/docker-compose.yml`) or
**bare metal** (`deploy/systemd/*.service` + nginx). Pick one per environment.

---

## 2. First-time provisioning

1. Provision a Linux host (Ubuntu LTS), create a non-root deploy user.
2. Install Docker + Compose, **or** Python 3.12 + `uv`, `nginx`, PostgreSQL and
   Redis for the bare-metal path.
3. `cp deploy/.env.production.example deploy/.env.production` and fill **every**
   value. Generate the secret with:
   `uv run python -c "import secrets; print(secrets.token_urlsafe(64))"`.
4. Point the application's DNS record at the host (owner-approved domain only).
5. Issue TLS certificates; place `fullchain.pem` / `privkey.pem` under
   `deploy/nginx/certs/`.
6. Bring the stack up and run the one-time commands:

   ```bash
   docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml up -d --build
   docker compose -f deploy/docker-compose.yml exec web python manage.py sync_roles
   docker compose -f deploy/docker-compose.yml exec web python manage.py createsuperuser
   uv run python manage.py import_nigeria_locations --source <file>   # 37 states + 774 LGAs
   ```

---

## 3. Routine operations

| Task | Command |
|---|---|
| Deploy a new release | `./deploy/scripts/deploy.sh` (backup → build → migrate → collectstatic → restart → smoke) |
| Health check | `BASE_URL=https://DOMAIN ./deploy/scripts/healthcheck.sh` |
| Restart web | `docker compose -f deploy/docker-compose.yml restart web` |
| Restart workers | `docker compose -f deploy/docker-compose.yml restart worker beat` |
| Tail logs | `docker compose -f deploy/docker-compose.yml logs -f web` |
| Apply migrations | `docker compose ... exec web python manage.py migrate` |
| Refresh role groups | `docker compose ... exec web python manage.py sync_roles` |
| Backup now | `./deploy/scripts/backup.sh` |
| Expire stale orders | Celery beat runs it; manually: `... exec web python manage.py shell -c "from apps.orders.services import expire_orders; print(expire_orders())"` |

---

## 4. Deploy procedure (standard)

1. Confirm CI is green on the release commit (`.github/workflows/ci.yml`).
2. Take a verified backup (`./deploy/scripts/backup.sh`).
3. Tag the release (`docs/RELEASE_CHECKLIST.md`).
4. Run `./deploy/scripts/deploy.sh`. It refuses to continue if checks or
   migrations fail.
5. Watch logs for 5 minutes; run the health check; smoke test login + a test-mode
   checkout.
6. If anything is wrong, **roll back** (below) rather than debugging in place.

### Rollback

- **Code:** redeploy the previous git tag (migrations are additive; do not
  reverse a migration unless it is explicitly reversible and reviewed).
- **Database:** restore the pre-deploy backup into an isolated DB, verify, then
  cut over (`docs/DISASTER_RECOVERY.md` §4).
- Record the incident and root cause.

---

## 5. Security operations

### Secret rotation

| Secret | Impact of rotation | Steps |
|---|---|---|
| `DJANGO_SECRET_KEY` | All sessions and outstanding password-reset/verification tokens are invalidated | update env → restart web/worker/beat |
| `DATABASE_URL` password | none if coordinated | rotate in Postgres, update env, restart |
| `PAYSTACK_SECRET_KEY` | payment initialisation/webhook verification use the new key | update env, restart, send a test webhook |
| `EMAIL_HOST_PASSWORD` | none | update env, restart worker |
| TLS certificate | none | renew via certbot/ACM, reload nginx |

### HSTS preload

`SECURE_HSTS_PRELOAD` is **off** by default because preload is hard to undo.
Enable it only after **all** subdomains are permanently HTTPS, then submit to
hstspreload.org. Keep `SECURE_HSTS_SECONDS` at 30 days for the controlled launch.

### Media access check (must pass on the host)

```bash
curl -sI https://DOMAIN/media/<some-private-file>   # expect 403 or 404
curl -sI https://DOMAIN/static/css/app.css          # expect 200
```

### Payments remain in test mode until approved

`PAYSTACK_ENABLED=False` for staging. The webhook kill switch (H-3) guarantees a
disabled environment records incoming webhooks as `ignored` and never settles an
order.

---

## 6. Common incidents

| Symptom | Likely cause | Action |
|---|---|---|
| 502 from nginx | Gunicorn down | restart `web`; check logs for a boot-time settings error |
| 500 on every request | bad env (e.g. `SECRET_KEY`, `ALLOWED_HOSTS`, `CACHE_URL`) | prod settings fail fast; fix the env and restart |
| `collectstatic` error about manifest | missing hashed file | rebuild assets (`npm run build:css`) and redeploy |
| Orders not expiring | beat not running | restart `beat`; verify `expire_orders` in logs |
| Emails not delivered | SMTP credentials | check `EMAIL_*`; console/locmem backends are rejected in prod |
| Payment webhook 401 | wrong `PAYSTACK_SECRET_KEY`/webhook secret | fix key, replay the event from the Paystack dashboard |
| Payment captured but order not confirmed | late/duplicate capture on cancelled/expired order | finance review queue (`requires_review`) — refund or reinstate |

---

## 7. On-call checklist (daily)

- [ ] `healthcheck.sh` green; disks not near full.
- [ ] Last night's backup exists, is non-zero and passed verification.
- [ ] Error rate in logs normal; no repeated 500s.
- [ ] Finance: any `requires_review` payments from the last 24 h addressed.
- [ ] Celery beat queue not backing up.

---

## 8. Launch-day gates

Run `docs/RELEASE_CHECKLIST.md` plus:

- [ ] `uv run python manage.py check --deploy` clean on the host env.
- [ ] Media default-deny verified (§5).
- [ ] TLS chain valid; HTTP redirects to HTTPS.
- [ ] Backup + a **restore drill** performed on staging.
- [ ] Monitoring/alerting configured (`docs/MONITORING.md`).
- [ ] `sync_roles` run; superuser created; Nigeria locations imported.
- [ ] Paystack still in test mode (live keys require explicit owner approval).

# Production Launch Plan — AA Shinaka Digital Business Platform

**Phase:** 14 (staging verification & controlled production launch)
**Applies to:** the eventual *production* deployment — a **separate, explicit
owner approval** is required before any step in §9 is executed.
**Current state:** **NOT APPROVED TO LAUNCH.** Staging execution is
**NOT VERIFIED** (no host was available — see `docs/PHASE_14_STAGING_REPORT.md`).

> Nothing in this document has been performed against production. No DNS record
> was changed, no live Paystack credential was enabled and no production data was
> migrated.

---

## 1. Domain & DNS plan

| Item | Value (owner supplies) | Notes |
|---|---|---|
| Apex domain | `EXAMPLE_DOMAIN` | owner-approved, already owned |
| `www` host | `www.EXAMPLE_DOMAIN` | CNAME to apex or same A record |
| App A record | `<host-ip>` | the production VPS/LB |
| TTL | 300 s during cutover, then 3600 s | low TTL first for fast rollback |
| Email (SPF/DKIM/DMARC) | per mail provider | required before launch emails |
| Staging host | `staging.EXAMPLE_DOMAIN` | **isolated**; never shares the prod DB/Redis |

DNS changes are made **only** at launch time, after §7's checklist is green, by
the owner or a named delegate. Keep the previous DNS answer documented for
rollback.

## 2. TLS certificate plan

1. Issue a certificate for `EXAMPLE_DOMAIN` **and** `www.EXAMPLE_DOMAIN`
   (Let's Encrypt/certbot or the host's managed certificate).
2. Install `fullchain.pem` + `privkey.pem` under `deploy/nginx/certs/`.
3. Verify with `deploy/scripts/verify_host.sh` (valid chain, HTTP→HTTPS 301,
   HSTS header present).
4. Enable auto-renewal and monitor expiry (`docs/MONITORING.md`).
5. HSTS: keep `SECURE_HSTS_SECONDS` at 30 days and `preload` **off** for the
   controlled launch; enable preload only after every subdomain is permanently
   HTTPS (see runbook §5).

## 3. Production environment configuration

- `cp deploy/.env.production.example deploy/.env.production` and fill **every**
  value (see `deploy/.env.production.example`).
- Run `./deploy/scripts/validate_env.sh deploy/.env.production` — it must pass.
- Confirm the **root `.env` file does not exist on the host**: `config/settings/
  base.py` reads a local `.env` as a *fallback*, and this repository's `.env`
  contains development values (e.g. `DJANGO_SECURE_SSL_REDIRECT=False`). Real
  environment variables (the Docker `env_file`/systemd `EnvironmentFile`) take
  precedence, but the fallback must not be present in production.
- Secrets are generated, never reused: `uv run python -c "import secrets;
  print(secrets.token_urlsafe(64))"`.
- `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS` lists the real hosts (no `*`),
  `CSRF_TRUSTED_ORIGINS` are `https://` only.

## 4. Database migration plan

1. Take a verified pre-launch backup (`deploy/scripts/backup.sh`) — §5.
2. Apply migrations with the app **not** serving traffic, or during a maintenance
   window: `manage.py migrate --noinput`. Migrations are additive.
3. `manage.py migrate --check` must exit 0 afterwards.
4. One-time provisioning on the production DB:
   - `manage.py sync_roles` (10 role groups),
   - `manage.py import_nigeria_locations --source <verified file> --strict`
     (expect 37 states + 774 LGAs),
   - `manage.py createsuperuser` (owner account, MFA enrolled immediately).
5. There is **no destructive** migration or data-replacement step. Do not run
   `flush`, `reset`, or `DROP` against production.

## 5. Backup-before-launch procedure

```bash
DATABASE_URL="$PROD_DATABASE_URL" BACKUP_DIR=/var/backups/aa-shinaka \
  ./deploy/scripts/backup.sh
# verify the archive exists, is non-zero and lists:
pg_restore --list /var/backups/aa-shinaka/aa_shinaka_<stamp>.dump | head
```

A fresh verified backup must exist immediately before any migration or launch
step. Confirm the nightly timer (`deploy/systemd/aa-shinaka-backup.timer`) is
active and off-site copy + encryption are configured.

## 6. Deployment checklist

Run `docs/RELEASE_CHECKLIST.md`, then in order:

- [ ] CI green on the release commit (`lint`, `checks`, `assets`, `test`, `security`).
- [ ] `deploy/scripts/preflight.sh deploy/.env.production` passes.
- [ ] Fresh verified backup exists (§5).
- [ ] `manage.py migrate --noinput` applied; `migrate --check` clean.
- [ ] `collectstatic` run; `static/css/app.css` served (HTTP 200).
- [ ] `sync_roles` run; locations imported; superuser created + MFA enrolled.
- [ ] `deploy/scripts/deploy.sh <tag>` completes; web/worker/beat healthy.
- [ ] `deploy/scripts/smoke_test.sh` passes.
- [ ] `deploy/scripts/verify_host.sh` passes (TLS, redirect, media deny, ports).
- [ ] `manage.py verify_deployment` reports 0 FAIL in the production env.
- [ ] Monitoring/alerting wired; a test alert delivered (`docs/MONITORING.md`).

## 7. Smoke tests (post-deploy)

`deploy/scripts/smoke_test.sh` plus a manual pass:

1. Homepage, About, Contact, News, FAQs, Services, Shop, Training render.
2. Product search + a product detail page render with live data.
3. Register a **test** customer → verify email → login → logout → password reset.
4. Add to cart → checkout (test-mode) → order visible in the portal.
5. Staff login with MFA → open the dashboard → confirm a test-mode payment.
6. Submit a support ticket and an export enquiry; confirm staff see them.
7. `/media/<private>` returns 403/404; `/static/` returns 200.

## 8. Rollback plan

- **Code:** `ROLLBACK_CONFIRM=yes ./deploy/scripts/rollback.sh <previous-tag>`
  (rebuild + restart + smoke; migrations are **not** reversed).
- **Database:** restore the pre-launch backup into an isolated DB, verify, then
  cut over (`docs/DISASTER_RECOVERY.md` §4).
- **DNS:** revert to the previous A/CNAME answer (documented in §1).
- Record the incident, timeline and root cause.

## 9. Payment activation checklist (separate approval)

Live payments are **off** by default. To enable them, *after* the owner gives a
separate written approval:

- [ ] Owner approval recorded (date, scope, who approved).
- [ ] Live Paystack account verified; business/KYC complete.
- [ ] Live secret/public keys installed as environment variables only.
- [ ] `PAYSTACK_ENABLED=True` **and** `PAYSTACK_LIVE_MODE=True` (both required —
      a live key is refused while live mode is off).
- [ ] Webhook URL registered in the Paystack dashboard with the correct secret.
- [ ] A small real end-to-end payment is made and reconciled; refund tested.
- [ ] Finance monitoring/alerting for payments confirmed.

Until every box is ticked, keep `PAYSTACK_ENABLED=False` / test keys only.

## 10. Incident response contacts

| Role | Name | Contact | Escalation |
|---|---|---|---|
| Business owner | | | final decision |
| On-call engineer | | | infra/app |
| Finance lead | | | payments/refunds |
| Hosting provider support | | | infra outage |

(Owner to complete before launch. Keep this table in the runbook the on-call
operator actually reads.)

## 11. Owner approval form

I approve the controlled production launch of the AA Shinaka Digital Business
Platform under the conditions checked above, with payments remaining in **test
mode** until a separate live-payment approval is given.

| Role | Name | Signature | Date |
|---|---|---|---|
| Business owner | | | |
| Operations | | | |
| Finance | | | |

> The consolidated go/no-go decision record is
> `docs/PRODUCTION_LAUNCH_APPROVAL.md`. This plan is the procedure; that document
> is the decision.

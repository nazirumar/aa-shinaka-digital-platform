# Staging Test Plan — AA Shinaka Digital Business Platform

**Phase:** 14. **Audience:** the engineer running the staging verification.
**Purpose:** every step below is executable on the staging host. In the Phase 14
development environment (no host) each is **NOT VERIFIED**; this plan is what
turns it into evidence. Record each result in
`docs/PHASE_14_STAGING_REPORT.md`.

> Authorised use only. Staging must be **isolated** from production (separate DB,
> Redis, media volume, hostname). Paystack stays in **test mode**.

---

## 0. Bring staging up

```bash
cp deploy/.env.staging.example deploy/.env.staging     # fill every value
./deploy/scripts/validate_env.sh deploy/.env.staging   # must pass
./deploy/scripts/preflight.sh deploy/.env.staging      # env + checks + migration guard
./deploy/scripts/staging_deploy.sh <git-ref>           # build → migrate → collectstatic → smoke
```

Record: git ref, image digest, deploy timestamp.

## 1. Database verification (Step 4)

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.staging.yml \
  exec web python manage.py verify_deployment --check-celery --json /tmp/verify.json
docker compose ... exec web python manage.py migrate --check
docker compose ... exec web python manage.py sync_roles
docker compose ... exec web python manage.py import_nigeria_locations \
  --source <verified.csv> --strict --dry-run     # then again without --dry-run
```

Expected: `verify_deployment` reports **0 FAIL**, role groups 10, locations
**37 states / 774 LGAs**. Capture the JSON. **Do not fabricate** inventory or
customer records — use only owner-approved data.

## 2. Public website testing (Step 5)

Automated: `BASE_URL=https://staging.EXAMPLE_DOMAIN ./deploy/scripts/smoke_test.sh`.

Manual (desktop / tablet / mobile — 360, 768, 1440 px):

- [ ] Homepage, About, Contact (form submit → staff enquiry visible).
- [ ] Services list + each division page; footer/nav links all resolve.
- [ ] Shop index, category, product detail, **search** (results + empty state).
- [ ] News list/detail, FAQs, CMS pages.
- [ ] Training academy list + course detail; certificate verification page.
- [ ] Export enquiry form submits and reaches the staff queue.
- [ ] `robots.txt`, `sitemap.xml` return the staging domain.
- [ ] No console errors; layouts reflow without horizontal scroll.

## 3. Customer workflow testing (Step 6)

- [ ] Register → verification email received → verify → login.
- [ ] Logout; password reset (token works, rate-limited).
- [ ] Dashboard, profile edit, address add/edit/delete.
- [ ] Cart add/update/remove (guest cart merges on login).
- [ ] Checkout (test mode): order created `pending_payment`, stock reserved.
- [ ] Order detail + tracking status history visible only to the owner.
- [ ] Payment history, invoice, receipt render; another customer cannot open them.
- [ ] Export enquiry, consultancy booking, storage booking, training enrolment.
- [ ] Support ticket create + reply; notification centre shows events.
- [ ] Document downloads work and are ownership-checked.
- [ ] **Isolation:** with customer B's session, opening customer A's URLs → 403/404.

## 4. Staff dashboard testing (Step 7)

- [ ] Staff login with a privileged account is **challenged for MFA**; wrong code
      rejected, correct TOTP accepted, a recovery code works once.
- [ ] Role permissions: e.g. a Sales Officer cannot open finance/staff management.
- [ ] Product management, inventory receive/transfer/adjust.
- [ ] Order management + fulfilment + payment approval (test mode).
- [ ] Service request handling; export destination approval + documents.
- [ ] Training course/cohort management; certificate approval.
- [ ] Support queue, assignment, status transitions.
- [ ] Analytics/report builder renders; exports download via an authorised view.
- [ ] **Negative:** GET on a state-changing action returns 405.

## 5. Paystack test mode (Step 8)

Use **test** keys only. When test credentials are supplied securely:

- [ ] Successful test payment → order `confirmed` after server verification.
- [ ] Failed payment → order stays unpaid, no settlement.
- [ ] Cancelled checkout → order unchanged.
- [ ] Duplicate webhook → idempotent (no double settlement).
- [ ] Invalid webhook signature → 401, recorded.
- [ ] Amount/currency mismatch → rejected, flagged for review.
- [ ] Expired/cancelled order + late `charge.success` → `requires_review`, not settled.
- [ ] Refund workflow `request → approve → complete`.
- [ ] `orders.reconcile_payments` finds no unexplained payments.

Without test credentials: mark **NOT VERIFIED**; the code-level contract tests
(`tests/test_orders_payments.py`, `tests/test_paystack_test_mode.py`) still apply.

## 6. Security verification (Step 9)

```bash
BASE_URL=https://staging.EXAMPLE_DOMAIN HOST=staging.EXAMPLE_DOMAIN \
  ./deploy/scripts/verify_host.sh
```

- [ ] Valid TLS chain; HTTP→HTTPS 301.
- [ ] HSTS + nosniff headers on the wire.
- [ ] `/media/<private>` → 403/404; `/static/` → 200.
- [ ] App port (8000) not publicly reachable.
- [ ] `manage.py check --deploy --fail-level ERROR` clean.
- [ ] `manage.py verify_deployment` — security checks all PASS.
- [ ] Login rate limiting triggers after the configured attempts.
- [ ] MFA enforced for privileged accounts.
- [ ] Upload scanning: an EICAR test upload is rejected and quarantined; the
      review page lists it; an authorised release is audited.
- [ ] Secrets only via env; no secret in logs or the repo.
- [ ] Database connection uses TLS (`sslmode=require`) where the host supports it.

## 7. Backup & restore (Step 10)

```bash
DATABASE_URL="$DATABASE_URL" ./deploy/scripts/backup.sh          # nightly timer
DATABASE_URL="$DATABASE_URL" \
TARGET_DATABASE_URL="postgres://.../aa_shinaka_restore_drill" \
RESTORE_DRILL_CONFIRM=yes ./deploy/scripts/restore_drill.sh
```

- [ ] Backup produced, non-zero, readable; encryption + off-site copy configured.
- [ ] Restore drill into an **isolated** DB succeeds; `migrate --check` clean.
- [ ] Record RTO (drill wall time) and RPO (backup cadence).
- [ ] Backup-failure alert fires when the backup command is forced to fail.

## 8. Monitoring (Step 11)

- [ ] `/healthz/` probed by the monitor; a forced DB outage turns it 503 and alerts.
- [ ] Error logs structured (JSON) and shipped.
- [ ] Celery worker/beat liveness monitored; a stopped worker alerts.
- [ ] Backup-failure and payment-processing alerts wired.
- [ ] Trigger a **safe test alert** and confirm delivery; record timestamp.

## 9. Performance (Step 12)

```bash
BASE_URL=https://staging.EXAMPLE_DOMAIN \
  uv run python deploy/scripts/loadtest.py \
  --duration 120 --concurrency 20 \
  --paths /,/shop/,/training/,/healthz/ \
  --json perf_staging.json
```

- [ ] Record p50/p95/p99 latency, throughput, error rate for each path.
- [ ] Test authenticated checkout latency with a scripted test account.
- [ ] Watch DB (`pg_stat_activity`), CPU and memory during the run.
- [ ] Document the capacity limit (the concurrency/load at which p95 or error
      rate becomes unacceptable).

## 10. Accessibility (Step 13)

```bash
# With a browser available (axe-core CLI or Lighthouse):
npx @axe-core/cli https://staging.EXAMPLE_DOMAIN/ --exit
npx lighthouse https://staging.EXAMPLE_DOMAIN/ --only-categories=accessibility --output=json
```

Manual WCAG 2.2 AA checks on representative public, customer and staff pages:

- [ ] Full keyboard operation (no traps); visible focus states.
- [ ] Every form control has an associated label; errors announced (`role="alert"`).
- [ ] Colour contrast ≥ 4.5:1 (text) / 3:1 (large text, UI).
- [ ] Landmarks/headings in order; images have alt text; skip link works.
- [ ] Reflows at 320 px width and 200% zoom without loss of content.
- [ ] Record issues + fixes and re-test.

## 11. Sign-off

Complete `docs/PRODUCTION_LAUNCH_APPROVAL.md`. Every item is PASSED / FAILED /
NOT VERIFIED / NOT APPLICABLE with justification. A production launch requires a
**separate explicit approval**.

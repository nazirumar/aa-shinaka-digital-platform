# Changelog

All notable changes to the AA Shinaka Digital Business Platform.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] — Phase 12: production security, QA, deployment & launch readiness

### Security

- Added `@require_POST` to ten staff dashboard actions that mutated state over
  `GET` (export destinations, export quotations/compliance; training
  categories/courses/instructors/assignments/assessments) — closes a CSRF-bypass
  path. (Audit H-1.)
- Payment webhook now honours the `PAYSTACK_ENABLED` kill switch: when payments
  are disabled the event is recorded as `ignored` and never settles an order.
  (Audit H-3.)
- Hardened settings: `CSRF_COOKIE_HTTPONLY`, `SECURE_CONTENT_TYPE_NOSNIFF`,
  `SECURE_CROSS_ORIGIN_OPENER_POLICY`, and explicit upload-size/number limits.
- Production settings rewritten to fail fast on insecure configuration
  (weak/short `SECRET_KEY`, wildcard/empty `ALLOWED_HOSTS`, non-HTTPS
  `CSRF_TRUSTED_ORIGINS`, non-Redis cache, console/locmem/dummy email backend).
- Production adds HSTS (preload off by default), secure/HttpOnly/SameSite
  cookies, `SECURE_SSL_REDIRECT`, `X-Forwarded-Proto` trust, WhiteNoise manifest
  static storage, explicit password hashers and structured JSON logging.
- nginx reference config default-denies `/media/` and allow-lists only public
  prefixes; private documents are served only through authorised Django views.
  (Audit H-2.)
- Added a 23-test production security suite (`tests/test_production_security.py`)
  covering GET-mutation rejection, auth redirects, webhook signature/kill-switch,
  duplicate-event idempotency, object-level boundaries, CSRF cookie behaviour and
  production settings fail-fast.

### Fixed

- Cancelling a **paid** order through the generic status transition now returns
  committed stock to the ledger (previously only active holds were released).
  (Audit M-1.)
- `ProductListing.primary_image` is memoised per instance, removing an N+1 on
  catalogue cards. (Audit M-2.)

### Added

- End-to-end scenario suite (`tests/test_e2e.py`): purchase → payment →
  confirmed; consultancy → quotation; export enquiry → order; training
  enrolment → payment; support ticket lifecycle; analytics report → download.
- Dedicated test settings module (`config/settings/test.py`) with fast password
  hashing, eager Celery, in-memory email and a temporary `MEDIA_ROOT`.
- Deployment assets under `deploy/` (Dockerfile, Compose stack, gunicorn config,
  entrypoint, nginx site, systemd units, backup/restore/healthcheck/deploy
  scripts, production env template) and a dependency-free load tester.
- CI pipeline (`.github/workflows/ci.yml`): lint/format, system + migration
  checks, asset build, tests with coverage, dependency audit and a production
  `check --deploy`.
- Safe error templates (`400.html`, `404.html`, `500.html`).
- Documentation: production readiness audit, disaster recovery, runbook,
  monitoring, data protection, launch content checklist, performance &
  accessibility, release checklist, and the final readiness report.
- Added `gunicorn` as a production server dependency.

### Notes

- Payments remain in **test mode**; no live credentials, DNS changes or customer
  data were introduced by this phase.
- Known accepted gaps (see the final readiness report): no MFA for privileged
  staff yet, no malware scanning, multi-warehouse reservations default to the
  single MAIN warehouse, and deployment-dependent controls (TLS, `/media/`
  deny, backups) require verification on the host.

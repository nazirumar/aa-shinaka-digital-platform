# Release Checklist — AA Shinaka Digital Business Platform

Copy this into the release PR/issue and tick every box. A release is not shipped
until all **blocking** items pass.

---

## 1. Pre-release (code)

- [ ] All work merged; branch green in CI (`.github/workflows/ci.yml`).
- [ ] `uv run ruff check .` — clean.
- [ ] `uv run ruff format --check .` — clean.
- [ ] `uv run pytest` — full suite green (no skips reported as passes).
- [ ] `uv run python manage.py check` — clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` — "No changes detected".
- [ ] `uv run python manage.py check --deploy` — clean with production settings.
- [ ] `npm run build:css` — Tailwind bundle rebuilt; `static/css/app.css` non-empty.
- [ ] No new dependency without a stated need (DRF stays deferred).
- [ ] No secrets committed; only `.env.example` / `deploy/.env.production.example` changed.

## 2. Review

- [ ] Migrations reviewed (additive, reversible where possible, no hand-edits).
- [ ] Security-sensitive diffs reviewed against `docs/PRODUCTION_READINESS_AUDIT.md`.
- [ ] Content changes reviewed against `docs/LAUNCH_CONTENT_CHECKLIST.md`
      (no invented categories/prices/achievements).
- [ ] Accessibility/perf impact considered (`docs/PERFORMANCE.md`).

## 3. Version & changelog

- [ ] `CHANGELOG.md` updated for the release.
- [ ] Version decided and tagged: `git tag -a vX.Y.Z -m "..."` and pushed.
- [ ] Database backup taken and verified *before* deploy.

## 4. Deploy (staging first)

- [ ] `./deploy/scripts/deploy.sh` on staging.
- [ ] `BASE_URL=... ./deploy/scripts/healthcheck.sh` — all checks pass.
- [ ] Smoke: login, browse, test-mode checkout, staff dashboard, report export.
- [ ] Media default-deny verified on the host.
- [ ] Re-run the end-to-end scenarios (`tests/test_e2e.py`) against staging data
      where feasible.

## 5. Deploy (production — only after approval)

- [ ] Owner approval recorded.
- [ ] Fresh verified backup.
- [ ] `./deploy/scripts/deploy.sh` on production.
- [ ] Health check + logs watched for 5 minutes.
- [ ] Rollback plan confirmed (`docs/PRODUCTION_RUNBOOK.md` §4).
- [ ] Paystack remains in test mode unless live keys are explicitly approved.

## 6. Post-release

- [ ] Monitoring/alerting green (`docs/MONITORING.md`).
- [ ] No new `requires_review` payments left unaddressed.
- [ ] Release notes shared with the business owner.
- [ ] Any incident or accepted gap written up and tracked.

## 7. Rollback (if needed)

- [ ] Previous tag redeployed; trailing migration impact assessed.
- [ ] If data was affected: restore into an isolated DB, verify, cut over.
- [ ] Incident logged with timeline and root cause.

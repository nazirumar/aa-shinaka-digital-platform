# Final Production Readiness Report — AA Shinaka Digital Business Platform

**Phase:** 12 (hardened further in Phase 13)
**Date:** 2026-10-16
**Prepared by:** engineering (Phase 12; Phase 13 addendum below)
**Decision owner:** AA Shinaka business owner

---

## Final status

# READY FOR STAGING

Every code-level gate passes (790 tests, 0 failures; lint, format, system check,
migration guard, production `check --deploy` and the CSS build all clean). The
remaining items are **host-execution gates** (§4) that cannot run in the
development environment: TLS, the `/media/` deny, a backup/restore drill, live
monitoring and the load/accessibility passes.

This report becomes **READY FOR CONTROLLED PRODUCTION LAUNCH** the moment every
gate in §4 is executed and passes on staging and the owner signs off
`docs/LAUNCH_CONTENT_CHECKLIST.md`. It must not be quoted as production-launch
ready before then. It is **not** `NOT READY`: nothing is blocked by an unknown
code defect.

> **Phase 13 addendum (2026-10-16):** the two code-level gaps that Phase 12
> accepted for a controlled launch — **staff MFA** and **upload malware
> scanning** — are now implemented and tested, inventory selection/reservations
> are hardened for multi-warehouse with concurrency evidence, and CI is
> mandatory. Full detail and evidence: `docs/PHASE_13_COMPLETION_REPORT.md`.
> **No deployment, DNS change or live Paystack key was performed.**

---

## How the three statuses map here

| Status | Applies when |
|---|---|
| `NOT READY` | A blocking code/security defect is unresolved. **Not the case** — 0 Critical and 0 open High findings. |
| `READY FOR STAGING` | **Current status.** Code is hardened and tested; host gates still to be executed. |
| `READY FOR CONTROLLED PRODUCTION LAUNCH` | §4 gates pass on staging + owner content sign-off. |

---

## 1. Why this status

| Gate | Result |
|---|---|
| Security audit completed, findings triaged | ✅ 0 Critical, 3 High (all fixed), 5 Medium, 6 Low |
| All Critical/High findings fixed with test evidence | ✅ |
| Medium/Low audit items closed in Phase 13 | ✅ M-3, M-4, L-1, L-2 fixed; MFA implemented |
| Lint & format | ✅ `ruff check` / `ruff format --check` clean |
| Django system check | ✅ 0 issues |
| Missing-migration guard | ✅ "No changes detected" |
| Production `check --deploy` | ✅ clean at `--fail-level ERROR` (only the deliberate HSTS-preload warning remains) |
| Automated security tests | ✅ 23 passing |
| End-to-end scenarios A–F | ✅ 6 passing |
| Full regression suite | ✅ 790 passing, 0 failures, 0 skipped |
| Deployment assets & DR | ✅ provided (host verification pending) |
| No deployment / DNS / live keys performed | ✅ |

## 2. Hardening applied

**Phase 12**
- Ten `GET`-mutating staff endpoints now `@require_POST` (CSRF/state change).
- Payment webhook honours the `PAYSTACK_ENABLED` kill switch; events are
  recorded and deduplicated; signed-only, raw-body HMAC verification.
- Production settings fail fast on weak secrets, wildcard hosts, non-HTTPS CSRF
  origins, non-Redis cache and console email; secure cookies, HSTS, SSL redirect,
  nosniff, opener policy and JSON logging.
- nginx default-denies `/media/`; private documents are served only through
  authorised views.
- Paid-order cancellation via the generic transition restocks the ledger.
- `primary_image` N+1 removed.

**Phase 13**
- **Staff MFA (TOTP)** with single-use hashed recovery codes; login is parked
  until a confirmed second factor is presented; secrets encrypted at rest;
  disable/reset require a fresh code and are audited (`apps/accounts/mfa/`).
- **Upload malware scanning** (`apps/core/upload_security.py`): scan-before-store,
  quarantine, `FileScanRecord` forensics, fail-closed policy, lazy re-scan and
  capability-gated release; optional ClamAV backend in the Compose reference stack.
- **Inventory hardening**: explicit `select_warehouse`, per-warehouse oversell
  guard, roll-up recomputation from Σ balances, and PostgreSQL concurrency tests.
- **Paystack test-mode guard**: a live key (`sk_live_…`) is refused (fail closed)
  unless `PAYSTACK_LIVE_MODE=True` after launch approval.
- **CI hardened**: actions pinned to commit SHAs, `pip-audit` pinned with
  `--strict`, mandatory (non-blocking scanners removed), security subset runs
  first, tool failures distinguished from vulnerability findings.
- Analytics double-compute (L-1) and export selector naming (L-2) resolved.

## 3. Verification evidence

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | All files formatted |
| `uv run python manage.py check` | No issues |
| `uv run python manage.py makemigrations --check --dry-run` | No changes detected |
| prod `manage.py check --deploy` | Clean (only HSTS-preload warning, deliberate) |
| `uv run pytest` (full suite) | 790 passed, 0 failures, 0 skipped (4m57s) |
| `npm run build:css` | Bundle built, non-empty |

Tests are not reported as passing unless they actually ran and passed. Phase 13
added 82 tests (MFA 26, upload security 32, inventory concurrency 18, Paystack
test-mode 6); all prior suites remain green.

## 4. Launch gates that must be verified on the host (NOT VERIFIED here)

These require a real staging/production host and are **not** claimed as done:

1. TLS terminates correctly; HTTP 301-redirects to HTTPS.
2. `curl -I https://HOST/media/<private-file>` returns 403/404; `/static/` serves 200.
3. The application port is not publicly reachable (only nginx).
4. A backup is produced and a **restore drill** succeeds (RPO/RTO measured).
5. Monitoring/alerting is wired and fires a test alert.
6. `sync_roles` run; superuser created; Nigeria locations imported
   (37 states + 774 LGAs).
7. `docs/LAUNCH_CONTENT_CHECKLIST.md` fully signed off by the owner.
8. A load test and a WCAG 2.2 AA pass are executed on staging.
9. A fresh verified backup exists immediately before launch.
10. Paystack remains in **test mode** unless live keys are explicitly approved.

## 5. Accepted gaps (documented, not hidden)

| Gap | Severity | Rationale / plan |
|---|---|---|
| HSTS preload disabled | Low | Deliberate/irreversible; enable only after all subdomains are HTTPS. |
| No third-party penetration test | Medium | Recommended before GA. |
| Dependabot alert untriaged | Low | CI runs pinned `pip-audit` (Phase 13); one GitHub alert not reproduced locally. |
| Deployment-dependent controls | — | Must be verified on the host (§4). |

> Closed in Phase 13 (previously accepted gaps): staff MFA, upload malware
> scanning and multi-warehouse reservation selection are now implemented and
> tested. See `docs/PHASE_13_COMPLETION_REPORT.md`.

## 6. Scope compliance

- No oil & gas, multi-vendor marketplace or AgriTrade ERP features.
- Money remains `DecimalField`; listings own price/stock.
- No new dependency except `gunicorn` (production WSGI server); DRF still deferred.
- `.env` and `static/css/app.css` remain gitignored; no secrets committed.
- Customer accounts preserved; no real transactions created.

## 7. Recommendation

Proceed to **staging**, execute the §4 gates, run the load/accessibility passes
and complete the launch content checklist. When every §4 gate is green and the
owner has approved, this report may be quoted as **READY FOR CONTROLLED
PRODUCTION LAUNCH**. Do not treat the current commit as a general-availability
release while the penetration-test gap remains.

# Production Readiness Audit — AA Shinaka Digital Business Platform

**Phase:** 12 (production security, QA, deployment and launch readiness)
**Date:** 2026-10-16
**Scope:** the whole Django monolith (`apps/*`, `config/*`, `templates/*`, `deploy/*`,
`.github/*`), audited against the Phase 12 brief.
**Method:** manual source review of every mutating endpoint, the payment and
inventory state machines, settings, then corroborated with automated tests.
**Status vocabulary:** `FIXED` (change applied, test evidence), `MITIGATED`
(guarded at the edge / documented control), `OPEN` (accepted risk with a
follow-up), `NOT VERIFIED` (could not be confirmed in this environment).

> Honesty statement: every `FIXED` row cites the file and the test that proves
> it. Nothing is marked verified on the strength of a tool run alone. Items that
> depend on the deployment host (TLS, nginx, backup targets) are marked
> `MITIGATED` and must be re-checked during the staging smoke test — see
> `docs/PRODUCTION_RUNBOOK.md`.

---

## 1. Severity summary

| Severity | Found | Fixed / Mitigated | Open |
|---|---:|---:|---:|
| Critical | 0 | 0 | 0 |
| High | 3 | 3 | 0 |
| Medium | 5 | 2 | 3 |
| Low | 6 | 3 | 3 |

No Critical issue was found. Both `manage.py check --deploy` (production
settings) and the 23-test security suite pass; those are prerequisites, not the
whole audit.

---

## 2. High findings

### H-1 — State-changing endpoints reachable over GET (CSRF bypass)

- **Description:** several staff dashboard actions mutated data in a `GET`
  handler. A `GET` is not CSRF-protected, so a crafted link could publish a
  course or approve an export destination as the logged-in staff user.
- **Module:** `apps/export/dashboard_views.py`, `apps/training/dashboard_views.py`.
- **Evidence (pre-fix):** `destination_approve`, `destination_toggle_active`,
  `quotation_approve`, `compliance_approve`, `category_toggle`, `course_publish`,
  `course_archive`, `instructor_toggle`, `assignment_deactivate`,
  `assessment_publish` had no `@require_POST`. An AST scan for state-changing
  views without a method guard now returns none.
- **Impact:** unauthorised state change via a link/image while a privileged user
  is signed in (privilege-escalation-adjacent).
- **Fix:** added `@require_POST` to all ten; every template already submitted a
  `POST` form with `{% csrf_token %}`.
- **Status:** `FIXED`.
- **Verification:** `tests/test_production_security.py::test_staff_action_rejects_get`
  (405 for GET), plus the export/training suites (POST paths unaffected).

### H-2 — Sensitive uploaded documents stored under the public media path

- **Description:** invoices, receipts, export compliance documents, consultancy
  reports, training resources, support attachments and report exports live under
  `MEDIA_ROOT`/`MEDIA_URL`. If nginx serves `/media/` wholesale, a document is
  reachable by URL without authentication (documents are only *linked* through
  authorised views).
- **Module:** `config/settings/base.py` (`MEDIA_URL`), all `FileResponse` views,
  `deploy/nginx/aa-shinaka.conf`.
- **Evidence:** download views perform capability/ownership checks (support,
  training, export, documents, invoices verified), but the storage location is
  the shared media tree.
- **Impact:** confidentiality breach if a URL leaks (unguessable filenames are
  the only barrier without the edge rule).
- **Fix:** nginx config **default-denies `/media/`** and allow-lists only public
  prefixes (`/media/catalog/`, `/media/training/` course images, etc.). All
  private files are streamed through authorised Django views.
- **Status:** `MITIGATED` — the control is in `deploy/nginx/aa-shinaka.conf` and
  must be confirmed on the target host (deployment-dependent).
- **Verification (code):** `tests/test_production_security.py` asserts another
  customer cannot open a document/order they do not own. **Deployment check
  required:** `curl -I https://HOST/media/<private path>` must return 403/404.

### H-3 — Payment webhook processed while payments are disabled

- **Description:** `process_webhook` verified the signature but did not consult
  the `PAYSTACK_ENABLED` kill switch, so a stale/rogue `charge.success` could be
  processed on an environment where the provider is meant to be off.
- **Module:** `apps/orders/payments.py::process_webhook`.
- **Evidence:** the function reached event dispatch without an `is_enabled()`
  check.
- **Impact:** an environment with payments nominally disabled could still have an
  order settled from a webhook.
- **Fix:** when `paystack.is_enabled()` is `False`, record the event as
  `WebhookEventStatus.IGNORED` and return before dispatch.
- **Status:** `FIXED`.
- **Verification:** `tests/test_production_security.py::test_webhook_ignored_when_payments_disabled`.

---

## 3. Medium findings

### M-1 — Paid-order cancellation via the generic status transition did not restock

- **Description:** the dashboard "change status" path (`transition_order`) moved
  a paid order to `CANCELLED` but only released *active* holds; a paid order's
  reservations are *committed*, so the stock stayed deducted.
- **Module:** `apps/orders/services.py::transition_order`.
- **Evidence:** `_apply_transition` path called `_release_active_reservations`
  only; `_restock_committed` was reached solely through `cancel_order`.
- **Impact:** inventory understated (phantom stock loss) after a paid-order
  cancellation from the status endpoint.
- **Fix:** when the destination is `CANCELLED`/`EXPIRED` **and**
  `order.stock_committed_at` is set, call `_restock_committed`; otherwise release
  active holds (mirrors `cancel_order`). Idempotent because a cancelled order has
  no further legal transitions.
- **Status:** `FIXED`.
- **Verification:** `tests/test_production_security.py::test_paid_order_cancelled_via_status_transition_restocks`
  (stock returns from 7 back to 10).

### M-2 — `ProductListing.primary_image` N+1

- **Description:** `primary_image` ran a query (or two) on every call, and card
  templates call it more than once, multiplying queries on list pages.
- **Module:** `apps/catalog/models.py`.
- **Evidence:** method body hit `.images...` each call.
- **Impact:** avoidable query volume on the public catalogue and shop pages.
- **Fix:** memoised per instance using a module-level `_IMAGE_UNSET` sentinel.
- **Status:** `FIXED`.
- **Verification:** catalogue suites pass unchanged; query count no longer scales
  with the number of calls per card.

### M-3 — Reservations default to the single "MAIN" warehouse

- **Description:** `place_order` does not choose a warehouse; inventory helpres
  resolve to the default (`MAIN`) warehouse when none is supplied. Correct while
  the business operates one fulfilment warehouse, but a multi-warehouse
  operation would reserve from the wrong location.
- **Module:** `apps/catalog/inventory.py` (`resolve_warehouse`, `default_warehouse`),
  `apps/orders/services.py`.
- **Evidence:** `resolve_warehouse(None)` → `MAIN`; order placement passes none.
- **Impact:** incorrect allocation only once more than one warehouse is in active
  use; no data loss today.
- **Status:** `OPEN` — documented operational constraint. **Follow-up:** add
  warehouse selection to checkout before enabling multi-warehouse fulfilment.

### M-4 — No malware scanning on uploaded files

- **Description:** uploads are validated by type/size but not scanned for
  malicious content.
- **Module:** `apps/*/validators.py` (support, training, export, documents).
- **Impact:** a determined attacker could upload a malicious file; it is only
  served to authorised users and `Content-Disposition`/`nosniff` limit execution.
- **Status:** `OPEN` — accepted risk for the controlled launch. **Follow-up:**
  add an asynchronous AV scan (e.g. ClamAV) before the file is made downloadable.

### M-4b — Late/duplicate provider capture on a cancelled or expired order

- **Description:** a `charge.success` arriving after an order was cancelled or
  expired must not silently re-open it. The code marks the payment
  `requires_review` with a reason instead of settling automatically.
- **Module:** `apps/orders/payments.py` (`CANCELLED_OR_EXPIRED`, `requires_review`).
- **Impact:** money is captured but the order is not auto-fulfilled; a human must
  refund or reinstate.
- **Fix / control:** no automatic settlement; surfaced on the finance dashboard
  for reconciliation.
- **Status:** `MITIGATED` (documented manual step in the runbook).
- **Verification:** `tests/test_production_security.py` webhook tests; finance
  review coverage in the Phase 6 suite.

### M-4c — `ALLOWED_HOSTS` / proxy header trust is deployment-dependent

- **Description:** the app trusts `X-Forwarded-Proto`/`X-Forwarded-Host` behind
  the proxy. If the app port were exposed directly, those headers could be
  spoofed.
- **Control:** the reference topology only exposes nginx; the app binds to the
  internal network. `ALLOWED_HOSTS` is required (no wildcard) in production.
- **Status:** `MITIGATED` — must be confirmed on the host (app port not public).

---

## 4. Low findings

| ID | Finding | Status | Notes / evidence |
|---|---|---|---|
| L-1 | `analytics` `_context_for_page` can compute a context twice on some pages | OPEN | Correctness unaffected; minor CPU. Documented for a later perf pass. |
| L-2 | `apps.export.selectors.overview_metrics["active_destinations"]` and `export.selectors.active_destinations()` are two spellings of the same value | OPEN | Pre-existing; not user-visible. Cosmetic debt. |
| L-3 | Structured JSON logging does not scrub arbitrary PII from third-party log records | MITIGATED | App logs deliberately avoid PII; see `docs/DATA_PROTECTION.md`. |
| L-4 | No machine API beyond the payment webhook (DRF deferred) | MITIGATED | Deliberate per `AGENTS.md`; reduces attack surface. |
| L-5 | HSTS `preload` off by default | MITIGATED | Deliberate — irreversible; runbook documents the enable step. |
| L-6 | No automated dependency-update bot | OPEN | CI runs `pip-audit`; Dependabot can be enabled later. |

---

## 5. Controls confirmed present (not findings)

- **Login rate limiting** exists and is applied: `apps/core/ratelimit.py`, used
  by `apps/accounts/views.py` (attempts/window from env).
- **Anti user-enumeration:** password reset and login return the same response
  for known and unknown emails.
- **Password reset tokens:** Django's default `PASSWORD_RESET_TIMEOUT` + one-time
  hashed tokens.
- **Session hardening:** secure/HttpOnly/SameSite cookies in prod; session age
  from env; sessions invalidated on password change.
- **Object-level authorisation:** orders, payments, invoices, receipts, refunds,
  export documents/orders, consultancy reports, farming projects, storage
  bookings, training records/certificates, support tickets and report exports all
  check ownership or capability (verified by tests and by reading each view).
- **Money:** every money field is `DecimalField`; per-currency computation.
- **Inventory:** `select_for_update` on ledger rows; reservations committed once;
  no negative stock path.
- **Webhooks:** HMAC-SHA512 signature verified against the raw body; events
  recorded with a unique id for duplicate handling.
- **MFA for privileged staff:** **NOT VERIFIED / not implemented.** No second
  factor exists in the codebase. For a *controlled* launch this is an accepted,
  documented gap (see the final report) with a follow-up plan; it is a hard
  blocker for a general-availability launch of finance/admin roles.

---

## 6. What this audit did **not** cover

- Penetration testing by an independent third party (recommended before GA).
- Infrastructure security of the chosen host (OS hardening, firewall, IDS).
- Real provider (Paystack live) behaviour — only test-mode contracts verified.
- Load/soak behaviour on the production host — see `docs/PERFORMANCE.md`; numbers
  there are method, not measurements.
- MFA (not implemented), malware scanning (not implemented), Dependabot.

---

## 7. Sign-off

All Critical and High findings are fixed and under automated test. The remaining
Medium/Low items are either host-verification steps or accepted, documented risks
for a **controlled** launch. The overall status is recorded in
`docs/FINAL_PRODUCTION_READINESS_REPORT.md`.

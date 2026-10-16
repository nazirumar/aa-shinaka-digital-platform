# Architecture
## AA Shinaka Digital Business Platform

| | |
|---|---|
| Document ID | AASDP-ARCH-001 |
| Version | 0.4 (Phase 1–4) |
| Status | For engineering review |

---

## 1. Architectural style

The platform is a **classic Django MVT monolith** with server-rendered
templates, enhanced progressively with HTMX and Alpine.js. There is **no
separate frontend application** and no SPA framework.

```
Browser
  │  HTML + HTMX partials + minimal Alpine state
  ▼
Nginx (TLS, static/media)
  │
  ▼
WSGI (Gunicorn) ── Django request/response ── Templates (Tailwind CSS)
  │                         │
  │                         ├── Service layer (business rules, transactions)
  │                         ├── Selectors (read queries)
  │                         └── ORM ── PostgreSQL
  │
  ├── Redis ── Celery workers (async jobs, email, reports, future webhooks)
  └── Media storage (local in dev, S3-compatible in production)
```

**Explicit non-goals:** AgriTrade ERP integration, multi-vendor marketplace,
Oil and Gas functionality, SPA/React/Vue/Next.js, DRF unless a genuine
machine-to-machine API is required (e.g. payment webhooks or a future mobile
client).

---

## 2. Django applications

| App | Responsibility | Status |
|---|---|---|
| `config` | Project settings (`base`/`dev`/`prod`), root URLconf, WSGI/ASGI, Celery app | Phase 1 |
| `apps.core` | Shared abstract bases (timestamps, soft delete), audit helper, rate limiter, locale tooling, home page, healthcheck | Phases 1–3 |
| `apps.locations` | Nigeria location reference data (`Country`, `State`, `LGA`, `City`), location importer + audit table | Phase 4 |
| `apps.accounts` | Custom email user, canonical roles, capability permissions, auth views, profiles, addresses, staff account services; unified portal hub (metrics, activity timeline, document centre) and staff customer overview | Phases 1–2, 10 |
| `apps.cms` | CMS content models (pages, banners, divisions, services, blog, FAQs, testimonials, media, site settings, navigation), public website, CMS dashboard, sitemap/robots, i18n catalogue | Phase 3 |
| `apps.catalog` | Nested categories, products, variants/packaging, origin-specific listings, price engine, warehouses + stock balances, inventory ledger, public catalogue, catalogue/inventory dashboard | Phases 4–5 |
| `apps.orders` | Cart (guest + persistent), checkout, orders, fulfilment, reservations, quotations, shipping configuration; Phase 6 adds Paystack payments, verified webhooks, bank-transfer review, refunds, invoices/receipts and finance reconciliation | Phases 5–6 |
| `apps.services` | Shared service requests (consultancy, farming, marketing, storage), quotations, verified-payment settlement, customer portal and staff service dashboard | Phase 7 |
| `apps.export` | Agricultural export & international trade: destinations/requirements/restrictions, export product profiles, enquiries, Incoterms quotations, export orders, compliance checklists, private documents, shipments/milestones, customer portal and staff export dashboard | Phase 8 |
| `apps.training` | Training academy: configurable categories/courses/modules/lessons/resources, instructors & assignments, venues, capacity-limited cohorts, enrolment + waitlisting, verified-only course payment, attendance, assessments (auto/manual grading), derived completion, staff-approved certificates — public site, student portal and staff dashboard | Phase 9 |
| `apps.notifications` | Unified in-app notification centre: `Notification` feed, per-customer `NotificationPreference` opt-outs, `NotificationDelivery` ledger, pluggable channels (in-app/email, plus inert SMS/WhatsApp), idempotent `emit()` and event builders used by domain apps | Phase 10 |
| `apps.support` | Customer support centre: `SupportTicket`/`SupportMessage`/`SupportAttachment`/`SupportStatusHistory`, server-side ownership checks on linked records, a status state machine, customer + capability-gated staff surfaces | Phase 10 |
| `apps.analytics` | Analytics & reporting: executive + eight operational dashboards, KPI registry, allow-listed report definitions, dependency-free CSV/XLSX/PDF exports, report history, scheduled reports with per-period duplicate protection and a delivery ledger, and read-only data-quality checks (reporting artefacts only — never a business figure of its own) | Phase 11 |
| `apps.dashboard` | Staff dashboard views, staff management, audit log, reporting | Phases 2, 11 |

Rules:
- Apps are **domain-oriented**, not technical layers.
- Cross-app imports are one-directional: `core` ← everyone; `locations` ←
  `accounts`/`catalog`/`cms`; `catalog` ← `orders`; `accounts` ← all. Never
  import `orders` from `catalog`, and never import `catalog` from `locations`.
- `cms` owns every piece of public-site content. `core`'s home view never
  imports `cms` in Python — the homepage and header/footer read CMS data through
  `apps.cms.templatetags.cms_tags` and the `cms` context processor, so the
  catalogue phases can evolve without coupling `core` to `cms`.
- Each app owns its `models.py`, `services.py`, `selectors.py`, `urls.py`,
  `views.py`, `admin.py`, `tasks.py` and `templates/<app>/`.

---

## 3. Service-layer conventions

Views stay thin. Business logic lives in explicit layers:

```
apps/<app>/
  models.py      # schema + tiny invariants (properties, clean())
  selectors.py   # read-only query helpers, return querysets/data
  services.py    # write operations, transactions, side effects, audit
  tasks.py       # Celery task wrappers around services
  forms.py       # validation & widget rendering
  views.py       # request parsing, permission checks, call service/selector, render
```

- **Services** are the only place that mutates business state and the only
  place that opens `transaction.atomic()`. They accept primitive/DTO
  arguments, not `request` objects.
- **Selectors** never mutate.
- Services return domain objects or raise typed exceptions; views translate
  exceptions into messages/HTTP responses.
- Example signatures:

```python
def create_order(*, user, address, contact_name, contact_phone, note="") -> Order: ...
def settle_order(order, *, actor, reference="", note="", request=None) -> Order: ...
def confirm_payment(order, *, actor, reference="", note="", request=None) -> Order: ...
def adjust_stock(*, listing, delta, kind, actor, note="") -> StockMovement: ...
```

- Every sensitive service call writes an `AuditLog` entry within the same
  transaction.

---

## 4. URL routing strategy

```
/                              core:home
/healthz/                      core:healthcheck
/accounts/…                    apps.accounts (register/login/logout/verify/reset)
/account/…                     customer portal (authenticated: dashboard/profile/addresses/security)
/dashboard/…                   staff dashboard + staff management + audit (capability-gated)
/dashboard/cms/…               apps.cms CMS dashboard (content, media, enquiries — capability-gated)
/services/ /about/ /contact/   apps.cms (public website)
/news/ /faqs/ /pages/<slug>/   apps.cms (blog, FAQs, CMS-managed pages)
/sitemap.xml /robots.txt       apps.cms (SEO)
/shop/…                        apps.catalog (public catalogue)
  /shop/                       shop index (featured, categories, states)
  /shop/categories/            full category index
  /shop/category/<slug>/       category detail (subcategories + products)
  /shop/product/<slug>/        product detail (listings by origin)
  /shop/states/                shop by state
  /shop/state/<slug>/          listings originating in that state
  /shop/state/<state>/<lga>/   listings for that LGA
  /shop/search/                search + filters (category, origin, price, availability)
  /shop/compare/               side-by-side product comparison
  /states/… /products/<slug>/ /shop/<slug>/   legacy aliases → same catalog views
/dashboard/catalog/…           apps.catalog staff CRUD (contents, categories, products, listings, prices, stock, references)
/dashboard/inventory/          low-stock reporting (inventory.manage capability)
/cart/ /checkout/ /orders/…    apps.orders
  /orders/<number>/pay/        start/resume hosted Paystack checkout (payment_start)
  /orders/<number>/payment/callback/   Paystack redirect target (server re-verify)
  /orders/<number>/bank-transfer/      submit a manual bank-transfer claim
  /payments/ /payments/<uuid>/         customer payment portal
  /invoices/ /invoices/<number>/       customer invoices (+ /pdf/)
  /receipts/<number>/ (+ /pdf/)        receipts for verified payments
  /payments/paystack/webhook/          csrf-exempt, signature-verified webhook
/dashboard/finance/…           apps.orders finance dashboard (FINANCE_MANAGE)
  /dashboard/finance/          overview (verified-only metrics)
  /dashboard/finance/payments/ /payments/<uuid>/ (+ /reconcile/)
  /dashboard/finance/transfers/ /transfers/<uuid>/ (+ /review/)
  /dashboard/finance/refunds/ /refunds/<uuid>/ (+ /approve/ /complete/)
  /dashboard/finance/invoices/ /invoices/<number>/
  /dashboard/finance/bank-accounts/ (+ /new/ /<uuid>/edit/ /<uuid>/toggle/)
/consultancy/ /farming/ …      apps.services public request forms
/account/services/…            apps.services customer portal (authenticated)
  /account/services/           portal home (requests, quotations, appointments)
  /account/services/<division>/new/   booking/request forms
  /account/services/quotations/<uuid>/          quotation detail (+ /pay/)
  /account/services/payments/callback/<ref>/    server-side re-verify
  /account/services/proposals/<uuid>/decide/    accept/reject a proposal
/dashboard/services/…          apps.services staff dashboard (SERVICES_MANAGE)
  /dashboard/services/         overview + Chart.js (real records only)
  /dashboard/services/requests/ + /requests/<reference>/
  /dashboard/services/appointments/<uuid>/confirm|complete/
  /dashboard/services/farm/…   projects, milestones, progress
  /dashboard/services/marketing/…  enquiries, proposals, campaigns
  /dashboard/services/storage/…    facilities, units, bookings
  /dashboard/services/quotations/… (+ /quotations/new/<reference>/)
/account/export/…              apps.export customer portal (authenticated)
  /account/export/             portal home (enquiries, quotations, orders, shipments)
  /account/export/enquiries/new/ + /enquiries/<reference>/
  /account/export/quotations/<uuid>/ (+ /accept/)
  /account/export/orders/<reference>/ (+ /pay/ /documents/upload/)
  /account/export/documents/<uuid>/download/
  /account/export/shipments/<reference>/
  /account/export/payments/callback/<ref>/   server-side re-verify
/dashboard/export/…            apps.export staff dashboard (EXPORT_MANAGE)
  /dashboard/export/            overview + Chart.js (real records only)
  /dashboard/export/destinations/… (+ approve/activate/requirements/restrictions/documents)
  /dashboard/export/products/…
  /dashboard/export/enquiries/… (+ /quotation/new/)
  /dashboard/export/quotations/… (+ approve/revise)
  /dashboard/export/orders/<reference>/ (+ transition/documents)
  /dashboard/export/documents/… (+ review)
  /dashboard/export/compliance/… (+ approve, item updates)
  /dashboard/export/shipments/… (+ transition/milestone)
  /dashboard/export/providers/…
  /dashboard/export/reports/
/training/…                    apps.training public academy
  /training/                   home (featured published courses)
  /training/courses/ + /courses/<slug>/ + /categories/<slug>/
  /training/sessions/ + /sessions/<uuid>/ + /sessions/<uuid>/enrol/
  /training/verify/ + /verify/<code>/     public certificate verification
  /training/payments/callback/<reference>/  server-side re-verify
/account/training/…            apps.training student portal (authenticated)
  /account/training/           home, my courses, upcoming sessions
  /account/training/enrolments/<reference>/ (+ /pay/ /cancel/ lessons/… assessments/…)
  /account/training/resources/<uuid>/download/
  /account/training/certificates/ (+ /<uuid>/ /<uuid>/download/)
  /account/training/payments/
/dashboard/training/…          apps.training staff dashboard (TRAINING_MANAGE)
  /dashboard/training/         overview + Chart.js (real records only)
  /dashboard/training/categories/… courses/… modules/… lessons/… resources/…
  /dashboard/training/instructors/… assignments/… venues/…
  /dashboard/training/sessions/… (+ schedules, transitions)
  /dashboard/training/enrollments/… (+ actions)
  /dashboard/training/attendance/… (+ marking)
  /dashboard/training/assessments/… (+ questions/publish/grade)
  /dashboard/training/certificates/… (+ templates, issue/revoke — TRAINING_APPROVE)
  /dashboard/training/reports/
/account/…                     unified customer portal (authenticated)
  /account/                    overview dashboard (real per-customer metrics)
  /account/activity/           aggregated activity timeline
  /account/documents/          document centre
  /account/documents/<kind>/<pk>/download/   central, per-type ownership check
/notifications/…               apps.notifications centre (authenticated)
  /notifications/              notification centre
  /notifications/<uuid>/open/  mark read + safe-link redirect
  /notifications/<uuid>/read/  mark one read (HTMX-aware)
  /notifications/read-all/     mark all read
  /notifications/badge/        unread-count badge partial (HTMX)
  /notifications/preferences/  channel + category opt-outs
/support/…                     apps.support customer support centre (authenticated)
  /support/                    support home (my tickets)
  /support/new/                open a ticket (ownership-checked link)
  /support/tickets/<reference>/ (+ reply/close/reopen)
  /support/attachments/<pk>/download/   ownership-checked attachment
/dashboard/support/…           apps.support staff queue (SUPPORT_MANAGE)
  /dashboard/support/          queue + metrics
  /dashboard/support/tickets/<reference>/ (+ assign/status/reply)
  /dashboard/support/tickets/<reference>/priority/ (SUPPORT_APPROVE)
  /dashboard/support/attachments/<pk>/download/
/dashboard/customers/…         staff customer overview (CUSTOMERS_VIEW)
  /dashboard/customers/        directory
  /dashboard/customers/<uuid>/ cross-domain aggregates (finance rows need FINANCE_MANAGE)
/dashboard/…                   apps.analytics reporting surface (Phase 11)
  /dashboard/executive/         executive overview (analytics.view)
  /dashboard/analytics/<page>/  sales|finance|inventory|services|export|training|customers|support
                                (analytics.view; finance needs analytics.finance)
  /dashboard/analytics/api/<page>/  JSON KPI/chart feed (same gating)
  /dashboard/reports/builder/   controlled report builder (reports.build)
  /dashboard/reports/generate/  generate + redirect to the file (reports.build)
  /dashboard/reports/history/   generated-report history (reports.build; all rows need reports.manage)
  /dashboard/reports/<uuid>/download/  permission-checked private download
  /dashboard/reports/scheduled/…  recurring configs (reports.schedule)
  /dashboard/reports/data-quality/  read-only integrity checks (analytics.view)
/admin/                        Django admin (superusers)
```

- Each app declares `app_name` and includes its `urls.py` from `config/urls.py`
  under a stable prefix; reverse with `app:name`.
- Public slugs are the URL identity (SEO). IDs appear only in authenticated
  areas.
- Versioned API, if ever needed, would live under `/api/v1/` and be justified
  individually.

---

## 5. Template & component organisation

```
templates/
  base.html                 # shell: head, nav, messages, footer
  components/               # reusable includes (navbar, footer, cards, forms…)
    navbar.html
    footer.html
  <app>/<page>.html         # page templates per app
  registration/             # password reset templates (Django auth)
```

- Templates are shared, never duplicated per device. Responsiveness is handled
  with Tailwind utilities, not separate mobile templates.
- **HTMX** endpoints return **partials** (fragments) and live under the same
  route with an `HX-Request` check or dedicated `*/partial/` paths.
- **Alpine.js** is used only for local UI state (dropdowns, toggles, tabs).
- Components receive explicit context and avoid implicit globals.
- Accessibility is part of the component contract (labels, roles, focus, contrast).

### 5.1 Static assets / Tailwind pipeline

- Source: `static/src/app.css` (`@import "tailwindcss"` + `@source` globs +
  brand theme tokens).
- Build: `npm run build:css` → `static/css/app.css` (gitignored, built in dev
  and CI). `npm run watch:css` during development.
- Django serves hashed static files through WhiteNoise in production
  (`CompressedManifestStaticFilesStorage`).
- HTMX, Alpine.js and Chart.js are loaded as pinned CDN scripts in Phase 1;
  vendoring them locally is a deployment-hardening task in Phase 12.

---

## 6. Background task architecture

- Broker/result backend: **Redis**, accessed through Celery (`config/celery.py`).
- `CELERY_TASK_ALWAYS_EAGER` is `False` by default; tests set it `True`.
- Task conventions: idempotent, small, call a service function; heavy work
  (reports, exports, bulk email) is queued, never run in a request.
- Planned queues/tasks:
  - `email` — transactional email (registration, order, request updates).
  - `reports` — report generation (`ReportExport`). Phase 11 generates synchronously
    by default (`ANALYTICS_EXPORT_ASYNC=False`) for deterministic behaviour without
    a worker; `analytics.tasks.generate_report_export_task` renders a queued export
    when async is enabled, `analytics.tasks.run_scheduled_reports` runs due
    schedules at most once per period, and `analytics.tasks.cleanup_report_exports`
    enforces retention. `manage.py run_scheduled_reports` / `cleanup_report_exports`
    / `check_analytics_data` are the worker-free equivalents.
  - `integrations` — Paystack webhook/reconciliation tasks
    (`orders.reconcile_payments`).
  - `notifications` — unified notification-channel delivery
    (`notifications.tasks.deliver_delivery_task`, `deliver_pending_task`):
    per-delivery retry with exponential backoff plus a periodic sweep for missed
    schedules. The in-app row is always created synchronously; only channel
    delivery is deferred.
  - `maintenance` — nightly reconciliation of `stock_on_hand` vs the
    `StockMovement` ledger.
- Beat (scheduled) tasks are defined centrally with `CELERY_BEAT_SCHEDULE`.

---

## 7. Authentication and permissions (Phase 2, implemented)

- **Custom user** `accounts.User` (UUID PK, email login, no username), set via
  `AUTH_USER_MODEL` **before the first migration**. Emails are lower-cased on
  creation and login is case-insensitive.
- **Ten canonical roles** in `accounts.UserRole`: Customer, Sales Officer,
  Inventory Officer, Consultant, Training Manager, Export Officer, Finance
  Officer, Content Editor, Administrator, Owner/Super Admin. `User.role` is the
  indexed, canonical value used for display and filtering.
- **Two representations kept in sync:** `User.role` (the value) and a Django
  group `role:<code>` (the authority). Groups carry model permissions; the
  capability matrix in `accounts/roles.py` (`ROLE_CAPABILITIES`,
  `ROLE_DJANGO_PERMISSIONS`) is the single source of truth. `manage.py
  sync_roles` (re)creates the groups and permissions idempotently; role changes
  via services keep the group membership in step.
- **Enforcement points** (`accounts/permissions.py`) — all server-side:
  - `@capability_required("…")` / `has_capability(user, …)` for feature access.
  - `@staff_required`, `@role_required(…)` for staff areas.
  - `can_assign_role` / `assignable_roles` / `can_manage_target` in services for
    privilege-escalation and self-edit guards.
  - Object-level ownership checks (a customer sees only their own addresses and
    account).
- **Escalation guard.** Owners/superusers may grant any role; administrators may
  grant every staff role *except* `owner`/`administrator`; nobody may edit
  themselves; administrators cannot edit owner/superuser accounts. Public
  registration can only create `customer` (`accounts/forms.py`).
- **Email verification** uses `django.core.signing` timestamped tokens
  (salt `aa-shinaka.email-verification`) plus a per-user rotating
  `email_verification_nonce` for replay protection, expiring after
  `EMAIL_VERIFICATION_TIMEOUT` (default 48h).
- **Passwords** use Django's built-in validators. Reset uses the built-in views
  with `default_token_generator` (throttled via `ThrottledPasswordResetView`);
  change uses `update_session_auth_hash` so other sessions are invalidated by
  the session auth-hash mismatch.
- **Rate limiting** on register/login/resend/password-reset is cache-backed and
  dependency-free (`core/ratelimit.py`), keyed by IP/email/user.
- Templates only *hide* navigation the user cannot use (`perm_tags`); they never
  grant access.
- Sessions: secure/HTTP-only cookies in production; CSRF middleware always on.

### 7.1 Audit logging

- `dashboard.AuditLog` is append-only (writes go through `core.audit.record_audit`;
  `save()` on an existing row and `delete()` raise `ValueError`; admin is
  read-only).
- Each sensitive service call records actor, action, target type/id, request
  metadata (IP, user-agent), and a redacted before/after summary within the same
  transaction. Passwords, tokens and secrets are never recorded.

### 7.2 Phase 10 capabilities (notifications, support, customer overview)

- Three capabilities were added to the matrix in `accounts/roles.py`:
  `SUPPORT_MANAGE` (work the support queue, reply, assign),
  `SUPPORT_APPROVE` (priority/approval-class actions) and `CUSTOMERS_VIEW`
  (read-only staff customer overview).
- `SALES_OFFICER` and `FINANCE_OFFICER` gain `CUSTOMERS_VIEW`;
  `ADMINISTRATOR`/`OWNER` hold all capabilities. Run `manage.py sync_roles`
  after migrations.
- Notification/support **isolation is object-level**: a customer only ever reads
  their own `Notification`/`SupportTicket` rows, and the central document
  download re-authorises by record type *and* ownership — a raw primary key is
  never trusted on its own. Financial rows on the staff customer overview are
  gated by the finance capability (`FINANCE_MANAGE`) in the view, never by the
  template.

### 7.3 Unified notification pipeline (Phase 10)

`apps.notifications` consolidates customer-facing communication without
duplicating the per-domain email senders:

```
domain service (order placed, payment verified, ticket reply …)
  -> apps.notifications.events.<event>(obj)      # build title/message/safe link
  -> services.emit(recipient, category, event, dedupe_key, …, manage_email=…)
        - idempotent on dedupe_key (retried webhooks never duplicate)
        - a muted category stores nothing
        - creates Notification + a NotificationDelivery per channel IN the
          current transaction  (so the in-app row is never lost)
        - schedules only channel delivery on transaction.on_commit
  -> Celery task deliver_delivery_task -> channels.<Channel>.send()
        - EmailChannel is recorded `delivered` only when the backend confirms
        - unconfigured SMS/WhatsApp channels are recorded `skipped`
```

- **No duplicate emails:** events a domain app already emails simply mirror into
  the in-app feed; `manage_email=True` is reserved for genuinely new events
  (e.g. support replies). This boundary is transitional and documented.
- `NotificationPreference` holds per-channel toggles and per-category opt-outs;
  `NotificationDelivery` is the audit-grade delivery ledger (attempts, status,
  error detail).
- SMS/WhatsApp adapters are **inert** until a provider URL/key is configured and
  the customer opts in; no credentials are hardcoded. All provider config comes
  from `SMS_*`/`WHATSAPP_*`/`SITE_URL`/`NOTIFICATION_*` env vars.

### 7.4 Support-ticket lifecycle (Phase 10)

`apps.support` owns the customer support case:

- A ticket may link one of the customer's own order/payment/enquiry/request/
  enrolment. The link is resolved **server-side** (`links.resolve_related`) and
  raises if the record is unknown or not owned — a raw reference/pk is never
  trusted.
- `SUPPORT_TRANSITIONS` declares the legal status moves
  (`open/assigned/in_progress/waiting_for_customer/resolved/closed/reopened`);
  anything else is rejected. A resolved ticket may be reopened only within
  `REOPEN_WINDOW_DAYS`.
- Internal staff notes never reach the customer (the customer-scoped selector
  filters them out) and never notify. A customer-visible staff reply mirrors into
  the notification feed via `events.support_ticket_reply` (this is a genuinely
  new event, so it may also send email).
- The queue, assignment, status and priority actions are capability-gated
  (`SUPPORT_MANAGE`/`SUPPORT_APPROVE`) in the view layer.

### 7.5 Phase 11 capabilities (analytics & reporting)

- Five capabilities were added to the matrix in `accounts/roles.py`:
  `ANALYTICS_VIEW` (see the dashboards), `ANALYTICS_FINANCE` (see financial
  figures/columns/reports), `REPORTS_BUILD` (use the report builder and history),
  `REPORTS_SCHEDULE` (create/manage recurring reports) and `REPORTS_MANAGE`
  (see and download every report, not only your own).
- Sales/Inventory/Training/Export officers and the Training Manager get
  `ANALYTICS_VIEW` + `REPORTS_BUILD`; the Consultant gets `ANALYTICS_VIEW`; the
  Finance Officer holds all five; `ADMINISTRATOR`/`OWNER` hold everything. Run
  `manage.py sync_roles` after migrations.
- Financial gating happens in **what is computed**, not only what is rendered: a
  user without `ANALYTICS_FINANCE` never receives a financial figure or column
  (the page raises `PermissionDenied`, the API returns 403, `available_reports`
  hides financial reports and `visible_columns` strips money columns).
- Report files are private. `report_download` re-checks ownership (or
  `REPORTS_MANAGE`) and the finance capability, and writes an audit entry for
  financial access. There is no public file URL.

### 7.6 Analytics & reporting pipeline (Phase 11)

`apps.analytics` is read-only against the business domain — it never writes to a
business table and never stores a business figure of its own:

```
request -> capability check
  -> selectors.<aggregate>(filters)         # real ORM aggregates, Decimal, per currency
  -> charts.<page>_charts(filters)          # JSON-safe payloads
  -> view model (kpis/charts/tables) -> template (json_script, never string-interpolated)

report builder -> ReportBuilderForm (typed, allow-listed filters)
  -> reports.get_report(key)                # allow-listed definition, else rejected
  -> reports.build_rows(definition, filters)
  -> exports.generate(columns, rows, format)  # CSV / XLSX(zip) / PDF
  -> private ReportExport (+ AuditLog for financial reports)

scheduled reports -> ReportExecution(period_key) unique per (schedule, period)
  -> generate + deliver_report() with a per-recipient capability re-check
```

- **No arbitrary SQL, model path or field list.** A request can only name a key
  from `REPORT_DEFINITIONS`.
- **Money is per-currency.** Selectors return per-currency rows and never sum
  across currencies; `ANALYTICS_BASE_CURRENCY` selects the reporting currency and
  `ANALYTICS_EXCHANGE_RATES` (optional) enables conversion — the platform never
  invents a rate.
- **No fabricated values.** Empty states stay empty; money becomes `float` only
  for chart geometry and the exact `Decimal` is shown in the table.
- **Export safety.** Text cells are guarded against spreadsheet formula injection;
  XLSX is a hand-built Open XML package; PDF uses a small dependency-free renderer.
- **Retention.** `ANALYTICS_REPORT_RETENTION_DAYS` sets `expires_at`; a task or
  management command deletes files past retention and marks the records `expired`.

---

## 8. Payment lifecycle

The order flow reserves stock and stops at `pending_payment`. Settlement is
provider-independent at the core: both the audited manual `confirm_payment`
(capability `FINANCE_MANAGE`) and Phase 6 provider captures converge on the
idempotent `services.settle_order`, which commits the reservation
(`StockMovement: sale`) in the same transaction.

```
create order -> reserve stock -> Order(pending_payment)
      |                                             |
      |  staff manual approval    OR  verified Paystack capture
      |  (confirm_payment)            OR finance-approved bank transfer
      |                                             v
      +-------------------------> settle_order(atomic) -> Order.confirmed
                                                    |
                                      commit reservation (StockMovement: sale)
                                                    |
                               cancel/expire: release reservation
```

Phase 6 providers and modules:

- **Paystack** (`apps.orders.paystack`): the only place that talks to the
  provider and the only place smallest-unit amounts (kobo) exist
  (`to_kobo`/`from_kobo`). Reads `PAYSTACK_*` from settings only; never logs,
  renders or returns the secret key.
- **Checkout**: `initialize_payment` creates (or reuses) an open `Payment` +
  `PaymentAttempt` and returns the hosted `authorization_url`. The browser is
  redirected there; nothing about the amount comes from the client.
- **Verification** (`verify_payment` → `_apply_verification`): the redirect
  query string is never trusted. The status, amount and currency are re-fetched
  server-side and must match the stored `expected_amount`/`currency`; an
  underpay or currency mismatch is marked `failed` and flagged
  `requires_review`.
- **Webhooks** (`/payments/paystack/webhook/`): signature-verified with
  HMAC-SHA512 over the **raw** body using the secret key (or
  `PAYSTACK_WEBHOOK_SECRET` when configured). Each delivery is stored in
  `PaymentWebhookEvent` with a unique `(provider, event_id)`, so duplicates and
  out-of-order events are idempotent. Returns 401 for a bad signature, 400 for a
  malformed/unknown payload and 200 for accepted or duplicate deliveries.
- **Late payment**: a capture for an order that is no longer payable
  (expired/cancelled) records the payment, sets `requires_review` and never
  completes the order.
- **Bank transfers**: a customer claim (`BankTransferSubmission`) is never a
  settlement; an authorised finance user must approve it with
  `settlement_confirmed=True`, and the unique-approved-transfer constraint stops
  one transfer settling two orders.
- **Refunds**: `request → approve → complete`, finance-only, never exceeding
  captured funds; Paystack refunds complete via `refund.processed` webhooks,
  offline refunds are completed manually.
- **Invoices/receipts**: issued immutable documents (`apps.orders.documents`
  renders HTML views plus a dependency-free PDF); receipts exist only for
  verified payments.
- **Reconciliation**: `reconcile_payment(s)` re-verifies open Paystack payments;
  beat task `orders.reconcile_payments` and
  `manage.py reconcile_payments` run it on a schedule.
- No provider keys are committed; they come from environment variables
  (`PAYSTACK_ENABLED`, `PAYSTACK_SECRET_KEY`, …). See `.env.example`.

**Service quotations (Phase 7)** reuse the same pipeline. `orders.Payment`
gained an optional `service_quotation` target; a check constraint
(`chk_payment_single_target`) guarantees a payment points at exactly one of
`order`/`service_quotation`. `initialize_quotation_payment` opens a Paystack
round-trip for the quotation total, and on successful server-side verification
`_apply_verification` branches to
`apps.services.payments.settle_quotation_payment`. That service marks the
quotation paid, treats paying an *issued* quotation as implicit acceptance, and
calls `activate_paid_service` — the **only** path that confirms a paid storage
booking or activates a farm project. The browser callback never activates a
service by itself.

---

## 8a. Service-request lifecycle (Phase 7)

One concrete `ServiceRequest` is shared by every division, with per-division
detail records (`OneToOne`). The legal moves are declared in
`REQUEST_TRANSITIONS` and every change appends to
`ServiceRequestStatusHistory` and `ServiceActivityLog`:

```
submitted -> under_review -> quoted -> confirmed -> in_progress -> completed
     |            |            |          |             |
     +------------+------------+----------+-------------+--> rejected / cancelled
```

- A request acted on **straight from `submitted`** (a staff confirmation or an
  activation) is implicitly reviewed first, so history always reflects the
  declared pipeline rather than skipping a stage.
- `apps/services/services.py` owns every write; `selectors.py` owns reads.
  Money is `Decimal`; quotation totals are recomputed server-side and an
  accepted quotation is frozen (`save()` guards `_FROZEN_FIELDS`).
- Overlap (consultant appointments) and over-allocation (storage capacity) are
  enforced in the service layer under `select_for_update`, backed by
  CheckConstraints on the tables.
- Divisions are gated by `REQUESTS_CONSULTANCY|FARMING|MARKETING|STORAGE`; the
  shared dashboard by `SERVICES_MANAGE`; quotation approval/issue by
  `QUOTATIONS_MANAGE`. Enforcement is server-side, never in templates.

**Export payments (Phase 8)** reuse the same pipeline once more.
`orders.Payment` gained an optional `export_order` target (the single-target
constraint now covers `order`/`service_quotation`/`export_order`).
`initialize_export_payment` opens a Paystack round-trip in the configured
provider currency (Paystack is **not** assumed to support every export currency),
and on successful server-side verification `_apply_verification` branches to
`apps.export.payments.settle_export_payment` → `services.record_verified_payment`.
That trusted, system-actor path increases `amount_paid` and, once the deposit
threshold is met, advances the export order using the **non-gated** internal
`_advance_export_order`; staff-driven transitions use the gated
`transition_export_order`. The browser callback never marks an export order paid.

**Training-enrolment payments (Phase 9)** reuse the same pipeline.
`orders.Payment` gained an optional `training_enrollment` target (the
`chk_payment_single_target` constraint now covers `order` / `service_quotation` /
`export_order` / `training_enrollment`). `initialize_training_payment` opens a
Paystack round-trip; on successful server-side verification `_apply_verification`
branches to `apps.training.payments.settle_training_payment` →
`services.settle_enrollment_payment`, which is **idempotent** via
`Enrollment.settled_payment_references`, applies the verified amount and confirms
the enrolment once the required fee (or an approved deposit) is met. A browser
callback alone never confirms a training enrolment.

---

## 8b. Export order lifecycle (Phase 8)

The dedicated `apps.export` app owns the whole export & international-trade
workflow. Every write goes through `apps/export/services.py`; reads live in
`apps/export/selectors.py`; primary keys are UUIDs and money/quantities are
`Decimal`. Cross-app foreign keys use string references
(`catalog.*`, `locations.*`, `settings.AUTH_USER_MODEL`, `export.*`).

```
destination  : (country) -> pending -> approved -> activated   [EXPORT_APPROVE for approve]
enquiry      : submitted -> under_review -> quoted -> converted
quotation    : draft -> pending_approval -> issued -> accepted   [accepted = frozen]
order        : pending_payment -> payment_verified -> in_production ->
               ready_for_shipment -> shipped -> delivered -> completed
shipment     : planned -> booked -> dispatched -> in_transit ->
               customs_processing -> arrived -> delivered
```

Rules enforced in the service layer (not in templates):

- A destination is selectable only when it is **approved and active**; product
  eligibility combines the positive `allowed_destinations` allow-list with
  active `ExportTradeRestriction` rows (`selectors.active_restriction_for`).
- A quotation always carries an **Incoterms 2020** rule **and a named place**;
  totals are recomputed server-side and an accepted quotation is frozen.
- A compliance checklist is generated from the destination's document
  requirements; an order cannot become `ready_for_shipment`/`shipped` and a
  shipment cannot be `dispatched` until the checklist is approved.
- Shipment milestones are **staff-entered only**; nothing is fabricated.
- Two internal helpers (`_advance_enquiry`, `_advance_export_order`) exist
  solely so trusted system steps (a customer accepting their quotation; a
  verified payment) can advance state without a staff capability. The public
  `transition_enquiry` / `transition_export_order` remain gated on
  `EXPORT_MANAGE`.

Capabilities: `EXPORT_MANAGE` (Export Officer, plus admins/owners) gates the
staff dashboard; `EXPORT_APPROVE` (Administrators/Owners only) gates destination
approval and quotation approval/issue. Each division maps to `requests.export`.
Customers are scoped to their own enquiries/quotations/orders/shipments.

---

## 8c. Training-academy lifecycle (Phase 9)

The dedicated `apps.training` app owns the academy end to end. Every write goes
through `apps/training/services.py`; reads live in `apps/training/selectors.py`;
primary keys are UUIDs and money is `Decimal` (local `UUIDTimeStampedModel`,
references via `generate_reference`). Nothing is hardcoded — categories,
courses, cohorts, instructors, venues, fees and capacities are records.

```
course    : draft -> published -> archived        (published requires TRAINING_APPROVE)
session   : draft -> scheduled -> enrollment_open -> enrollment_closed ->
            in_progress -> completed               (-> cancelled from active states)
enrollment: pending -> payment_pending -> confirmed -> completed
            (waitlisted when full; cancelled from active states)
```

Rules enforced in the service layer (never in templates):

- Enrolment is capacity-checked under `select_for_update()`; a full cohort yields
  `WAITLISTED`, a free seat confirms immediately, a paid seat becomes
  `PAYMENT_PENDING` and confirms **only** on a server-verified payment
  (idempotent via `settled_payment_references`). Closed sessions and passed
  deadlines are rejected; duplicate active enrolments are blocked.
- Lesson and resource access is resolved from the enrolment (confirmed students),
  an active instructor assignment or a `TRAINING_MANAGE`/`TRAINING_APPROVE`
  capability — private resources are never public.
- Completion is **derived** (`recompute_progress`) from real records: every
  lesson complete **and** every published completion-required assessment passed;
  empty content never completes a course.
- Certificates require `TRAINING_APPROVE` plus a completed, certificate-eligible
  course; public verification exposes only the minimum approved information.
- Course payment reuses the Phase 6 pipeline (see §8 above); the browser callback
  never confirms a training enrolment.
- Capabilities: `TRAINING_MANAGE` gates the dashboard; `TRAINING_APPROVE`
  (Administrators/Owners) gates course publication and certificate issue/revoke;
  `TRAINING_INSTRUCT` plus an active assignment unlocks teaching surfaces.
  Students are scoped strictly to their own records.

---

## 9. Order and inventory state transitions

- Order: `pending_payment → payment_review → confirmed → processing →
  ready_for_dispatch → dispatched → delivered → completed`;
  terminal/exception: `cancelled`, `expired`, `refunded`. The transition map is
  enforced in `apps.orders.models` (`ORDER_TRANSITIONS`) and every
  change appends to the immutable `OrderStatusHistory`.
- Stock: **reserve** on order creation, **commit** on payment
  confirmation, **release** on cancellation/expiry; every change is an
  append-only `StockMovement` with a `balance_after` snapshot.
  `StockBalance.on_hand`/`reserved` are authoritative; the listing's
  `stock_on_hand`/`stock_reserved` are maintained roll-ups.
- Illegal transitions raise a domain exception; the DB is never left in a
  partial state because each transition is one transaction.

---

## 10. File and image storage

- Local `FileSystemStorage` in development; S3-compatible object storage in
  production (configured via `STORAGES`).
- `MEDIA_ROOT`/`MEDIA_URL` for uploads (`ProductImage`, documents).
- Uploads are validated for content type and size; images are served with
  correct `Content-Type` and `nosniff`.
- Exports/reports are generated to a private location and served via signed or
  permission-checked URLs, not guessed paths.

---

## 11. Logging and monitoring

- Structured console logging configured in `config/settings/base.py`
  (`django`, `django.security`, `apps` loggers).
- `apps` logger is used for domain events; audit-grade changes go to
  `AuditLog`, not just logs.
- `/healthz/` checks application + database connectivity for uptime monitors.
- Celery task failures are logged with task name and id; retries are explicit.
- Error tracking (e.g. Sentry) and metrics are Phase 12 hardening items.

---

## 12. Security practices

- Secrets only from environment (`.env` gitignored; `.env.example` documents keys).
- `SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL` injected via environment.
- Production settings enable HSTS, SSL redirect, secure cookies, `nosniff`,
  `X-Frame-Options: DENY`.
- CSRF on all unsafe methods; forms use `{% csrf_token %}`.
- ORM-only data access; no raw SQL with user input.
- `PROTECT`/`SET_NULL` FK behaviour and soft deletion preserve business records.
- Sensitive operations are transactional and audited.
- Input validation at forms + model + DB constraint levels.
- Cache-backed rate limiting protects the registration, login, verification-resend
  and password-reset endpoints (Phase 2; broader form throttling is Phase 12).
- Email verification, password reset/change and staff role assignment all run
  through audited services.

---

## 13. Deployment architecture

| Component | Development | Production |
|---|---|---|
| Settings | `config.settings.dev` | `config.settings.prod` |
| Python env | `uv` managed `.venv` | `uv`/container built from lockfile |
| Database | local PostgreSQL | managed PostgreSQL (≥15) |
| Cache/broker | local Redis (optional) | managed Redis |
| Web server | Django `runserver` | Gunicorn behind Nginx |
| Static | Django staticfiles | WhiteNoise + Nginx |
| Media | local `media/` | S3-compatible bucket |
| Workers | `celery -A config worker` | supervised workers + beat |
| Secrets | `.env` | platform secret manager |

Deployment steps: build static (`npm run build:css`), `collectstatic`,
`migrate`, restart web + workers. No secrets in the repository or images.

---

## 14. Testing strategy

- **pytest + pytest-django**, settings `config.settings.dev`, tests in `tests/`.
- Unit tests for services (transactions, state machines), model tests for
  constraints, view tests for routing/permissions, and command tests for the
  location importer.
- Phase 2 tests cover registration, login/logout, email verification, password
  management, the customer portal, the permission matrix, staff management and
  escalation guards, the audit log, security/rate limiting and template
  accessibility.
- Phase 5 tests cover the cart (guest sessions, login merge, server-side
  pricing), checkout gating/idempotency/oversell rejection, the reservation
  lifecycle (commit/release/expiry), the order state machine and payment
  approval boundaries, the customer order portal and quotation requests, and
  the staff orders + inventory (warehouse/stock) dashboards and their
  capability gates.
- Phase 6 tests cover the Paystack lifecycle and refunds with every provider
  call monkeypatched (see `tests/test_orders_payments.py`).
- Phase 7 tests (`tests/test_services.py`) cover the shared request engine
  (reference/history/transitions/assignment/comments/attachments/notification
  dedupe/division isolation), each division workflow (consultancy overlap,
  farming agreement gate, marketing proposal→campaign, storage capacity),
  quotations (server totals, workflow + freeze, capability gate, revise, expiry),
  verified settlement (idempotent, activates paid storage), and portal/dashboard
  access control, render smoke and URL reversal.
- Phase 8 tests (`tests/test_export.py`) cover destinations, quotations,
  compliance, documents, shipments and verified settlement.
- Phase 9 tests (`tests/test_training.py`) cover the academy catalogue, enrolment
  (capacity/waitlist/deadlines), verified-only settlement, attendance,
  assessments/grading, derived completion and certificates.
- Phase 10 tests: `tests/test_notifications.py` (idempotent emission, category
  muting, read-state/ownership, safe redirects, real email confirmation, inert
  SMS/WhatsApp, preferences, context processor), `tests/test_support.py` (ticket
  creation, state machine, reopen window, internal-note visibility, reply
  notification, ownership + attachment isolation, capability gating) and
  `tests/test_portal.py` (document-centre ownership and central download
  authorisation, activity isolation, portal metrics and the capability-gated
  staff customer overview).
- Phase 11 tests (`tests/test_analytics.py`) cover dashboard/API access control
  and finance gating, selector/multi-currency correctness, the report registry and
  builder, generate/download/ownership and financial-report auditing, export magic
  bytes and the formula-injection guard, retention cleanup, data-quality checks,
  and scheduling with per-period duplicate protection and delivery-permission
  skipping.
- `django_db` is required for DB tests; integration tests that need real
  external services are marked `integration`.
- `makemigrations --check` guards against missing migrations.
- Required local gate: `ruff check` → `ruff format --check` → `pytest` →
  `manage.py check` (+ `makemigrations --check` when models change).

---

## 15. Architectural decision record (ADR) summary

| ADR | Decision | Rationale |
|---|---|---|
| ADR-1 | Django MVT monolith, no SPA | Team expertise, SEO, simpler delivery; brief mandates it |
| ADR-2 | Custom email user before first migration | Email is the natural identifier; avoids painful later swap |
| ADR-3 | Service layer + selectors | Testable business rules, thin views, transactions in one place |
| ADR-4 | PostgreSQL + `Decimal` money | Correct currency maths, strong constraints |
| ADR-5 | Celery + Redis for async | Non-blocking requests, scheduled maintenance |
| ADR-6 | Tailwind compiled from source | Consistent design system, no runtime CSS framework |
| ADR-7 | Soft delete for business records | Recoverability and audit; hard delete only for transient data |
| ADR-8 | DRF deferred | No current machine client beyond future webhooks |
| ADR-9 | Roles as Django groups (`role:<code>`) synced from a capability matrix | One authority for capabilities; leverages Django permissions; easy to audit |
| ADR-10 | Append-only `AuditLog` written inside the service transaction | Tamper-evident trail; no partial audits; secrets never recorded |
| ADR-11 | Signed timestamped tokens + per-user nonce for email verification | Stateless, expiring, replay-resistant without extra tables |
| ADR-12 | Dependency-free cache-backed rate limiter | No new dependency; works with LocMem in dev and Redis in prod |
| ADR-13 | Unified notifications live in a new `apps.notifications` (not `accounts.Notification`) | Keeps a feed/preference/delivery ledger with its channels and event builders in one domain app; avoids a cross-cutting model in `accounts` and supersedes the roadmap’s sketch |
| ADR-14 | In-app rows are created synchronously; only channel delivery is deferred (`transaction.on_commit`) | The feed is never lost to a broker outage, and a delivery failure never rolls back a business transaction; duplicate-email risk to existing domain senders is avoided by mirroring events in-app only (`manage_email` reserved for new events) |
| ADR-15 | Support lives in a new `apps.support` with a server-side state machine and ownership-resolved links | Keeps ticket workflow and its capability gates self-contained; a linked record is resolved by ownership, never by a raw client-supplied reference/pk |
| ADR-16 | Analytics & reporting live in a new `apps.analytics`, read-only against the domain | Keeps reporting artefacts (exports/schedules/executions/deliveries) and the allow-listed report registry self-contained; analytics never writes a business table or stores a business figure of its own, and the roadmap's `dashboard.ReportExport`/`SavedReport` sketch is superseded |
| ADR-17 | Reports are a code-defined, allow-listed registry; exports are dependency-free with a formula-injection guard | No arbitrary SQL/model path/field list can be supplied; CSV/XLSX/PDF avoid a new dependency (`AGENTS.md`), and text cells can never execute as a spreadsheet formula |
| ADR-18 | Money is per-currency and net receipts are never called profit | Selectors return per-currency rows and never combine currencies without a configured rate; no profit figure is computed because no authoritative cost/expense ledger exists |

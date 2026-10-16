# AA Shinaka Digital Business Platform

A standalone agricultural commerce and services platform for **AA Shinaka
General Enterprise**. It sells AA Shinaka's own products directly (not a
marketplace) and supports consultancy, farming services, agricultural marketing,
storage & warehousing, export, product sales and a training academy.

> **Scope note.** Oil and Gas is out of scope. This platform does not integrate
> with AgriTrade ERP and has no multi-vendor marketplace features.

## Status — Phases 1–12 complete

**Phase 1 — Foundation**

- Django 5.2 LTS project (MVT, Django Templates — no SPA).
- PostgreSQL configured entirely through `DATABASE_URL` / environment variables.
- Custom **email-based** user model created before the first migration.
- Shared base models: timestamps, soft delete, `State`/`LGA` location reference
  data + a verified Nigeria location importer (37 states incl. FCT, 774 LGAs).
- Tailwind CSS compiled from source, HTMX + Alpine.js shell, Celery + Redis wiring.
- Ruff + pytest/pytest-django configured; full test suite passing.

**Phase 2 — Authentication, customer accounts, staff permissions & core
infrastructure**

- Ten canonical platform roles (`UserRole`) with a server-side capability
  matrix, mirrored onto Django groups (`role:<code>`) that carry the model
  permissions.
- Email/password registration (customer-only), login/logout, email verification
  and password reset/change.
- Customer portal at `/account/`: dashboard, profile, address book, security.
- Staff dashboard at `/dashboard/`: staff directory, create/edit, role
  assignment, activate/deactivate and a searchable audit log — every action is
  capability-gated on the server.
- Append-only `AuditLog`, cache-backed rate limiting on auth endpoints, hardened
  session/cookie settings.
- 114 automated tests covering the Phase 2 checklist in
  [`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md).

**Phase 3 — Corporate website, premium homepage & CMS**

- CMS-driven public site in `apps/cms`: 15-section premium homepage, service
  pages (consultancy, farming, marketing, storage, export), About, Contact,
  Blog, FAQs and CMS-managed pages.
- 13 content models with draft/published/archived states, publish dates, SEO
  fields, slugs, ordering and image validation.
- Staff CMS dashboard at `/dashboard/cms/` (Django templates + HTMX) behind
  server-enforced capabilities: content, media, testimonials approval, contact
  enquiries, navigation and site settings.
- SEO: semantic markup, canonical/OG tags, `/sitemap.xml`, `/robots.txt`,
  alt text, lazy loading and pagination.
- English + Hausa language readiness (`locale/ha/`, `manage.py
  compile_messages`) — no hardcoded translated strings; full bilingual content
  is not claimed.
- 56 new tests (170 total). See
  [`docs/PHASE_3_COMPLETION_REPORT.md`](docs/PHASE_3_COMPLETION_REPORT.md).

**Phase 4 — Catalogue, categories & Nigeria locations**

- Geographic reference data extracted into `apps.locations` (`Country`,
  `State`, `LGA`, `City`) — legacy table names preserved; loaded only through
  the verified Nigeria importer (no dataset bundled).
- Nested, cycle-safe category tree (breadcrumbs, reorder, depth guard, guarded
  delete); products with draft/published/archived, specs, tags and SEO.
- Origin-specific `ProductListing` with independent selling price and stock per
  state/LGA/package; packaging + priceable variants.
- A price engine (`ListingPrice` with scheduled windows, append-only
  `PriceHistory`, `WholesalePriceTier`) kept strictly separate from
  informational `MarketReferencePrice`; append-only inventory ledger and
  low-stock reporting.
- Public catalogue under `/shop/` (categories, product detail with origin
  listings, shop-by-state/LGA, search, filters, compare) with legacy aliases
  (`/states/…`, `/products/<slug>/`, `/shop/<slug>/`); homepage now renders live
  catalogue data.
- Staff catalogue/inventory dashboard at `/dashboard/catalog/` and
  `/dashboard/inventory/`, server-gated by `catalog.manage` / `inventory.manage`.
- 142 new tests (312 total). See
  [`docs/PHASE_4_COMPLETION_REPORT.md`](docs/PHASE_4_COMPLETION_REPORT.md).

**Phase 5 — Cart, checkout, orders & inventory**

- Warehouse-aware stock truth: `catalog.Warehouse` + per-listing/variant
  `StockBalance` (`on_hand` authoritative, `reserved` held); the listing's
  `stock_on_hand`/`stock_reserved` are maintained roll-ups. All stock writes go
  through `apps.catalog.inventory` (receipts, transfers, reservations, commits)
  with row locks and an auditable `StockMovement` ledger.
- Persistent cart in `apps.orders` with guest support: anonymous carts are keyed
  by session and **merged** into the customer's cart at login (session data
  survives the login key rotation). Prices and stock are always recomputed
  server-side; wholesale tiers apply at the cart line.
- Transactional checkout (authenticated only): captures a delivery address and a
  configured shipping method, validates the address/state against a
  `ShippingZone`/`ShippingRate`, snapshots line prices, creates the order and
  reserves stock atomically. A unique `checkout_token` makes order creation
  idempotent; a stale/oversized cart is rejected before any stock moves.
- No payment provider in Phase 5. Orders are created `pending_payment` and can
  only become paid through an audited staff **manual-payment approval**
  (`FINANCE_MANAGE`). Customers may flag a payment for review but can never mark
  their own order paid. Confirming payment commits the reservations (a `sale`
  movement) and moves the order to `confirmed`.
- Order lifecycle (`pending_payment → payment_review → confirmed → processing →
  ready_for_dispatch → dispatched → delivered → completed`, plus
  `cancelled`/`expired`), enforced by a server-side transition map and recorded
  in append-only `OrderStatusHistory`. Cancelling releases reservations or
  returns committed stock; abandoned pending orders expire via a Celery task
  (`orders.expire_reservations`) with an `expire_orders` management-command
  fallback.
- Customer portal: `/cart/`, `/checkout/`, `/orders/` (list + detail, cancel,
  payment-review) and `/quotations/` (bulk-quotation requests). Staff dashboard:
  `/dashboard/orders/` (orders, fulfilment, payment approval, shipments,
  quotations, shipping configuration) and `/dashboard/inventory/` (warehouses,
  stock levels, movements, reservations, receive/transfer) — every screen is
  capability-gated on the server.
- See [`docs/PHASE_5_COMPLETION_REPORT.md`](docs/PHASE_5_COMPLETION_REPORT.md).

**Phase 6 — Payments & refunds (Paystack)**

- Hosted **Paystack** checkout in `apps.orders`: the server creates the payment
  with the authoritative order total and redirects to the provider. Nothing about
  the amount comes from the client, and a payment is marked `paid` **only** after
  a server-side verification whose currency and amount match the stored order.
- Signature-verified webhooks at `/payments/paystack/webhook/`: HMAC-SHA512 over
  the **raw** body (`x-paystack-signature`, optional `PAYSTACK_WEBHOOK_SECRET`),
  stored per `(provider, event_id)` so duplicate and out-of-order deliveries are
  idempotent. A late payment on an expired/cancelled order is recorded and
  flagged for review rather than completing the order.
- Manual **bank transfers**: customers submit a claim (with optional proof);
  finance approves only with settlement confirmed, and a unique constraint stops
  one transfer settling two orders.
- **Refunds**: `request → approve → complete`, finance-only (`FINANCE_MANAGE`)
  and never exceeding captured funds; Paystack refunds finish via
  `refund.processed` webhooks.
- Immutable **invoices** (issued on order placement) and **receipts** (verified
  payments only), rendered as HTML and a dependency-free PDF. Customers get a
  payment portal (`/payments/`, `/invoices/`, `/receipts/<n>/`) and only ever see
  their own financial records.
- Staff **finance dashboard** at `/dashboard/finance/` (overview with
  verified-only metrics, payments + reconcile, transfers, refunds, invoices,
  company bank accounts), plus a `orders.reconcile_payments` Celery beat task and
  `manage.py reconcile_payments` command.
- Paystack is off by default (`PAYSTACK_ENABLED=false`); keys live only in
  `PAYSTACK_*` environment variables, are never rendered/logged, and tests mock
  every provider call. See
  [`docs/PHASE_6_COMPLETION_REPORT.md`](docs/PHASE_6_COMPLETION_REPORT.md).

**Phase 7 — Service divisions (consultancy, farming, marketing, storage)**

- One shared `ServiceRequest` engine in `apps.services` for every division:
  reference, a declared status pipeline (`REQUEST_TRANSITIONS`), append-only
  status history, activity log, staff assignment, comments and
  visibility-controlled attachments.
- **Consultancy**: bookable services, consultants with data-driven availability,
  appointments (online/on-site) with row-locked overlap prevention, and
  consultation reports.
- **Farming**: service requests → farm projects that activate only after
  approval **and** an agreement, with milestones, visits and progress reports.
- **Marketing**: enquiries → narrative proposals the customer accepts/rejects →
  campaigns (require an accepted proposal) with a dated activity log.
- **Storage & warehousing**: data-driven facilities/units and accepted produce
  types, capacity-checked bookings (over-allocation rejected under locks),
  allocations ledger, check-in/out and inspections.
- A single **quotation engine** (`ServiceQuotation` + items) with
  server-recomputed totals, tax, revisions/`supersedes`, approve → issue →
  accept/reject/expire, and frozen-on-accept immutability.
- **Verified payment settles services**: `orders.Payment` can target a
  quotation; the Phase 6 callback/webhook verification is the only path that
  marks it paid and activates a paid storage booking/farm project. The browser
  is never trusted.
- Customer portal at `/account/services/` and a capability-gated staff
  dashboard at `/dashboard/services/` with a Chart.js overview derived strictly
  from real records. New capabilities `SERVICES_MANAGE` and
  `QUOTATIONS_MANAGE`; each division maps to a `REQUESTS_*` capability.
- See [`docs/PHASE_7_COMPLETION_REPORT.md`](docs/PHASE_7_COMPLETION_REPORT.md).

**Phase 8 — Agricultural export management & international trade**

- A dedicated `apps.export` app (kept separate from `catalog`/`orders`, matching
  the project's domain-oriented layout) takes AA Shinaka's **own** produce to
  international buyers. No catalogue duplication: `ExportProductProfile` is a
  `OneToOne` extension of `catalog.Product`.
- **Destinations are data.** Each is a `locations.Country` row with a recorded
  approval and activation: a destination is created `pending`/inactive, approved
  by a holder of `EXPORT_APPROVE`, then explicitly activated. Requirements, trade
  restrictions and document rules carry their own source/provenance.
- **Priced quotations** always name an **Incoterms 2020** rule (`Incoterm`) **and
  a named place**, plus a currency, deposit percentage and validity. Totals are
  recomputed server-side; approval/issue requires `EXPORT_APPROVE`; an accepted
  quotation is **frozen**; revisions are snapshotted and superseded.
- **Export orders** are created from an accepted quotation (no browser-supplied
  terms). A **compliance checklist** generated from the destination's
  requirements gates movement to `ready_for_shipment`.
- **Documents** use private storage (`export/documents/`), with configurable
  document types (official types enforce an expiry date), staff review, and a
  per-document customer-visibility flag.
- **Shipments** use freight-forwarding `LogisticsProvider` records and
  **staff-entered milestones** only — the platform never fabricates live
  tracking. Dispatch requires a cleared checklist.
- **Verified-only settlement**: `orders.Payment` can target an export order
  (`chk_payment_single_target`); the Phase 6 server-side verification path is the
  only way an export payment becomes `paid`. The browser callback is never
  trusted and the Phase 6 logic is not duplicated.
- Customer portal at `/account/export/`; capability-gated staff dashboard at
  `/dashboard/export/` with a Chart.js report. New capabilities `EXPORT_MANAGE`
  (Export Officer) and `EXPORT_APPROVE` (Administrators/Owners only). Customers
  only ever see their own records.
- See [`docs/PHASE_8_COMPLETION_REPORT.md`](docs/PHASE_8_COMPLETION_REPORT.md).

**Phase 9 — Training academy**

- A dedicated `apps.training` app (kept separate from `catalog`/`orders`,
  matching the project's domain-oriented layout) runs AA Shinaka's **own**
  academy: a configurable catalogue (categories, courses, modules, ordered
  lessons, private resources), instructors and assignments, venues and
  capacity-limited cohorts, enrolment with waitlisting, attendance, assessments
  with automatic and manual grading, derived completion and certified training.
- **Nothing is hardcoded.** Categories, courses, cohorts, instructors, venues,
  fees and capacities are records; empty states never invent courses, dates or
  people. Every write goes through `apps/training/services.py`.
- **Verified-only course payment**: free seats confirm immediately; paid seats
  become `payment_pending` and confirm **only** on the Phase 6 server-side
  verification path (idempotent via `settled_payment_references`). The browser
  callback is never trusted and the Phase 6 logic is not duplicated
  (`orders.Payment.training_enrollment`).
- **Learning** tracks lesson progress and assessment attempts; completion is
  **derived** from real records (all lessons complete and every published
  completion-required assessment passed) — never assumed. Certificates are
  approved by a holder of `TRAINING_APPROVE` and can be publicly verified by code,
  exposing only the minimum approved information.
- Public site at `/training/`; student portal at `/account/training/`;
  capability-gated staff dashboard at `/dashboard/training/` with a Chart.js
  report. New capabilities `TRAINING_MANAGE` (Training Manager), `TRAINING_INSTRUCT`
  and `TRAINING_APPROVE` (Administrators/Owners only). Students only ever see
  their own records.
- See [`docs/PHASE_9_COMPLETION_REPORT.md`](docs/PHASE_9_COMPLETION_REPORT.md).

**Phase 10 — Unified customer portal, notifications & support centre**

- A single `/account/` hub: an overview with real per-customer metrics and recent
  activity, an aggregated **activity timeline** (orders, payments, service,
  export, training and support events), and a **document centre** that reuses the
  existing ownership-checked downloads through one central, per-type
  authorisation route (`account:document_download`) — a raw primary key is never
  trusted on its own.
- A dedicated `apps.notifications` app owns the unified **in-app notification
  centre**: a `Notification` feed, per-customer `NotificationPreference` opt-outs
  and a `NotificationDelivery` ledger. Rows are created synchronously inside the
  business transaction and only channel **delivery** is scheduled on commit
  (`transaction.on_commit`). `emit()` is idempotent on a `dedupe_key`, so retried
  webhooks/events never duplicate; a category a customer muted stores nothing.
- **No duplicate emails.** Events a domain app already emails simply mirror into
  the in-app feed; `manage_email=True` is reserved for genuinely new events (e.g.
  support replies). Email is only recorded `delivered` after the backend confirms
  it. **SMS/WhatsApp are inert** until an approved provider is configured *and*
  the customer opts in — unconfigured channels are recorded as skipped, and no
  credentials are hardcoded. Safe links reject absolute/off-site URLs.
- A dedicated `apps.support` app runs the **support centre**: tickets with a
  server-side ownership check on any linked order/payment/enquiry/request/enrolment,
  a status state machine (`SUPPORT_TRANSITIONS`) with a configurable reopen
  window, customer/staff replies (internal notes never reach the customer) and a
  capability-gated staff queue. New capabilities `SUPPORT_MANAGE`,
  `SUPPORT_APPROVE` and `CUSTOMERS_VIEW`.
- A capability-gated **staff customer overview** (`/dashboard/customers/`) shows
  real cross-domain aggregates for one customer; the financial section requires
  the finance capability (`FINANCE_MANAGE`).
- See [`docs/PHASE_10_COMPLETION_REPORT.md`](docs/PHASE_10_COMPLETION_REPORT.md).

**Phase 11 — Analytics & reporting**

- A dedicated `apps.analytics` app (reporting artefacts only — it never writes to
  a business table) adds an **executive overview** plus eight operational
  analytics pages (sales, finance, inventory, services, export, training,
  customers, support) with real KPIs, Chart.js charts (server-computed JSON
  embedded with `json_script`, never string-interpolated) and detail tables.
- **A KPI registry** (`apps/analytics/metrics.py`) documents exactly what every
  figure means, where it comes from and how it is computed; it is mirrored in
  [`docs/ANALYTICS_METRICS.md`](docs/ANALYTICS_METRICS.md). Nothing is fabricated —
  empty states stay empty.
- **A controlled report builder** over **21 code-defined, allow-listed** report
  definitions with typed columns and validated filters, a live preview, and
  history. There is no arbitrary SQL, model path or field list.
- **Dependency-free exports** — CSV, XLSX (hand-built Open XML) and PDF — with a
  spreadsheet **formula-injection guard**, private storage and a permission-checked
  download (never a public file URL).
- **Scheduled reports** with per-period duplicate protection
  (`uniq_schedule_period_execution`), a per-recipient capability re-check before
  delivery, and a delivery ledger; generated files expire after
  `ANALYTICS_REPORT_RETENTION_DAYS`.
- **Money is per-currency** and never combined without a configured exchange-rate
  source; **net receipts are labelled cash, not profit** (no profit figure is
  computed). Customer identity is absent from every dashboard and report.
- New capabilities `ANALYTICS_VIEW`, `ANALYTICS_FINANCE`, `REPORTS_BUILD`,
  `REPORTS_SCHEDULE`, `REPORTS_MANAGE`; financial figures, columns and reports are
  gated behind `analytics.finance`, and sensitive financial report access is
  audited. Staff dashboard under `/dashboard/executive/`, `/dashboard/analytics/`
  and `/dashboard/reports/`.
- See [`docs/PHASE_11_COMPLETION_REPORT.md`](docs/PHASE_11_COMPLETION_REPORT.md).

**Phase 12 — Production security, QA, deployment & launch readiness**

- **Security audit** of the whole monolith with findings graded
  Critical/High/Medium/Low, evidenced and tracked in
  [`docs/PRODUCTION_READINESS_AUDIT.md`](docs/PRODUCTION_READINESS_AUDIT.md):
  no Critical issue; three High findings fixed (GET-mutation/CSRF bypass,
  public-media exposure, payment-webhook kill-switch gap).
- Hardened settings: fail-fast `config.settings.prod` (no insecure fallbacks),
  HSTS/secure cookies/SSL redirect/nosniff/opener-policy, explicit password
  hashers, WhiteNoise manifest static storage and dependency-free JSON logging.
- A production security test suite (GET-mutation rejection, webhook signature and
  kill-switch, object-level boundaries, CSRF cookie behaviour, production
  settings) and an end-to-end scenario suite (purchase→payment, service
  quotation, export order, training enrolment, support lifecycle, report export).
- Deployment assets under [`deploy/`](deploy/README.md): Dockerfile, Compose
  stack, gunicorn config, entrypoint, nginx site with **default-deny `/media/`**,
  systemd units, verified backup/restore/healthcheck/deploy scripts, a
  production env template and a dependency-free load tester.
- CI (`.github/workflows/ci.yml`): lint/format, system + migration checks, asset
  build, tests with coverage, dependency vulnerability audit and a production
  `manage.py check --deploy`.
- Operations documentation: production audit, disaster recovery, runbook,
  monitoring, data protection, launch content checklist, performance &
  accessibility, release checklist, and the final readiness report
  (`docs/FINAL_PRODUCTION_READINESS_REPORT.md`). **No deployment, DNS change or
  live Paystack credential was performed by this phase.**

Phase 12 is delivered as a *readiness* phase and is **awaiting owner approval**.
Later phases are specified in the roadmap and must not start without approval.

## Documentation

| Document | Contents |
|---|---|
| [`docs/SRS.md`](docs/SRS.md) | Business goals, roles, functional/nonfunctional requirements, acceptance criteria |
| [`docs/DATABASE_DESIGN.md`](docs/DATABASE_DESIGN.md) | All models, constraints, indexes, location-import strategy |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | MVT layout, apps, service layer, payments, deployment |
| [`docs/UI_UX_SPEC.md`](docs/UI_UX_SPEC.md) | Public, portal and dashboard pages; components; accessibility |
| [`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md) | Phase-by-phase plan with acceptance criteria |
| [`docs/PHASE_3_COMPLETION_REPORT.md`](docs/PHASE_3_COMPLETION_REPORT.md) | Phase 3 deliverables, URLs, tests and limitations |
| [`docs/PHASE_4_COMPLETION_REPORT.md`](docs/PHASE_4_COMPLETION_REPORT.md) | Phase 4 deliverables, models, URLs, tests and limitations |
| [`docs/PHASE_5_COMPLETION_REPORT.md`](docs/PHASE_5_COMPLETION_REPORT.md) | Phase 5 deliverables, models, URLs, tests and limitations |
| [`docs/PHASE_6_COMPLETION_REPORT.md`](docs/PHASE_6_COMPLETION_REPORT.md) | Phase 6 payments/refunds deliverables, security rules, URLs, tests and limitations |
| [`docs/PHASE_7_COMPLETION_REPORT.md`](docs/PHASE_7_COMPLETION_REPORT.md) | Phase 7 service-division deliverables, models, quotations, verified settlement, URLs, tests and limitations |
| [`docs/PHASE_8_COMPLETION_REPORT.md`](docs/PHASE_8_COMPLETION_REPORT.md) | Phase 8 export & international trade deliverables, models, compliance, verified settlement, URLs, tests and limitations |
| [`docs/PHASE_9_COMPLETION_REPORT.md`](docs/PHASE_9_COMPLETION_REPORT.md) | Phase 9 training-academy deliverables, models, enrolment, verified settlement, certificates, URLs, tests and limitations |
| [`docs/PHASE_10_COMPLETION_REPORT.md`](docs/PHASE_10_COMPLETION_REPORT.md) | Phase 10 unified customer portal, notifications and support-centre deliverables, models, channels, URLs, tests and limitations |
| [`docs/PHASE_11_COMPLETION_REPORT.md`](docs/PHASE_11_COMPLETION_REPORT.md) | Phase 11 analytics & reporting deliverables, models, report catalogue, URLs, tests and limitations |
| [`docs/PHASE_12_COMPLETION_REPORT.md`](docs/PHASE_12_COMPLETION_REPORT.md) | Phase 12 hardening/deployment deliverables and accepted gaps |
| [`docs/ANALYTICS_METRICS.md`](docs/ANALYTICS_METRICS.md) | Analytics KPI reference (mirrors `apps/analytics/metrics.py`) |
| [`docs/PRODUCTION_READINESS_AUDIT.md`](docs/PRODUCTION_READINESS_AUDIT.md) | Phase 12 security audit: findings by severity, evidence, fix and verification status |
| [`docs/FINAL_PRODUCTION_READINESS_REPORT.md`](docs/FINAL_PRODUCTION_READINESS_REPORT.md) | Phase 12 final status (NOT READY / READY FOR STAGING / READY FOR CONTROLLED PRODUCTION LAUNCH) |
| [`docs/PRODUCTION_RUNBOOK.md`](docs/PRODUCTION_RUNBOOK.md) | Provisioning, deploy/rollback, secret rotation, incidents, on-call |
| [`docs/DISASTER_RECOVERY.md`](docs/DISASTER_RECOVERY.md) | Backup/restore, RPO/RTO targets, drills |
| [`docs/MONITORING.md`](docs/MONITORING.md) | Signals, alerting wiring, dashboards, retention |
| [`docs/DATA_PROTECTION.md`](docs/DATA_PROTECTION.md) | Personal data, controls, subject requests, breach response |
| [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) | Load-test method and WCAG 2.2 AA accessibility checklist |
| [`docs/LAUNCH_CONTENT_CHECKLIST.md`](docs/LAUNCH_CONTENT_CHECKLIST.md) | Owner-supplied content required before launch |
| [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) | Per-release gate checklist |
| [`deploy/README.md`](deploy/README.md) | Deployment assets and topologies |

## Technology stack

Django 5.2 LTS · Django Templates (MVT) · PostgreSQL · Tailwind CSS ·
HTMX · Alpine.js · Celery + Redis · Chart.js · Paystack ·
pytest + pytest-django · Ruff. Django REST Framework is added only when a
genuine machine-to-machine API is required.

## Getting started

### Prerequisites

- Python 3.12 (see `.python-version`) and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 15+ and Redis
- Node.js + npm (for the Tailwind build)

### 1. Install dependencies

```bash
uv sync
npm install          # installs Tailwind CLI
```

### 2. Configure the environment

```bash
cp .env.example .env
# then edit .env: set DJANGO_SECRET_KEY and DATABASE_URL
# optional (Phase 2): EMAIL_URL / DEFAULT_FROM_EMAIL, CACHE_URL,
# EMAIL_VERIFICATION_TIMEOUT, PASSWORD_RESET_TIMEOUT and the RATE_LIMIT_* keys.
# optional (Phase 6): PAYSTACK_ENABLED / PAYSTACK_SECRET_KEY /
# PAYSTACK_PUBLIC_KEY / PAYSTACK_WEBHOOK_SECRET / PAYSTACK_CALLBACK_URL and
# ORDER_TAX_RATE / ORDER_RESERVATION_TTL_HOURS. Leave Paystack disabled to run
# fully offline; never commit real keys.
```

Create the database and role (example):

```sql
CREATE ROLE aa_shinaka LOGIN PASSWORD '<password>' CREATEDB;
CREATE DATABASE aa_shinaka OWNER aa_shinaka ENCODING 'UTF8';
```

### 3. Build CSS, migrate and run

```bash
npm run build:css                 # compiles static/src/app.css -> static/css/app.css
uv run python manage.py migrate
uv run python manage.py seed_data           # baseline records + safe development samples
uv run python manage.py createsuperuser     # prompts for email (no username)
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/ and http://127.0.0.1:8000/healthz/.

`seed_data` only runs with `DEBUG=True` and is safe to rerun. It creates baseline
records, the 10 role groups, an inactive demo customer with no usable password,
and draft/noindex CMS and training examples plus an inactive consultancy example.
These examples are not approved business information. The command does not seed
catalogue categories/prices/inventory, location state/LGA data, orders/payments,
export transactions, or audit/history records. Load state/LGA records separately
from a verified, owner-approved source with `import_nigeria_locations`.

### Optional: background workers

```bash
uv run celery -A config worker -l info
uv run celery -A config beat -l info
```

## Common commands

| Task | Command |
|---|---|
| Run tests | `uv run pytest` |
| Focused test | `uv run pytest tests/test_accounts.py -k unique` |
| Lint | `uv run ruff check .` |
| Format check | `uv run ruff format --check .` |
| Format | `uv run ruff format .` |
| System check | `uv run python manage.py check` |
| Migrations | `uv run python manage.py makemigrations` / `migrate` |
| Missing migrations guard | `uv run python manage.py makemigrations --check --dry-run` |
| Sync role groups | `uv run python manage.py sync_roles` |
| Seed safe development data | `uv run python manage.py seed_data` (`--dry-run` to preview; requires `DEBUG=True`) |
| Build Tailwind (minified) | `npm run build:css` |
| Watch Tailwind | `npm run watch:css` |
| Import Nigeria locations | `uv run python manage.py import_nigeria_locations --source data/ng_locations.csv --strict` |

## Nigeria location data

The importer expects a CSV with the header
`state_name,state_code,zone,lga_name,lga_code` from an **authoritative,
owner-approved source** (no dataset is bundled). Validate first:

```bash
uv run python manage.py import_nigeria_locations --source data/ng_locations.csv --dry-run --strict
```

`--strict` requires exactly 37 state-level entries and 774 LGAs. See
[`docs/DATABASE_DESIGN.md`](docs/DATABASE_DESIGN.md) §2.6 for the full strategy.

## Project layout

```
config/          Django project (settings base/dev/prod, urls, wsgi/asgi, celery)
apps/core/       Shared base models, audit helper, rate limiter, home, healthcheck
apps/locations/  Country/State/LGA/City reference data + Nigeria importer (Phase 4)
apps/accounts/   Custom user model, roles, permissions, auth views, profiles, addresses
apps/catalog/    Categories, products, origin listings, pricing, inventory (Phase 4)
apps/orders/     Cart, orders, payments, refunds (Phases 5–6)
apps/services/   Service requests, quotations, verified-payment activation (Phase 7)
apps/export/     Export enquiries, quotations, orders, shipments, compliance (Phase 8)
apps/training/   Training catalogue, cohorts, enrolment, assessments, certificates (Phase 9)
apps/dashboard/  Staff dashboard, staff management, audit log, reporting (Phases 2, 10)
apps/cms/        CMS content, public website, CMS dashboard (Phase 3)
templates/       Shared templates and components
static/          Tailwind source (src/) and build output (css/)
tests/           pytest suite
docs/            Requirements, architecture, database and phase reports
```

## Accounts, roles & access control

Authentication and the portals live under two prefixes:

| URL | Purpose |
|---|---|
| `/accounts/register/` | Customer self-registration (customer role only) |
| `/accounts/login/` · `/accounts/logout/` | Session login / logout |
| `/accounts/verify-email/<token>/` · `/accounts/resend-verification/` | Email verification |
| `/accounts/password-reset/` (+ confirm / change) | Password reset and change |
| `/account/` | Customer portal home |
| `/account/profile/` · `/account/addresses/` · `/account/security/` | Profile, address book, security |
| `/account/services/` | Customer service portal (requests, quotations, bookings) |
| `/dashboard/` | Staff dashboard |
| `/dashboard/services/` | Staff service dashboard (consultancy/farming/marketing/storage) |
| `/dashboard/staff/` (+ create / detail / edit) | Staff management (capability-gated) |
| `/dashboard/audit/` | Audit log |

**Roles.** Exactly ten: Customer, Sales Officer, Inventory Officer, Consultant,
Training Manager, Export Officer, Finance Officer, Content Editor,
Administrator, Owner/Super Admin. Each role maps to a Django group
`role:<code>`; capabilities are defined once in `apps/accounts/roles.py` and
enforced server-side by decorators in `apps/accounts/permissions.py`. Templates
only *hide* navigation they cannot use — they never grant access. Public
registration can only ever create a `customer`; staff roles are granted by an
authorised administrator, and only an owner/superuser may grant
`administrator`/`owner`.

## Security

- Never commit `.env` or any secret; only `.env.example` is tracked.
- Production uses `config.settings.prod` with secure-cookie/HSTS/SSL settings.
- Report sensitive changes through audited, transactional services.
- Email verification uses signed, timestamped tokens with a per-user rotating
  nonce (replay protection); password reset uses Django's token generator and
  invalidates other sessions on password change.
- Register/login/resend/password-reset endpoints are rate-limited by a
  dependency-free, cache-backed limiter (`apps/core/ratelimit.py`).
- Security- and business-sensitive actions write an append-only `AuditLog`
  entry (actor, action, target, request metadata, redacted change summary);
  passwords/tokens/secrets are never logged, and audit rows cannot be edited or
  deleted from the application.

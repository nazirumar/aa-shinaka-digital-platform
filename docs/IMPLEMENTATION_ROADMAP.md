# Implementation Roadmap
## AA Shinaka Digital Business Platform

| | |
|---|---|
| Document ID | AASDP-ROAD-001 |
| Version | 0.4 (Phases 1–4 delivered) |
| Status | For owner/engineering approval |

> Phases are **independent and testable**. Each phase ends with a runnable,
> verified system and an acceptance-criteria check. Execution is **strictly
> sequential after approval** — a completed phase does not proceed to the next
> automatically.
>
> **Revision note.** Phase 2 is *Authentication, customer accounts, staff
> permissions & core infrastructure*. **Phase 3 is the Corporate Website,
> Premium Homepage & Content Management** (the CMS-driven public site). The
> catalogue — previously drafted as Phase 3 — moves to **Phase 4**, and every
> later phase shifts down by one. Cross-references in `docs/SRS.md`,
> `docs/ARCHITECTURE.md` and `docs/DATABASE_DESIGN.md` follow the numbers below.
>
> **Revision 0.4.** **Phase 4 — Catalog, categories & Nigeria locations** is
> delivered (see `docs/PHASE_4_COMPLETION_REPORT.md`); every later phase is
> unchanged. Phase 5 (cart/checkout/orders) must **not** start without owner
> approval.

**Global definition of done (applies to every phase):**

- `uv run python manage.py check` clean.
- Migrations generated, reviewed, and applied from an empty database.
- `uv run python manage.py makemigrations --check` reports no missing migrations.
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- `uv run pytest` passes; new functionality is covered by tests.
- Documentation updated; no secrets committed; no hardcoded categories/prices/
  inventory/achievements; no oil-and-gas, multi-vendor, or AgriTrade ERP content.
- Changelog/summary of completed work recorded.

---

## Phase 1 — Foundation, requirements & architecture  ✅

| | |
|---|---|
| **Objective** | Establish the standalone Django project, configuration, custom user model, shared base models and verified docs, so later phases have a stable, tested base. |
| **Dependencies** | None. |
| **Apps** | `config`, `apps.core`, `apps.accounts`; skeletons for `catalog`, `orders`, `services`, `dashboard`. |
| **Features** | PostgreSQL via `DATABASE_URL`; split settings (`base`/`dev`/`prod`); custom email user before first migration; Tailwind CLI pipeline; HTMX/Alpine shell; Celery/Redis wiring; healthcheck; Ruff + pytest configuration; `.env.example`; README. |
| **Models** | `core.TimeStampedModel`, `core.SoftDeleteModel`, `core.State`, `core.LGA`, `core.NigeriaLocationImport`, `accounts.User`. |
| **Pages** | Home shell (division cards, shop-by-state placeholder), sign in, sign up. |
| **Permissions** | Public registration is customer-only; Django admin; `AUTH_USER_MODEL` wired. |
| **Validation** | Email unique/normalised; role enum; state code/name unique; LGA unique per state; location importer validates columns, zones and (strict) national totals. |
| **Tests** | Custom user (create/superuser/login/roles/uniqueness), base models (slugs, timestamps, constraints), soft delete (archive/restore/hard delete), location importer (dry-run, import, idempotency, strict failure, bad input), smoke tests (home, healthcheck, auth pages, signup cannot self-escalate). |
| **Acceptance criteria** | Django starts; PostgreSQL connects; `check`, `makemigrations --check`, migrations, Ruff and pytest all pass; custom user confirmed; all Phase 1 docs exist; prod settings pass `check --deploy` (aside from intentionally weak dev secrets). |
| **Definition of done** | ✅ Complete (see Phase 1 completion report). |

---

## Phase 2 — Authentication, customer accounts, staff permissions & core infrastructure  ✅

| | |
|---|---|
| **Objective** | Add a secure identity and access-control foundation: authentication, customer self-service accounts, a server-enforced staff permission model, audit logging and core infrastructure — so every later phase can rely on roles, accounts and an audit trail. |
| **Dependencies** | Phase 1. |
| **Apps** | `accounts` (primary), `core` (audit helper, rate limiter), `dashboard` (staff management, audit log), `config` (settings/`.env`). |
| **Features** | Ten canonical roles with a capability matrix mirrored onto Django groups (`role:<code>`) and synced by `sync_roles`; email/password registration (customer-only), login/logout; email verification (signed, expiring, replay-protected); password reset/change; customer profile & address book; staff directory with create/edit/role-assignment/activate-deactivate; append-only audit logging; cache-backed rate limiting on auth endpoints; customer portal and staff dashboard shells; auth-aware navigation. |
| **Models** | `accounts.User` (email-verified fields, rotating nonce, custom staff permissions), `accounts.Address`, `dashboard.AuditLog`. Data migration `accounts.0003` maps Phase 1 role values onto the ten roles and creates the role groups. |
| **Pages** | `/accounts/register/`, `/accounts/login/`, `/accounts/logout/`, email-verification + resend, password reset/change; `/account/` (dashboard, profile, addresses, security); `/dashboard/` (home, staff list/create/detail/edit, audit log). |
| **Permissions** | Capability matrix in `accounts/roles.py`, enforced server-side by `accounts/permissions.py` (`@capability_required`, `@staff_required`, `@role_required`) and object-level service checks. Escalation guard: only owners/superusers grant `administrator`/`owner`; no self-edit; administrators cannot manage owners. |
| **Validation** | Email normalised/unique and case-insensitive login; verification tokens time-limited and rotating; password-reset tokens; one default address per user; address LGA must belong to its state; role must be a valid canonical role; customer is the only self-assignable role. |
| **Tests** | 114 tests: registration, auth flow, email verification, password management, customer account/addresses, permission matrix, staff management + escalation guards, audit log immutability/redaction, security & rate limiting, template accessibility. |
| **Acceptance criteria** | `check`/migrations/Ruff/pytest all pass (114 passed); auth pages render; role changes are group-synced and audited; public registration cannot create staff/superusers; email verification and password reset work end-to-end; audit records capture actor/action/target/request metadata and cannot be edited or deleted by ordinary staff; no hardcoded credentials; no Phase 1 regressions. |
| **Definition of done** | ✅ Complete (see Phase 2 completion report). |

---

## Phase 3 — Corporate Website, Premium Homepage & Content Management  ✅

| | |
|---|---|
| **Objective** | Build a CMS-driven public site: reusable design system, premium homepage, public service pages (Consultancy, Farming, Marketing, Storage, Export), About/Contact/Blog/FAQs, SEO + sitemaps/robots, language readiness (Hausa), staff CMS dashboard with publish/approve/handle workflows; product previews degrade gracefully before the catalogue ships. |
| **Dependencies** | Phase 2. |
| **Apps** | `apps.cms` (public + CMS dashboard), `config` (urls/settings/middleware), `accounts` (capabilities), `core` (template tags, locale tooling), `dashboard` (nav). |
| **Features** | 15-section homepage; BusinessDivision & ServicePage models; Blog (posts/categories); Testimonials (approve/unapprove); FAQs; Team; Media; Navigation; Site settings (singleton); Contact (honeypot, rate-limited, stored enquiry); XML sitemap + robots.txt; i18n-ready (en/ha catalogue + dependency-free compile command); server-enforced CMS capabilities. |
| **Models** | `cms.MediaAsset`, `cms.SiteSetting`, `cms.NavigationItem`, `cms.Page`, `cms.HeroBanner`, `cms.BusinessDivision`, `cms.ServicePage`, `cms.ServiceCategory`, `cms.FAQ`, `cms.Testimonial`, `cms.TeamMember`, `cms.BlogCategory`, `cms.BlogPost`, `cms.ContactEnquiry`; abstract bases `SEOModel`, `PublishableModel`, `SluggedModel`. |
| **Pages** | `/`, `/services/`, `/services/<slug>/`, `/about/`, `/contact/`, `/news/`, `/news/<slug>/`, `/faqs/`, `/pages/<slug>/`, `/robots.txt`, `/sitemap.xml`; CMS dashboard under `/dashboard/cms/`. |
| **Permissions** | `CONTENT_VIEW/CONTENT_MANAGE/CONTENT_PUBLISH/MEDIA_MANAGE/TESTIMONIALS_APPROVE/CONTACT_MANAGE/NAV_MANAGE/SITE_CONFIG`; `CONTENT_EDITOR`/`TRAINING_MANAGER` granted relevant CMS caps; `ADMINISTRATOR`/`OWNER` all; server-side checks + capability mixins. |
| **Validation** | Image type/size, honeypot, contact required fields, slug uniqueness (model save), publish schedule respected, testimonial rating 1–5, invalid publish-status fallback. |
| **Tests** | 56 new Phase 3 tests covering public rendering/SEO/sitemap/i18n and dashboard permissions/publication/workflows; 114 existing unchanged. |
| **Acceptance criteria** | 170 tests pass; `check`/`makemigrations --check`/`ruff` pass; Tailwind builds; migrations applied; no hardcoded content or exclusions violated; product previews degrade gracefully; drafts hidden from public and sitemap. |
| **Definition of done** | ✅ Complete (see `docs/PHASE_3_COMPLETION_REPORT.md`). |

---

## Phase 4 — Catalog, categories & Nigeria locations  ✅

| | |
|---|---|
| **Objective** | Model nested categories, products, origin-specific listings and inventory; load verified location data; expose public catalogue browsing. |
| **Dependencies** | Phase 3; owner approval of ASSUMPTION-02 (categories) and ASSUMPTION-12 (location dataset source). |
| **Apps** | `catalog` (primary), `locations` (location data), `dashboard` (catalogue CRUD), `accounts` (permissions). |
| **Features** | Nested category tree (cycle-safe, breadcrumbs, reorder, guarded delete); product catalogue with draft/published/archived, specs, tags, SEO and audit; origin-specific listing CRUD; packaging + variants; a price engine (`ListingPrice`, `PriceHistory`, `WholesalePriceTier`) with `MarketReferencePrice` kept separate; inventory ledger with low-stock reporting; image uploads; public browsing by category/state/LGA; search, filters and compare; homepage integration; staff catalogue/inventory dashboard. |
| **Models** | `catalog.Category`, `UnitOfMeasure`, `Tag`, `Product`, `ProductVariant`, `ProductImage`, `ProductListing`, `ListingPrice`, `PriceHistory`, `WholesalePriceTier`, `MarketReferencePrice`, `StockMovement`; `locations.Country`, `State`, `LGA` seeded via importer. |
| **Pages** | Public: `/shop/`, `/shop/categories/`, `/shop/category/<slug>/`, `/shop/product/<slug>/`, `/shop/states/`, `/shop/state/<slug>/`, `/shop/state/<state>/<lga>/`, `/shop/search/`, `/shop/compare/`; legacy aliases `/shop/<slug>/`, `/states/…`, `/products/<slug>/`. Dashboard: `/dashboard/catalog/…` and `/dashboard/inventory/` low stock. |
| **Permissions** | Manage catalogue (`catalog.manage`): Sales Officer, Inventory Officer, Content Editor, Administrator, Owner. Manage price/stock & inventory (`inventory.manage`): Inventory Officer, Administrator, Owner. Public read-only browsing. |
| **Validation** | Category no-cycles + unique name per parent + max depth; slug uniqueness; listing origin+package unique; non-negative price/stock; `stock_reserved ≤ stock_on_hand`; immutability of `PriceHistory`/`StockMovement`; published product requires a category, unit, ≥1 image and ≥1 active listing. |
| **Tests** | Category nesting/cycles/breadcrumbs/reorder; product CRUD/status/specs/tags; listing constraints + images; pricing engine + history + tiers + market references; inventory ledger + low stock; public routes/search/compare/leakage guards + legacy aliases; dashboard access + CRUD; importer `--strict` on the approved dataset (37/774). |
| **Acceptance criteria** | Importer loads exactly 37 states + 774 LGAs with an audit row; public catalogue filters by category and origin; prices/stock are DB rows (none hardcoded); dashboards manage the catalogue with audit entries. |
| **Definition of done** | ✅ Complete (see `docs/PHASE_4_COMPLETION_REPORT.md`). |

---

## Phase 5 — Cart, checkout & orders

| | |
|---|---|
| **Objective** | Let customers buy directly: persistent cart, transactional checkout, order lifecycle and fulfilment views. |
| **Dependencies** | Phase 4; approvals for ASSUMPTION-03, -06, -07. |
| **Apps** | `orders`, `accounts` (addresses), `catalog` (stock), `dashboard` (fulfilment). |
| **Features** | Persistent cart; availability/price revalidation; address book; transactional order creation with stock reservation; order emails; cancellation; order history. |
| **Models** | `orders.Cart`, `CartItem`, `Order`, `OrderItem`, `OrderStatusHistory`; reuses `accounts.Address`. |
| **Pages** | `/cart/`, `/checkout/`, order confirmation; `/account/orders/`, `/account/orders/<number>/`, `/account/addresses/`; dashboard `/dashboard/orders/`. |
| **Permissions** | Customers manage their own cart/orders; Inventory Officer/Sales Officer fulfil and transition orders; Finance Officer views payments later. |
| **Validation** | Quantity ≤ available stock; unique (cart, listing); totals recomputed server-side; illegal order transitions rejected; order number unique. |
| **Tests** | Cart add/update/remove; checkout reserves stock atomically; insufficient stock rejected; order transition rules; cancellation releases stock; permission isolation between customers. |
| **Acceptance criteria** | Order creation is atomic and reserves stock; stock never goes negative under concurrent checkout (row locking test); customers only see their own orders; status history recorded for every change. |
| **Definition of done** | Global DoD + no payment provider yet (orders remain `pending_payment`). |

---

## Phase 6 — Payments & refunds (Paystack)

| | |
|---|---|
| **Objective** | Add the Paystack payment lifecycle and refund handling against the Phase 5 order model. |
| **Dependencies** | Phase 5; owner approval of ASSUMPTION-04 (tax/delivery) and ASSUMPTION-05 (refunds); Paystack keys. |
| **Apps** | `orders` (payments/refunds), `dashboard` (finance views), `config` (webhook route). |
| **Features** | Payment initialization/redirect; signature-verified idempotent webhooks; payment confirmation deducts stock; refund request/approval/processing; reconciliation. |
| **Models** | `orders.Payment`, `orders.Refund`. |
| **Pages** | Checkout payment step; payment result; `/dashboard/payments/`; refunds queue. |
| **Permissions** | Finance Officer/Administrator/Owner initiate refunds; only authorized roles approve. |
| **Validation** | Unique (provider, reference); refund ≤ payment amount; webhook signature; amount/currency match the order. |
| **Tests** | Webhook signature accepted/rejected; duplicate webhook is idempotent; successful payment deducts stock and sets order paid; failed payment releases reservation; refund state machine. |
| **Acceptance criteria** | Duplicate/replayed webhooks never double-deduct stock or double-record payment; secrets from env only; refunds require approval and are audited. |
| **Definition of done** | Global DoD + Paystack sandbox end-to-end verified. |

---

## Phase 7 — Service divisions (consultancy, farming, marketing, storage)

| | |
|---|---|
| **Objective** | Capture and manage requests for the consultancy, farming, marketing and storage divisions. |
| **Dependencies** | Phases 4–5 (locations, users); ASSUMPTION-01 (permission matrix). |
| **Apps** | `services`, `dashboard`, `accounts`. |
| **Features** | Request forms + status pipelines; staff assignment; storage intake/release records; unified request queues; email notifications. |
| **Models** | `services.ServiceRequest` (abstract), `ConsultancyRequest`, `FarmingServiceRequest`, `MarketingRequest`, `StorageFacility`, `StorageRequest`, `StorageRecord`. |
| **Pages** | `/consultancy/`, `/farming-services/`, `/marketing/`, `/storage/` + request forms; `/account/requests/`; dashboard division queues + `/dashboard/storage/`. |
| **Permissions** | Per-division staff (Consultant, Inventory Officer, Sales Officer) manage their queues; Administrators/Owners see all; customers see only their own requests. |
| **Validation** | Required fields per request; state/LGA valid; quantities positive; storage release ≤ intake; status transitions valid. |
| **Tests** | Each request service (create/assign/transition); record intake/release; permission isolation; email task enqueued. |
| **Acceptance criteria** | All four divisions capture and advance requests with history; customers track statuses in the portal; staff queues respect roles. |
| **Definition of done** | Global DoD. |

---

## Phase 8 — Export & Training/Academy

| | |
|---|---|
| **Objective** | Add international export enquiries/quotations and the training academy with cohorts and enrollment. |
| **Dependencies** | Phase 7; approvals for ASSUMPTION-08 (export currency/incoterms) and ASSUMPTION-09 (course fees/certificates). |
| **Apps** | `services`, `dashboard`, `orders` (optional course payment). |
| **Features** | Export enquiry → quotation → pipeline; course catalogue, cohorts, capacity-limited enrollment, trainee records. |
| **Models** | `services.ExportEnquiry`, `TrainingCourse`, `TrainingCohort`, `TrainingEnrollment`. |
| **Pages** | `/export/` + enquiry form; `/training/` + course detail + enroll; `/account/training/`; dashboard export pipeline + training management. |
| **Permissions** | Export Officer manages the pipeline; Training Manager manages courses/cohorts; Administrators/Owners oversee. |
| **Validation** | Destination country required; volume positive; cohort capacity enforced; unique (cohort, trainee). |
| **Tests** | Enquiry pipeline transitions; capacity limits; enrollment uniqueness; permission checks; optional course payment hook. |
| **Acceptance criteria** | Export enquiries capture international destinations and advance through stages; enrollment respects capacity; courses are data-driven with owner-set fees (no invented values). |
| **Definition of done** | Global DoD. |

---

## Phase 9 — Customer portal & notifications

| | |
|---|---|
| **Objective** | Deliver a complete, unified customer portal and notification system. |
| **Dependencies** | Phases 5–8; ASSUMPTION-10 (notification channels). |
| **Apps** | `accounts`, `dashboard` (notifications), all domain apps. |
| **Features** | Portal dashboard, combined orders/requests/enrollments; in-app notifications; transactional email templates; profile/address/security management; account deactivation. |
| **Models** | `accounts.Notification` (address book already delivered in Phase 2). |
| **Pages** | `/account/` home, orders, requests, training, profile, addresses, security; notification centre. |
| **Permissions** | Strict per-user isolation; staff notifications scoped to their role queues. |
| **Validation** | Notification ownership; cannot read others’ records; safe redirects after login. |
| **Tests** | Portal access control (no cross-user leakage); notification read/unread; email tasks; profile/address CRUD. |
| **Acceptance criteria** | A customer can manage everything about their relationship with AA Shinaka in one place; zero cross-user data exposure in automated tests. |
| **Definition of done** | Global DoD. |

---

## Phase 10 — Staff dashboard, reporting & audit

| | |
|---|---|
| **Objective** | Complete role-aware dashboards, reporting/analytics and a tamper-evident audit trail. |
| **Dependencies** | Phases 4–9; ASSUMPTION-11 (retention/deletion). |
| **Apps** | `dashboard`, all domain apps. |
| **Features** | Role-aware dashboard home with KPIs; sales/stock/service/export/training reports; Chart.js charts; CSV export via Celery; searchable audit log; user/role management. (The audit log and staff/role management foundation shipped in Phase 2.) |
| **Models** | `dashboard.ReportExport`, `SavedReport` (AuditLog already delivered in Phase 2). |
| **Pages** | `/dashboard/`, `/dashboard/reports/`, `/dashboard/audit/`, `/dashboard/users/`. |
| **Permissions** | Reports limited by role (see SRS §21.3); audit log admin/finance-viewable; user management administrator/owner. |
| **Validation** | Report date ranges bounded; export authorisation; audit entries immutable. |
| **Tests** | KPI/aggregation correctness; chart data endpoints; audit written for every sensitive service; CSV generation task; role-based report access. |
| **Acceptance criteria** | Every sensitive mutation produces an audit row; reports compute from real data only (no placeholders); dashboard enforces role permissions. |
| **Definition of done** | Global DoD. |

---

## Phase 11 — Hardening, performance & deployment

| | |
|---|---|
| **Objective** | Production readiness: security, performance, observability and automated deployment. |
| **Dependencies** | Phases 1–10. |
| **Apps** | `config` (settings/infra), all apps. |
| **Features** | Broader rate limiting; 2FA option for staff; vendored/pinned static assets; image optimisation; caching; error tracking & metrics; backups; CI/CD; production runbook; load testing. (Auth-endpoint rate limiting already shipped in Phase 2.) |
| **Models** | None (infrastructure/ops). |
| **Pages** | Operational pages: 403/404/500, maintenance. |
| **Permissions** | Final permission-matrix sign-off (ASSUMPTION-01). |
| **Validation** | Dependency and secret auditing; `check --deploy` clean with real secrets; accessibility and performance budgets. |
| **Tests** | End-to-end critical journeys; load/concurrency tests; security tests (authz, CSRF, headers); backup/restore drill. |
| **Acceptance criteria** | Staging deployment passes the full gate and a smoke run of every division; documented rollback; no high-severity findings outstanding. |
| **Definition of done** | Global DoD + operational sign-off. |

---

## Cross-phase dependency graph

```
P1 Foundation
 └─> P2 Auth, accounts & access control
      └─> P3 Corporate website & CMS
           └─> P4 Catalog + Locations
                └─> P5 Cart/Checkout/Orders
                     └─> P6 Payments/Refunds
                └─> P7 Services (consultancy/farming/marketing/storage)
                     └─> P8 Export + Training
                          └─> P9 Portal + Notifications
                               └─> P10 Dashboard + Reporting + Audit
                                    └─> P11 Hardening + Deployment
```

## Requirement traceability

| SRS area | Phase |
|---|---|
| FR-AUTH, FR-SEC (base) | 1 (partial), 2, 9, 11 |
| FR-CMS (website, content) | 3 |
| FR-CAT, FR-LOC, FR-PRICE | 4 |
| FR-ORD | 5 |
| FR-PAY | 6 |
| FR-CON, FR-SRV (farming/marketing/storage) | 7 |
| FR-EXP, FR-TRN | 8 |
| FR-PORTAL, FR-NOTIF | 9 |
| FR-DASH, FR-REP | 10 |
| NFR hardening | 11 |

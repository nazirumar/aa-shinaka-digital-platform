# Implementation Roadmap
## AA Shinaka Digital Business Platform

| | |
|---|---|
| Document ID | AASDP-ROAD-001 |
| Version | 1.1 (Phases 1–11 delivered) |
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
> unchanged.
>
> **Revision 0.5.** **Phase 5 — Cart, checkout, orders & inventory** is delivered
> (see `docs/PHASE_5_COMPLETION_REPORT.md`). It ships **no payment provider**:
> orders are created `pending_payment` and only an audited staff
> manual-payment approval (`FINANCE_MANAGE`) can mark them paid. Phase 6
> (Paystack payments & refunds) must **not** start without owner approval.
>
> **Revision 0.6.** **Phase 6 — Payments & refunds (Paystack)** is delivered
> (see `docs/PHASE_6_COMPLETION_REPORT.md`). It adds card/hosted Paystack
> checkout, signature-verified idempotent webhooks, manual bank-transfer review,
> refunds, immutable invoices/receipts, customer payment/invoice portals and a
> finance dashboard with reconciliation. Every provider call is mocked in tests;
> all keys come from `PAYSTACK_*` env vars. Phase 7 must **not** start without
> owner approval.
>
> **Revision 0.7.** **Phase 7 — Service divisions** is delivered (see
> `docs/PHASE_7_COMPLETION_REPORT.md`): a shared request engine, per-division
> records, a reusable quotation engine and verified-payment activation.
>
> **Revision 0.8.** **Phase 8 — Agricultural export management & international
> trade** is delivered (see `docs/PHASE_8_COMPLETION_REPORT.md`) in a dedicated
> `apps.export` app. The training academy originally bundled with this phase is
> split out and delivered as Phase 9.
>
> **Revision 0.9.** **Phase 9 — Training academy** is delivered (see
> `docs/PHASE_9_COMPLETION_REPORT.md`) in a dedicated `apps.training` app:
> configurable categories, courses/modules/lessons and private resources,
> instructors and assignments, venues and capacity-limited cohorts, enrolment
> with waitlisting, verified-only course payment, attendance, assessments with
> automatic and manual grading, derived completion, and approved certificates.
> Repurposing Phase 9 means the *customer-portal & notification* work originally
> pencilled here moves to **Phase 12**. Phases 10+ must **not** start without
> owner approval.
>
> **Revision 1.0.** **Phase 10 — Unified customer portal, notifications & support
> centre** is delivered (see `docs/PHASE_10_COMPLETION_REPORT.md`). Per the
> approved task spec, this phase brings the *customer-portal & notification*
> consolidation forward from the pencilled Phase 12 and adds a new **support
> centre** (`apps.support`). The portal/notification work now lives in two new
> domain apps — `apps.notifications` (feed, preferences, delivery ledger) and
> `apps.support` (tickets, workflow) — and the unified `/account/` hub gains a
> document centre, an activity timeline and a capability-gated staff customer
> overview. The previously-drafted **Staff dashboard, reporting & audit** and
> **Hardening, performance & deployment** phases are **renumbered to Phase 11 and
> Phase 12** respectively; the old Phase 12 portal section is replaced by the
> delivered Phase 10. Phases 11+ must **not** start without owner approval.
>
> **Revision 1.1.** **Phase 11 — Analytics & reporting** is delivered (see
> `docs/PHASE_11_COMPLETION_REPORT.md`) in a new `apps.analytics` app. Reporting
> moved out of the sketched `dashboard.ReportExport`/`SavedReport` into
> `apps.analytics` (`ReportExport`, `ScheduledReport`, `ReportExecution`,
> `ReportDelivery`). Phase 12 (Hardening, performance & deployment) must **not**
> start without owner approval.

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

## Phase 5 — Cart, checkout, orders & inventory  ✅

| | |
|---|---|
| **Objective** | Let customers buy directly: persistent cart (guest-capable), transactional checkout, an explicit order lifecycle, stock reservations and fulfilment/inventory screens. |
| **Dependencies** | Phase 4; approvals for ASSUMPTION-07 (no guest checkout) and the shipping/expiry assumptions. |
| **Apps** | `orders` (cart/checkout/orders/quotations/shipping), `catalog` (warehouses, balances, stock ops), `accounts` (addresses, capabilities), `dashboard` (navigation). |
| **Features** | Persistent cart with guest sessions merged on login; server-side price/availability revalidation; warehouse-aware stock (`StockBalance`, `StockMovement` ledger); transactional order creation with per-warehouse reservations and expiry; order lifecycle + append-only history; manual-payment approval (no provider); cancellation/restock; shipping zones/methods/rates; bulk quotation requests; customer order portal; staff orders + inventory dashboards. |
| **Models** | `catalog.Warehouse`, `catalog.StockBalance` (plus `StockMovement.variant`/`warehouse`); `orders.ShippingZone`, `ShippingMethod`, `ShippingRate`, `Cart`, `CartItem`, `StockReservation`, `Order`, `OrderItem`, `OrderStatusHistory`, `Shipment`, `QuotationRequest`; reuses `accounts.Address`. |
| **Pages** | `/cart/`, `/checkout/`, `/orders/`, `/orders/<number>/`, `/quotations/`, `/quotations/new/<listing>/`; dashboard `/dashboard/orders/` (orders, shipments, quotations, shipping config) and `/dashboard/inventory/` (warehouses, stock, movements, reservations, receive/transfer). |
| **Permissions** | Customers manage only their own cart/orders/quotations; `ORDERS_MANAGE` (Sales/Inventory/Finance/Admin/Owner) fulfils and transitions; only `FINANCE_MANAGE` (Finance/Admin/Owner) may confirm payment; `INVENTORY_MANAGE` (Inventory/Admin/Owner) guards warehouse/stock screens. Enforced in services/views, never in templates. |
| **Validation** | Quantity ≤ available (`on_hand − reserved`); unique (cart, listing); money `Decimal` only; totals recomputed and line prices snapshotted server-side; illegal order transitions and unpaid fulfilment rejected; `checkout_token` idempotency; unique order number; checkout blocked without a configured rate. |
| **Tests** | Cart add/update/remove + guest merge; server-side pricing (live price + wholesale tiers); checkout gating, idempotency and oversell rejection; reservation commit/release/expiry; state-machine and payment-approval boundaries; staff orders + inventory dashboard access and writes; customer order portal isolation and quotations. |
| **Acceptance criteria** | Order creation is atomic and reserves stock (row locks); stock never goes negative; customers only see their own orders; every status change is recorded; checkout + order portal are authenticated-only. |
| **Definition of done** | ✅ Complete (see `docs/PHASE_5_COMPLETION_REPORT.md`). No payment provider yet — orders remain `pending_payment` until an audited staff approval. |

---

## Phase 6 — Payments & refunds (Paystack)  ✅

| | |
|---|---|
| **Objective** | Add the Paystack payment lifecycle and refund handling against the Phase 5 order model. |
| **Dependencies** | Phase 5; Paystack keys/approval. Delivered with `PAYSTACK_ENABLED` off by default; every provider call is mocked in tests (no live keys needed). |
| **Apps** | `orders` (payments/refunds/service + finance & customer views), `config` (webhook route, `PAYSTACK_*` settings). |
| **Features** | Hosted Paystack initialize/redirect; server-side verification; signature-verified, deduplicated webhooks; provider/manual settlement on the shared idempotent `settle_order`; customer payment portal; bank-transfer claim + finance review; refund request/approval/completion; immutable invoices/receipts (HTML + dependency-free PDF); finance dashboard; reconciliation task + command; email notifications. |
| **Models** | `orders.Payment`, `orders.PaymentAttempt`, `orders.PaymentWebhookEvent`, `orders.Refund`, `orders.CompanyBankAccount`, `orders.BankTransferSubmission`, `orders.Invoice`, `orders.Receipt`. |
| **Pages** | `/orders/<n>/pay/`, `/orders/<n>/payment/callback/`, `/orders/<n>/bank-transfer/`, `/payments/`, `/invoices/`, `/receipts/…`, and the gated `/dashboard/finance/…` (overview, payments, transfers, refunds, invoices, bank accounts). |
| **Permissions** | `FINANCE_MANAGE` (Finance/Admin/Owner) manages payments, bank accounts, transfers and refunds; customers see only their own financial records; webhook is public but signature-gated. |
| **Validation** | Unique `Payment.reference`; webhook HMAC-SHA512 over the raw body; amount + currency must match the stored order total (never the browser); unique `(provider, event_id)`; one approved transfer per `(reference, account)`; refunds ≤ captured funds; invoices/receipts immutable after issue. |
| **Tests** | Provider calls monkeypatched: initialize/verify/settle, idempotency, underpay + currency mismatch, bad-signature and duplicate/malformed webhooks, late payment after expiry, bank-transfer approval rules and duplicate-settlement guard, refund limits/state, invoice immutability, receipt-only-for-verified, ownership isolation, finance capability gating, verified-only metrics and reconciliation. |
| **Acceptance criteria** | A payment is `paid` only after server-side verification; duplicate/replayed webhooks never double-settle or double-commit stock; secrets never leak; refunds require finance approval and are audited; customers are isolated; finance metrics derive from verified payments only. |
| **Definition of done** | ✅ Complete (see `docs/PHASE_6_COMPLETION_REPORT.md`). Global DoD met; Paystack sandbox/credential wiring is the only owner-supplied step. |

---

## Phase 7 — Service divisions (consultancy, farming, marketing, storage)  ✅

| | |
|---|---|
| **Objective** | Capture, price, settle and fulfil requests for the consultancy, farming, marketing and storage divisions, with a shared request engine, quotations, verified payment and dual (customer/staff) portals. |
| **Dependencies** | Phases 4–6 (locations, users, order/payment infrastructure); ASSUMPTION-01 (permission matrix). |
| **Apps** | `services` (models/services/selectors/forms/views/dashboard), `orders` (quotation payments), `accounts` (capabilities), `dashboard` (navigation). |
| **Features** | One concrete `ServiceRequest` with a shared status pipeline (`REQUEST_TRANSITIONS`), status history, activity log, staff assignment and comments/attachments; per-division detail models; consultancy booking/availability/overlap prevention + consultation reports; farming requests → projects → agreement-gated activation, milestones and progress reports; marketing enquiry → narrative proposal → campaign → activity log (campaign requires an accepted proposal); storage facility/unit capacity accounting, bookings, allocations, check-in/out and inspections; a single `ServiceQuotation` engine (items, totals, tax, revision/`supersedes`, approval/issue/accept/reject/expire, frozen-on-accept); verified-payment settlement reusing the Phase 6 pipeline; customer portal (`/account/services/`); capability-gated staff service dashboard with a Chart.js overview derived from real records; idempotent email notifications. |
| **Models** | `services.ServiceRequest`, `ServiceRequestStatusHistory`, `ServiceAssignment`, `ServiceComment`, `ServiceAttachment`, `ServiceActivityLog`, `ServiceNotificationLog`; `ConsultancyService`, `Consultant`, `ConsultantAvailability`, `ConsultationAppointment`, `ConsultationReport`; `FarmingService`, `FarmServiceRequest`, `FarmProject`, `FarmMilestone`, `FarmProgressReport`; `MarketingService`, `MarketingEnquiry`, `MarketingProposal`, `MarketingCampaign`, `MarketingActivity`; `StorageFacility`, `StorageUnit`, `ProduceType`, `StorageServiceRequest`, `StorageBooking`, `StorageCapacityAllocation`, `StorageCheckIn`, `StorageCheckOut`, `StorageInspection`; `ServiceQuotation`, `ServiceQuotationItem`. `orders.Payment` gains an optional `service_quotation` target (`chk_payment_single_target`). |
| **Pages** | Customer `/account/services/` (home, requests, the four request forms, quotations, quotation pay + callback, proposal decision); staff `/dashboard/services/` (home with Chart.js, request queue + detail, consultancy confirm/complete, farming projects, marketing, storage facilities/bookings, quotations). |
| **Permissions** | `SERVICES_MANAGE` gates the dashboard; `QUOTATIONS_MANAGE` gates approval/issue; per-division `REQUESTS_*` capabilities gate each queue; customers see only their own records. Enforced in services/views, never in templates. |
| **Validation** | Server-recomputed quotation totals; accepted quotations frozen; only a verified payment (never the browser callback) activates a paid service; appointment overlap rejected under row locks; storage capacity cannot be over-allocated; end date after start date; positive quantities; illegal status transitions rejected. |
| **Tests** | `tests/test_services.py`: request engine (reference, history, transitions/auto-review, assignment, comments, attachment type/size limits, notification dedupe, division isolation); consultancy (booking, mode support, availability/confirm, overlap, report + completion); farming (budget guard, agreement-gated activation, milestones, progress); marketing (proposal lifecycle, campaign requires accepted proposal, activity, completion); storage (capacity reserve, overbooking, unit ceiling, check-in/out, unaccepted produce); quotations (totals, full workflow + immutability, capability gate, revise/supersede, expiry); verified settlement (idempotent, activates paid storage, ignores non-quotation payments); portal/dashboard access control, render smoke and URL reversal. |
| **Acceptance criteria** | All four divisions capture and advance requests with history; quotations are priced server-side and frozen on acceptance; no paid service activates without a verified payment; customers only see their own records and staff queues respect their capabilities; dashboards chart real records only. |
| **Definition of done** | ✅ Complete (see `docs/PHASE_7_COMPLETION_REPORT.md`). Global DoD met. |

---

## Phase 8 — Agricultural export management & international trade  ✅

> **Scope refinement.** The original roadmap bundled *Export* with
> *Training/Academy*. This phase delivers **export and international trade only**,
> in a dedicated `apps.export` app (mirroring how `orders` is separate from
> `catalog`). The training academy (course catalogue, cohorts, capacity-limited
> enrollment, ASSUMPTION-09) is **not** delivered here and ships as **Phase 9**
> in the dedicated `apps.training` app.
>
> **ASSUMPTION-08 (export currency/incoterms)** is resolved as data: a quotation
> names an explicit **Incoterms 2020** rule **and a named place**, a
> currency, and (optionally) an exchange-rate reference. Destinations are
> `locations.Country` rows — never hand-entered — and only activate after a real
> approval (`EXPORT_APPROVE`) followed by a staff activation.

| | |
|---|---|
| **Objective** | Take AA Shinaka's own produce to international buyers: destination/eligibility configuration, export enquiries, priced quotations (Incoterms + named place), export orders, compliance checklists, private documents, freight-forwarding shipments/milestones, and verified-only settlement — through a customer portal and a capability-gated staff dashboard. |
| **Dependencies** | Phases 4–7 (catalog, locations, users, approvals, payment infrastructure); ASSUMPTION-08. |
| **Apps** | `export` (new: models/services/selectors/forms/validators/notifications/payments/views/dashboard_urls), `orders` (export payment target), `accounts` (capabilities), `catalog` (`ExportProductProfile` extends `Product`), `locations` (destination countries), `dashboard` (audit + navigation). |
| **Features** | Configurable destinations (approved → activated) with requirements, trade restrictions and source provenance; `ExportProductProfile` (no catalogue duplication) with allow-lists and minimum export quantities; export enquiries → priced quotations (Incoterms 2020 + named place, currency, deposit, revisions/supersede) → accepted export orders with frozen terms; compliance checklists generated from destination requirements; private (non-public storage) export documents with review/verification and customer visibility; shipments with freight-forwarding providers and **staff-entered** milestones (never fabricated live tracking); verified-only settlement via the Phase 6 pipeline; customer portal `/account/export/`; staff dashboard `/dashboard/export/` with Chart.js reports. |
| **Models** | `export.ExportDestination`, `ExportDestinationRequirement`, `ExportTradeRestriction`, `ExportProductProfile`; `ExportEnquiry`, `ExportEnquiryItem`, `ExportEnquiryAttachment`, `ExportEnquiryStatusHistory`; `ExportQuotation`, `ExportQuotationItem`, `ExportQuotationRevision`; `ExportOrder`, `ExportOrderItem`, `ExportOrderStatusHistory`; `ExportDocumentType`, `ExportDocument`, `ExportDocumentRequirement`, `ExportDocumentReview`; `ExportComplianceChecklist`, `ExportComplianceChecklistItem`; `LogisticsProvider`, `ExportShipment`, `ExportShipmentItem`, `ShipmentMilestone`, `ShipmentDocument`; `ExportNotificationLog`. `orders.Payment` gains an `export_order` target (`chk_payment_single_target`). |
| **Pages** | Customer `/account/export/` (home, enquiries + create + detail, quotations + accept, orders + pay + document upload, shipment tracking, payment callback); staff `/dashboard/export/` (home with Chart.js, destinations + requirements/restrictions/document rules, product configuration, enquiries, quotations + approve/revise, orders, documents + review, compliance, shipments + milestones, logistics providers, reports). |
| **Permissions** | `EXPORT_MANAGE` gates the dashboard; `EXPORT_APPROVE` gates destination approval and quotation approval/issue (Administrators/Owners only). Customers see and act on only their own records; enforcement is in services/views, never templates. |
| **Validation** | Destination countries are `locations.Country` rows and must be approved **and** active; active trade restrictions/product allow-lists block ineligible items; prices are server-recomputed and an accepted quotation is frozen; a quotation requires an Incoterms **version** and **named place**; shipment dispatch requires a cleared compliance checklist; official document types enforce expiry; milestones are staff-entered; a payment is `paid` only after server-side verification. |
| **Tests** | `tests/test_export.py` (with `tests/export_helpers.py`): destinations (pending → approved → activated), product profiles/restrictions/minimums, enquiry creation + transitions, quotation issue/approve/accept/freeze/revise, order lifecycle + compliance gate, documents (expiry, review, customer visibility), shipments + milestones, verified export payments (ownership, settle, revenue isolation), reporting selectors, and portal/dashboard access control + render smoke. |
| **Acceptance criteria** | Destinations, rates and documents are data-driven (nothing guessed); no catalogue duplication; a verified payment is the only path to "paid"; customers are strictly isolated; staff queues respect capabilities; milestones are never fabricated. |
| **Definition of done** | ✅ Complete (see `docs/PHASE_8_COMPLETION_REPORT.md`). Global DoD met. Training/Academy is delivered in Phase 9. |

---

## Phase 9 — Training academy  ✅

> **Scope.** The training academy split out of Phase 8 ships here in a dedicated
> `apps.training` app (mirroring `apps.export`). Course payment reuses the Phase 6
> verified-payment pipeline through `orders.Payment.training_enrollment`;
> notifications reuse `orders.notifications.send_notification`; certificates
> render with the dependency-free `orders.documents` PDF helper. Nothing is
> hardcoded — categories, courses, cohorts, instructors, venues, fees and
> capacities are all records.

| | |
|---|---|
| **Objective** | Run AA Shinaka's **own** training academy as a first-class, auditable workflow: a configurable course catalogue with modules/lessons and private resources, instructors and assignments, venues and capacity-limited cohorts, enrolment (including waitlisting), verified-only course payment, attendance, assessments with automatic and manual grading, derived completion and approved certificates — served through the public site, a student portal and a capability-gated staff dashboard. |
| **Dependencies** | Phases 4–8 (catalog, locations, users, approvals, verified-payment infrastructure, notification and PDF helpers). |
| **Apps** | `training` (new: models/services/selectors/forms/validators/notifications/payments/documents/views + public, student and staff URLconfs), `orders` (training payment target), `accounts` (capabilities), `dashboard` (audit + navigation). |
| **Features** | Configurable training categories (never a hardcoded list); courses with modules, ordered lessons (with preview lessons) and private resources; instructor profiles and course/session assignments; venues; cohorts (sessions) with a capacity and a fee; enrolment with transactional capacity enforcement and waitlisting; free vs paid enrolment where a paid seat confirms **only** after server-side payment verification; attendance registers and records; assessments (automatic objective grading, manual written-answer grading), attempts and pass marks; derived course completion (all lessons + all published completion-required assessments) and progress tracking; certificate templates and certificates **approved by staff** (`TRAINING_APPROVE`) with public code verification; schedule entries; reporting selectors rendered with Chart.js from real records only. |
| **Models** | `training.TrainingCategory`, `Course`, `CourseModule`, `CourseLesson`, `CourseResource`; `InstructorProfile`, `InstructorAssignment`; `TrainingVenue`, `TrainingSession`, `TrainingSessionSchedule`, `Enrollment`, `EnrollmentRequirement`; `AttendanceSession`, `AttendanceRecord`; `Assessment`, `AssessmentQuestion`, `AssessmentOption`, `AssessmentSubmission`, `AssessmentResult`; `LessonProgress`, `CourseProgress`; `CertificateTemplate`, `Certificate`, `CertificateVerificationLog`; `TrainingNotificationLog`. `orders.Payment` gains a `training_enrollment` target (`chk_payment_single_target`). |
| **Pages** | Public `/training/` (home, course list + detail, category, session list + detail, enrol, certificate verification); student `/account/training/` (home, my courses, upcoming sessions, enrolments + detail, lesson completion, assessments, resource download, certificates + view/download, payment history); staff `/dashboard/training/` (home with Chart.js, categories, courses/modules/lessons/resources, instructors + assignments, venues, sessions + schedules, enrolments + actions, attendance registers + marking, assessments/questions/options + publish + grading, certificates + templates + issue/revoke, reports). |
| **Permissions** | `TRAINING_MANAGE` gates course/content/session/instructor/venue/enrolment/attendance work; `TRAINING_APPROVE` gates course publication and certificate issue/revoke (Administrators/Owners); `TRAINING_INSTRUCT` combined with an active assignment allows teaching surfaces. Students see and act on only their own enrolments, progress, submissions and certificates; enforcement is in the service/view layer, never templates. |
| **Validation** | Sessions validate date ordering and enrollment deadlines; enrolment is capacity-checked with `select_for_update()` and rejects duplicate active requests, closed sessions and past deadlines; only verified payments settle an enrolment, idempotently, and a browser callback never confirms one; attendance statuses are validated and lesson/course mismatches rejected; submissions obey attempt limits and course membership; completion is derived from real records and never for empty content; certificates require `TRAINING_APPROVE` and a completed, certificate-eligible course, with duplicates blocked. |
| **Tests** | `tests/test_training.py` (with `tests/training_helpers.py`): categories, course publication gate + illegal transitions, lesson/resource access control, instructors and assignments, session schedule and transitions, free/paid/capacity/waitlist/duplicate/deadline enrolment, verified-only settlement (ownership, partial, idempotency, isolation, callback), attendance, assessments (auto/manual grading, attempts, gates), progress and completion, certificates (issue/revoke/verify/PDF), public site, student portal scoping, notifications, reporting selectors, dashboard permissions and URL reversal. |
| **Acceptance criteria** | Course, cohort and certificate data are records (nothing invented); a paid seat confirms only after a verified payment; students are strictly isolated to their own records; staff surfaces respect capabilities; completion is derived from real progress; dashboards chart real records only. |
| **Definition of done** | ✅ Complete (see `docs/PHASE_9_COMPLETION_REPORT.md`). Global DoD met. |

---

## Phase 10 — Unified customer portal, notifications & support centre  ✅

> **Scope.** Delivered per the approved task spec: the *customer-portal &
> notification* consolidation (pencilled as Phase 12) plus a new **support
> centre**. Implemented in two new domain apps — `apps.notifications` (feed,
> preferences, delivery ledger) and `apps.support` (tickets, workflow) — with the
> portal surfaces added to `apps.accounts`. This supersedes the roadmap's former
> `accounts.Notification` sketch: `Notification` lives in `apps.notifications`.

| | |
|---|---|
| **Objective** | Give every customer one authenticated place to see everything about their relationship with AA Shinaka, be told about genuine state changes, and get help — and give staff a scoped, capability-gated view of a customer and a support queue — without ever duplicating an existing domain email or trusting a browser-supplied reference. |
| **Dependencies** | Phases 2–9 (users/roles, addresses, orders/payments, services, export, training, audit); ASSUMPTION-10 (notification channels). |
| **Apps** | `notifications` (new), `support` (new), `accounts` (portal hub, documents, activity, staff customer overview), `dashboard` (nav; audit), domain apps (`orders`, `services`, `export`, `training`) emit events. |
| **Features** | Unified `/account/` hub (overview metrics + recent activity); cross-domain **activity timeline**; **document centre** reusing existing ownership-checked downloads through one central per-type route; unified **in-app notification centre** with per-customer preferences and a delivery ledger; synchronous in-transaction notification rows with delivery scheduled `on_commit`; idempotent `emit()`; event-driven mirroring of domain events (orders/payments, services, export, training) with **no duplicate emails**; real email delivery recorded only after the backend confirms it; inert SMS/WhatsApp channels; safe (same-site) links; **support centre** with ownership-checked linked records, a status state machine and a configurable reopen window; internal staff notes; capability-gated staff queue; capability-gated staff customer overview. |
| **Models** | `notifications.Notification`, `NotificationPreference`, `NotificationDelivery`; `support.SupportTicket`, `SupportMessage`, `SupportAttachment`, `SupportStatusHistory`. `apps.core` gains the shared `UUIDTimeStampedModel`. `accounts.Notification` is **not** created (superseded). |
| **Pages** | Customer `/account/` (dashboard metrics, activity, documents + central download), `/notifications/` (centre, preferences, badge, open), `/support/` (home, new ticket, ticket detail, reply, close/reopen, attachment download); staff `/dashboard/support/` (queue, ticket detail, assign, status, priority, reply) and `/dashboard/customers/` (directory, customer overview). |
| **Permissions** | New capabilities `SUPPORT_MANAGE` (queue/replies/assignment), `SUPPORT_APPROVE` (priority/approval-class actions) and `CUSTOMERS_VIEW` (staff customer overview). Sales/Finance officers get `CUSTOMERS_VIEW`; Administrators/Owners get all. Financial rows on the customer overview additionally require `FINANCE_MANAGE`. Strict per-customer isolation everywhere; enforcement in services/views, never templates. |
| **Validation** | Notification rows are idempotent on `dedupe_key` and a muted category stores nothing; only same-site relative links are kept; a delivery is `delivered` only when the backend confirms it; unconfigured channels are skipped (never fabricated). Support tickets require subject + message; linked records are ownership-checked server-side (never trusting a raw reference/pk); only legal status transitions are allowed; reopening is bounded by the configured window; the central document download re-authorises by type and ownership. |
| **Tests** | `tests/test_notifications.py`, `tests/test_support.py`, `tests/test_portal.py`: idempotent emission, category muting, read-state/ownership, safe redirects, real email confirmation, inert SMS/WhatsApp, preferences; ticket creation/state machine/reopen window/internal-note visibility/reply notification/ownership isolation/attachment isolation/capability gating; documents ownership + central download authorisation, activity isolation, portal metrics, and capability-gated staff customer overview. |
| **Acceptance criteria** | A customer can manage their whole relationship with AA Shinaka from one place with zero cross-user exposure in the automated tests; notification problems never break a business flow; no duplicate domain emails; no paid/state change is ever driven by the browser; SMS/WhatsApp stay inert until configured; capability checks are server-side. |
| **Definition of done** | ✅ Complete (see `docs/PHASE_10_COMPLETION_REPORT.md`). Global DoD met. |

---

## Phase 11 — Analytics & reporting  ✅

> **Scope.** Delivered in a dedicated `apps.analytics` app. The audit-log and
> staff/role-management foundation already shipped in Phase 2; this phase adds the
> analytics dashboards, the reporting/BI layer, exports, scheduled reports and
> data-quality checks. The roadmap's earlier `dashboard.ReportExport`/`SavedReport`
> sketch is superseded by the `apps.analytics` models.

| | |
|---|---|
| **Objective** | Give staff a trustworthy, capability-gated analytics and reporting layer built strictly from the authoritative domain records — per-currency money, no fabricated metrics, aggregate-by-default and no arbitrary SQL. |
| **Dependencies** | Phases 4–10; ASSUMPTION-11 (retention/deletion). |
| **Apps** | `analytics` (new), `accounts` (capabilities/nav), `config` (settings/urls), all domain apps (read-only sources). |
| **Features** | Executive overview + eight operational analytics pages (sales, finance, inventory, services, export, training, customers, support) with real KPIs, Chart.js charts (JSON embedded via `json_script`) and detail tables; a KPI registry documenting every figure; a controlled report builder over **21 allow-listed** report definitions with typed columns and validated filters; dependency-free CSV/XLSX/PDF exports with a formula-injection guard; report **history**; **scheduled reports** with per-period duplicate protection and per-recipient capability re-checks; a **delivery ledger**; ten read-only **data-quality checks**; retention cleanup. |
| **Models** | `analytics.ReportExport`, `ScheduledReport`, `ReportExecution`, `ReportDelivery`. |
| **Pages** | `/dashboard/executive/`, `/dashboard/analytics/<page>/`, `/dashboard/analytics/api/<page>/`, `/dashboard/reports/builder/`, `/dashboard/reports/generate/`, `/dashboard/reports/history/`, `/dashboard/reports/<uuid>/download/`, `/dashboard/reports/scheduled/…`, `/dashboard/reports/data-quality/`. |
| **Permissions** | New capabilities `ANALYTICS_VIEW`, `ANALYTICS_FINANCE`, `REPORTS_BUILD`, `REPORTS_SCHEDULE`, `REPORTS_MANAGE`. Financial figures/columns/reports require `analytics.finance`; Finance Officer holds all five; Sales/Inventory/Training/Export officers build reports; Consultant views only; Administrator/Owner hold everything. Enforcement is server-side, never template-only. |
| **Validation** | Reports are allow-listed (no SQL/model path/field list); filter date ranges validated; money is per-currency and never summed across currencies without configured rates; a generated file is served only through a permission-checked view (ownership or `reports.manage`, plus `analytics.finance` for financial reports) and never a public URL; text cells are guarded against spreadsheet formula injection; a schedule runs at most once per period (`uniq_schedule_period_execution`, plus an integrity-error catch for races); an unauthorised recipient is recorded `skipped` rather than emailed; financial report access is audited. |
| **Tests** | `tests/test_analytics.py` (45 tests): access control and finance gating; selector/multi-currency correctness; the report registry and builder; generate/download/ownership; financial-report auditing; export magic bytes + the injection guard; retention cleanup; data-quality checks; scheduling, duplicate-period protection and delivery-permission skipping. |
| **Acceptance criteria** | Dashboards and reports compute from real records only (empty states stay empty); money is never combined across currencies; net receipts are labelled cash, never profit; every sensitive financial report access is audited; capability checks are server-side; exports are safe and private. |
| **Definition of done** | ✅ Complete (see `docs/PHASE_11_COMPLETION_REPORT.md`). Global DoD met. |

---

## Phase 12 — Hardening, performance & deployment  ✅

> **Delivered** as the Phase 12 production-readiness work: security audit and
> fixes, hardened `config.settings.prod`, a dedicated test settings module,
> security + end-to-end test suites, deployment assets under `deploy/`, CI, and
> the runbook/DR/monitoring/release documentation. See
> `docs/PHASE_12_COMPLETION_REPORT.md`, `docs/PRODUCTION_READINESS_AUDIT.md` and
> `docs/FINAL_PRODUCTION_READINESS_REPORT.md`. Nothing was deployed by this
> phase. Two items remain for general availability: MFA for privileged staff and
> a third-party penetration test.

| | |
|---|---|
| **Objective** | Production readiness: security, performance, observability and automated deployment. |
| **Dependencies** | Phases 1–11. |
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

## Previously drafted — Customer portal & notifications (delivered as Phase 10)  ✅

> **Superseded.** The customer-portal & notification consolidation drafted here
> was brought forward and delivered as **Phase 10** (together with the new support
> centre). The `accounts.Notification` model sketched below was replaced by
> `notifications.Notification`; the portal, activity timeline, document centre and
> capability-gated staff customer overview now ship through `apps.accounts`,
> `apps.notifications` and `apps.support`. See
> `docs/PHASE_10_COMPLETION_REPORT.md`.

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
                     └─> P8 Export
                          └─> P9 Training academy
                               └─> P10 Portal + Notifications + Support
                                    └─> P11 Analytics + Reporting
                                         └─> P12 Hardening + Deployment
```

## Requirement traceability

| SRS area | Phase |
|---|---|
| FR-AUTH, FR-SEC (base) | 1 (partial), 2, 10, 12 |
| FR-CMS (website, content) | 3 |
| FR-CAT, FR-LOC, FR-PRICE | 4 |
| FR-ORD | 5 |
| FR-PAY | 6 |
| FR-CON, FR-SRV (farming/marketing/storage) | 7 |
| FR-EXP | 8 |
| FR-TRN | 9 |
| FR-PORTAL, FR-NOTIF, FR-SUPPORT | 10 |
| FR-DASH, FR-REP | 11 |
| NFR hardening | 12 |

# Software Requirements Specification (SRS)
## AA Shinaka Digital Business Platform

| | |
|---|---|
| Document ID | AASDP-SRS-001 |
| Version | 0.4 (Phase 1–4) |
| Status | For owner review and approval |
| Owner | AA Shinaka General Enterprise |
| Audience | Business owner, product owner, engineering, QA |

> **How to read this document.** Requirements marked **[CONFIRMED]** come directly
> from the Phase 1 brief. Requirements marked **[ASSUMPTION]** are reasonable
> defaults proposed by engineering that **must be approved or changed by the
> owner** before the dependent phase starts. Every requirement has a stable ID
> so later documents, tests and tickets can reference it. No real prices,
> inventory quantities, capacities or company achievements are invented anywhere
> in this document.
>
> **Revision 0.3.** Phase 3 (delivered) is the **Corporate Website, Premium
> Homepage & Content Management** work, specified as §5.15 (`FR-CMS`). The
> catalogue is now **Phase 4** and every later phase shifts by one — the
> "Needed by" column in §21.2 and `docs/IMPLEMENTATION_ROADMAP.md` use the new
> numbering.
>
> **Revision 0.4.** **Phase 4 (delivered) — Catalogue, categories & Nigeria
> locations** implements §5.2 (`FR-CAT`), §5.3 (`FR-LOC`) and §5.4 (`FR-PRICE`)
> including optional requirements FR-CAT-7/-8/-9, FR-LOC-7, FR-PRICE-7/-8/-9.
> The catalogue is data-driven: categories, units, packaging, prices, stock and
> market reference prices are rows (never hardcoded), and selling prices are kept
> strictly separate from informational market reference prices. See
> `docs/PHASE_4_COMPLETION_REPORT.md`.

---

## 1. Purpose and business goals

AA Shinaka General Enterprise is a Nigerian agricultural business operating
across seven divisions. The platform is a **standalone** digital business
platform whose goals are:

- **BG-1 [CONFIRMED]** Sell AA Shinaka's own agricultural products directly to
  customers (B2C and B2B). This is **not** a multi-vendor marketplace.
- **BG-2 [CONFIRMED]** Market services (consultancy, farming, marketing,
  storage, export facilitation, training) and capture qualified requests.
- **BG-3 [CONFIRMED]** Publish agricultural produce with **origin-specific
  listings** (state and LGA) so buyers can source by provenance.
- **BG-4 [CONFIRMED]** Support **international export enquiries** and manage
  export pipelines.
- **BG-5 [CONFIRMED]** Run a **training academy** with course catalogues and
  enrollment.
- **BG-6 [CONFIRMED]** Give staff a single dashboard for operations, fulfilment,
  inventory and reporting.
- **BG-7 [CONFIRMED]** Be fully independent: **do not connect to AgriTrade ERP**.
- **BG-8 [CONFIRMED]** Operate in Nigeria, with NGN pricing and international
  export destinations.

### 1.1 Out of scope (hard exclusions)

- **OOS-1 [CONFIRMED]** Oil and Gas — no processes, products or content.
- **OOS-2 [CONFIRMED]** Multi-vendor marketplace features (vendors, vendor
  onboarding, commissions, per-vendor payouts, vendor storefronts).
- **OOS-3 [CONFIRMED]** Integration with AgriTrade ERP.
- **OOS-4 [CONFIRMED]** Single-page-application frontend (React/Vue/Next.js) or
  any separate frontend application.
- **OOS-5 [ASSUMPTION]** Physical logistics fleet management, cold-chain
  telemetry and IoT sensor integrations are deferred beyond the phases in this
  SRS.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| Division | One of the seven stated business lines |
| Category / Subcategory | Nested classification of products (DB-driven, unlimited depth) |
| Product | A sellable agricultural good (e.g. "sesame seed") independent of origin |
| Listing | A product offered from a specific origin (state/LGA) with its own package size, price and stock |
| Origin | The state + LGA where a listing's produce is sourced |
| Service request | Consultancy, farming, storage, export or training enquiry submitted by a user |
| Staff | Any user with a staff role and dashboard access |
| Customer | Any non-staff registered user |
| Portal | Authenticated customer area |
| Dashboard | Authenticated staff/admin area |

---

## 3. Stakeholders and user roles

### 3.1 Primary stakeholders
- **SH-1** Business owner / management (approves requirements and policies).
- **SH-2** Operations staff across the seven divisions.
- **SH-3** Customers (individual buyers, farmers, businesses, exporters).
- **SH-4** Engineering & QA.

### 3.2 User roles

Roles are stored on the custom user model (`User.role`) as one of **ten
canonical roles** and are mirrored onto Django groups (`role:<code>`) that carry
the model permissions. Only `customer` is self-assignable; staff roles are
granted by an authorised administrator, and roles also set `is_staff=True`.

| Role code | Label | Primary capabilities |
|---|---|---|
| `customer` | Customer | Browse, buy, track orders, raise requests, manage own profile/addresses |
| `sales_officer` | Sales Officer | Product sales, customers and order/fulfilment support |
| `inventory_officer` | Inventory Officer | Stock, listings, storage intake/release and fulfilment |
| `consultant` | Consultant | Manage assigned consultancy requests |
| `training_manager` | Training Manager | Courses, cohorts, enrollments |
| `export_officer` | Export Officer | Export enquiries, quotations, documentation |
| `finance_officer` | Finance Officer | Payments, refunds, reconciliation, reports |
| `content_editor` | Content Editor | Catalogue/content, categories, listings, campaigns |
| `administrator` | Administrator | Staff management and cross-division oversight (not owner/admin peers) |
| `owner` | Owner / Super Admin | Full platform administration, including administrators |

> **Phase 2 reconciliation.** The earlier customer sub-roles (`farmer`,
> `consultancy_client`, `trainee`, `export_buyer`) and staff roles
> (`field_agent`, `warehouse_staff`, `marketing_officer`, `trainer`, `manager`,
> `admin`) were consolidated into the ten roles above. A data migration maps the
> old values (e.g. `marketing_officer` → `sales_officer`, `warehouse_staff` →
> `inventory_officer`, `trainer` → `training_manager`, `manager`/`admin` →
> `administrator`) and forces superusers to `owner`.

> **[ASSUMPTION-01]** Exact capability boundaries per staff role (who may
> approve refunds, discounts, export quotations and price changes) require owner
> approval. Until then, §21.3 is a proposal; the executable matrix lives in
> `apps/accounts/roles.py`.

---

## 4. Business divisions

| ID | Division | Customer-facing outcomes |
|---|---|---|
| DIV-1 | Agricultural Consultancy | Advisory bookings, reports, follow-up |
| DIV-2 | Farming Services | Field/mechanisation/agronomy service requests and scheduling |
| DIV-3 | Agricultural Marketing | Market linkage requests, buyer matching, produce promotion |
| DIV-4 | Storage and Warehousing | Storage enquiries, capacity requests, intake/release records |
| DIV-5 | Agricultural Export | Export enquiries, destination-specific quotations, compliance docs |
| DIV-6 | Agricultural Product Sales | Direct product catalogue, origin listings, cart, checkout |
| DIV-7 | Training and Academy | Course catalogue, cohorts, enrollment, certificates |

**Explicitly excluded:** Oil and Gas.

---

## 5. Functional requirements

IDs follow `FR-<DOMAIN>-<n>`. Priority uses MoSCoW (M/S/C/W).

### 5.1 Accounts, authentication and profiles (`AUTH`)

| ID | Priority | Requirement |
|---|---|---|
| FR-AUTH-1 | M | Users register with email + password; email is the login identifier |
| FR-AUTH-2 | M | Public registration only creates the `customer` role |
| FR-AUTH-3 | M | Email verification before checkout/checkout-relevant actions **[ASSUMPTION]** |
| FR-AUTH-4 | M | Password reset via email |
| FR-AUTH-5 | M | Users edit profile: name, phone, state/LGA, marketing consent |
| FR-AUTH-6 | M | Users manage multiple delivery addresses |
| FR-AUTH-7 | S | Staff accounts are created only by admins; staff cannot self-register |
| FR-AUTH-8 | S | Session security: secure cookies in production, idle timeout **[ASSUMPTION]** |
| FR-AUTH-9 | C | Optional 2FA for staff roles **[ASSUMPTION]** |

### 5.2 Categories and products (`CAT`) — Phase 4, delivered

| ID | Priority | Requirement |
|---|---|---|
| FR-CAT-1 | M | Categories support **unlimited nested subcategories** |
| FR-CAT-2 | M | Categories are data-driven; **no hardcoded category list** in code |
| FR-CAT-3 | M | Products hold shared attributes (name, slug, description, unit, media, status) |
| FR-CAT-4 | M | A product may have multiple origin-specific listings |
| FR-CAT-5 | M | Products can be published, unpublished or archived |
| FR-CAT-6 | M | Category details expose their direct children and ancestor path |
| FR-CAT-7 | S | Products support tags, variety/grade and harvest season metadata |
| FR-CAT-8 | S | Search and filter by category, origin (state/LGA), price band, availability |
| FR-CAT-9 | S | SEO-friendly slugs and canonical URLs per category/product |

### 5.3 Origin-specific listings and locations (`LOC`) — Phase 4, delivered

| ID | Priority | Requirement |
|---|---|---|
| FR-LOC-1 | M | The platform stores Nigeria's **36 states + FCT** and their **774 LGAs / area councils** |
| FR-LOC-2 | M | Location reference data is imported and verified, not hand-typed |
| FR-LOC-3 | M | A listing records origin state, origin LGA, package size + unit |
| FR-LOC-4 | M | Each listing has its **own independent selling price and stock** |
| FR-LOC-5 | M | Buyers can browse products by state and narrow to LGA |
| FR-LOC-6 | M | Location pages show only active, in-stock listings by default |
| FR-LOC-7 | S | Listings expose provenance/quality notes **[ASSUMPTION]** |
| FR-LOC-8 | C | Map/geo coordinates for origin **[ASSUMPTION / deferred]** |

### 5.4 Pricing and inventory (`PRICE`) — Phase 4, delivered

| ID | Priority | Requirement |
|---|---|---|
| FR-PRICE-1 | M | All monetary values are stored as decimal currency (NGN base) |
| FR-PRICE-2 | M | Listing price is independent per origin/package; **no state-specific price is hardcoded** |
| FR-PRICE-3 | M | Stock is tracked per listing, with reserved vs available quantities |
| FR-PRICE-4 | M | Stock changes are recorded as movements (auditable ledger) |
| FR-PRICE-5 | M | Checkout cannot sell more than available stock |
| FR-PRICE-6 | M | Staff may set price and stock via the dashboard; changes are audited |
| FR-PRICE-7 | S | Optional compare-at price and scheduled price windows **[ASSUMPTION]** |
| FR-PRICE-8 | S | Low-stock threshold and alerts **[ASSUMPTION]** |
| FR-PRICE-9 | S | Bulk/tiered pricing for B2B and export **[ASSUMPTION]** |

### 5.5 Ordering and checkout (`ORD`)

| ID | Priority | Requirement |
|---|---|---|
| FR-ORD-1 | M | Customers add listings to a persistent cart |
| FR-ORD-2 | M | Cart recalculates when price/stock changes and warns on conflicts |
| FR-ORD-3 | M | Checkout captures delivery address, contact and any notes |
| FR-ORD-4 | M | Order creation is transactional and decrements/reserves stock atomically |
| FR-ORD-5 | M | Orders have a lifecycle: pending payment → paid → processing → dispatched → delivered → completed / cancelled |
| FR-ORD-6 | M | Customers can view order history and status |
| FR-ORD-7 | M | Order status changes are recorded with actor and timestamp |
| FR-ORD-8 | S | Guest checkout **[ASSUMPTION: likely not permitted]** |
| FR-ORD-9 | S | Delivery fee rules by state/zone **[ASSUMPTION]** |
| FR-ORD-10 | S | Order cancellation window rules **[ASSUMPTION]** |

> **Implementation status (Phase 5 — delivered).** FR-ORD-1/2/3/4/5/6/7 and
> FR-ORD-9 are implemented: a persistent cart (guest carts merge at login) whose
> totals are recomputed server-side; transactional checkout that snapshots line
> prices and reserves per-warehouse stock; an enforced order state machine with
> an append-only `OrderStatusHistory`; a customer order portal; and shipping
> zones/methods/rates. FR-ORD-4 reserves rather than decrements at creation;
> stock is decremented when payment is confirmed. FR-ORD-8 is resolved as **guest
> checkout not permitted** (checkout is authenticated-only). No payment provider
> ships in Phase 5 — orders stay `pending_payment` until an audited staff
> manual-payment approval (see FR-PAY-1 and `docs/PHASE_5_COMPLETION_REPORT.md`).

### 5.6 Payments and refunds (`PAY`)

| ID | Priority | Requirement |
|---|---|---|
| FR-PAY-1 | M | Payment uses **Paystack** (Phase 6). Provider calls are server-side only; keys come from `PAYSTACK_*` env vars and are never rendered, logged or returned |
| FR-PAY-2 | M | The data model supports a payment lifecycle independent of the provider (`Payment`, `PaymentAttempt`) |
| FR-PAY-3 | M | Payments record reference, provider, currency, expected/verified amount, status and provider reference |
| FR-PAY-4 | M | Payments are marked paid **only** after server-side verification; the browser redirect alone is never trusted |
| FR-PAY-5 | M | Webhooks are HMAC-SHA512 signature-verified over the raw body, deduplicated and idempotent |
| FR-PAY-6 | M | Refunds reference a payment, carry a reason and approver, cannot exceed captured funds, and are finance-only |
| FR-PAY-7 | S | Partial refunds and multiple payments per order are supported |
| FR-PAY-8 | M | Customers may submit a bank-transfer claim, but only finance approval (with settlement confirmed) settles the order |
| FR-PAY-9 | M | One bank transfer cannot settle more than one order |
| FR-PAY-10 | M | Invoices and receipts are issued immutably (versioned rather than edited); receipts exist only for verified payments |
| FR-PAY-11 | M | Customers can view only their own payments, invoices and receipts |
| FR-PAY-12 | S | Finance metrics derive only from verified payments (gross/refunds/net/pending/unpaid); open payments are reconciled against the provider |
| FR-PAY-13 | M | A late payment on an expired/cancelled order is recorded and flagged for review, never auto-completed |

### 5.7 Consultancy and service bookings (`CON`) — Phase 7, delivered

| ID | Priority | Requirement |
|---|---|---|
| FR-CON-1 | M | Customers submit consultancy bookings (service, online/on-site mode where supported, preferred slot, notes) |
| FR-CON-2 | M | Staff triage, assign a consultant, and confirm/reschedule/reject/complete; completion records a report |
| FR-CON-3 | M | Requests carry a shared status lifecycle, history and activity log |
| FR-CON-4 | M | Consultant availability is data-driven; conflicting confirmed appointments for the same consultant are rejected under a row lock |
| FR-CON-5 | M | Customers see only their own appointments/reports; division queues are capability-gated |

### 5.8 Farming, marketing and storage services (`SRV`) — Phase 7, delivered

| ID | Priority | Requirement |
|---|---|---|
| FR-SRV-1 | M | Customers submit **farming service requests** (requested service, farm location, area/size, crop, season, expected start, budget range) |
| FR-SRV-2 | M | Customers submit **marketing enquiries** (product, available quantity, target market); staff issue a narrative proposal the customer accepts or rejects |
| FR-SRV-3 | M | Customers submit **storage requests** (produce type, quantity/unit, facility preference, dates, special handling) |
| FR-SRV-4 | M | Warehouse staff manage facilities/units, capacity allocations, bookings, check-in/out and inspections |
| FR-SRV-5 | M | All service requests share a common `ServiceRequest` engine: reference, status pipeline + append-only history, activity log, assignment, comments and visibility-controlled attachments |
| FR-SRV-6 | M | A single quotation engine prices any request (line items, server-recomputed totals, revision/`supersedes`, approval → issue → accept/reject/expire); accepted quotations are frozen |
| FR-SRV-7 | M | A paid service is activated only by a **verified** payment (Phase 6), never by the browser callback |
| FR-SRV-8 | M | Storage capacity cannot be over-allocated; end dates must follow start dates; quantities must be positive |
| FR-SRV-9 | M | Each division maps to a `REQUESTS_*` capability; the shared dashboard to `SERVICES_MANAGE` / `QUOTATIONS_MANAGE`; customers see only their own records |

### 5.9 Export management & international trade (`EXP`) — Phase 8, delivered

| ID | Priority | Requirement |
|---|---|---|
| FR-EXP-1 | M | Export buyers submit enquiries: product(s), volume, destination country, preferred shipping mode, timeline |
| FR-EXP-2 | M | Destination is an **international market** (`locations.Country`), not a company branch; only approved **and** active destinations are selectable |
| FR-EXP-3 | M | Export officers issue quotations and track status; a quotation names an explicit **Incoterms 2020** rule **and a named place**, a currency and a validity |
| FR-EXP-4 | S | Export documents/compliance checklist per destination; official document types enforce an expiry date |
| FR-EXP-5 | S | Incoterm and currency support beyond NGN; an accepted quotation is **frozen** and totals are always recomputed server-side |
| FR-EXP-6 | M | An accepted quotation produces an export order whose terms are copied from the quotation, never from the browser |
| FR-EXP-7 | M | Shipments use freight-forwarding providers and **staff-entered milestones** only; live tracking is never fabricated |
| FR-EXP-8 | M | An export payment is `paid` only after server-side verification and counts as revenue only once verified |

> **Delivery note.** Phase 8 lives in the dedicated `apps.export` app and extends
> `catalog.Product` through `ExportProductProfile` — the catalogue is **not**
> duplicated.

### 5.10 Training and academy (`TRN`)

> **Phase 9 delivered.** The training academy is implemented in the dedicated
> `apps.training` app. Courses are configurable records (never a hardcoded list),
> cohorts are capacity-limited `TrainingSession`s, enrolment supports waitlisting
> and free/paid seats, attendance and assessments feed derived completion, and
> certificates are staff-approved (`TRAINING_APPROVE`) with public code
> verification. A paid seat confirms **only** after a server-verified payment
> (Phase 6 pipeline); the browser callback is never trusted.

| ID | Priority | Requirement |
|---|---|---|
| FR-TRN-1 | M | Publish training courses (title, description, level, duration, fee optional) |
| FR-TRN-2 | M | Courses may have cohorts/schedules with capacity |
| FR-TRN-3 | M | Users enroll; enrollment status tracked (pending/payment_pending/confirmed/waitlisted/cancelled/completed) |
| FR-TRN-4 | S | Attendance records and **approved** certificates (with public code verification) |
| FR-TRN-5 | S | Course payments integrate with the Phase 6 verified-payment lifecycle |

### 5.11 Customer portal (`PORTAL`) — Phase 10, delivered

> **Phase 10 delivered.** The unified portal is consolidated under `/account/`
> with a metrics dashboard, an aggregated cross-domain **activity timeline**, a
> **document centre** (one central, per-type ownership-checked download route)
> and links to each division's portal. `FR-PORTAL-1`–`4` are complete;
> `FR-PORTAL-5` (wishlist) remains a later-phase saving feature; `FR-PORTAL-6`
> (in-app notifications) is delivered by the Phase 10 notification centre below.

| ID | Priority | Requirement |
|---|---|---|
| FR-PORTAL-1 | M | Dashboard-style landing for the customer |
| FR-PORTAL-2 | M | Order history, order detail and status tracking |
| FR-PORTAL-3 | M | All submitted requests in one place with statuses |
| FR-PORTAL-4 | M | Profile, addresses and password management |
| FR-PORTAL-5 | S | Saved items / wishlist **[ASSUMPTION]** |
| FR-PORTAL-6 | S | In-app notifications **[ASSUMPTION]** |

### 5.12 Staff dashboard (`DASH`)

| ID | Priority | Requirement |
|---|---|---|
| FR-DASH-1 | M | Role-aware dashboard home with KPIs |
| FR-DASH-2 | M | CRUD for categories, products, listings, price and stock |
| FR-DASH-3 | M | Order management and fulfilment queue |
| FR-DASH-4 | M | Service request queues per division |
| FR-DASH-5 | M | User management (staff creation, roles, activation) |
| FR-DASH-6 | M | Export enquiry pipeline |
| FR-DASH-7 | M | Training course/enrollment management |
| FR-DASH-8 | S | Content management for homepage sections **[ASSUMPTION]** |

### 5.13 Reporting and analytics (`REP`)

| ID | Priority | Requirement |
|---|---|---|
| FR-REP-1 | M | Sales summary by period, division, category, origin **(delivered Phase 11)** |
| FR-REP-2 | M | Stock position and low-stock report **(delivered Phase 11)** |
| FR-REP-3 | M | Service request volumes and turnaround **(delivered Phase 11)** |
| FR-REP-4 | M | Export enquiry pipeline report **(delivered Phase 11)** |
| FR-REP-5 | S | CSV export of reports **[ASSUMPTION]** — **delivered Phase 11** as dependency-free CSV, XLSX and PDF with a spreadsheet formula-injection guard |
| FR-REP-6 | S | Chart.js visual dashboards **[ASSUMPTION on chart set]** — **delivered Phase 11** (executive + eight operational pages) |
| FR-REP-7 | M | **Report history**: every generated report with its filters, owner and status, scoped to the owner unless `reports.manage` |
| FR-REP-8 | M | **Scheduled reports** with per-period duplicate protection and a per-recipient delivery ledger |
| FR-REP-9 | M | **Financial gating**: financial figures, columns and reports require `analytics.finance`; financial report access is audited |
| FR-REP-10 | M | **Per-currency money**: no figure is summed across currencies without a configured exchange-rate source |
| FR-REP-11 | S | **Data-quality checks** surfacing records that would skew analytics |
| FR-REP-12 | M | **No fabricated metrics**: dashboards and reports compute from authoritative records only; empty states stay empty |

> **Phase 11 delivery note.** Reporting lives in `apps.analytics` (see
> `docs/PHASE_11_COMPLETION_REPORT.md`). Reports are a **code-defined allow-list**
> (no arbitrary SQL/model path/field list); customer identity is absent from every
> dashboard and report (aggregate by default); stored files are private and served
> only through a permission-checked view; **net receipts are labelled cash, not
> accounting profit** and no profit figure is computed because no authoritative
> cost/expense ledger exists. The KPI registry (`apps/analytics/metrics.py`)
> documents every figure; `docs/ANALYTICS_METRICS.md` mirrors it.

### 5.14 Security, audit and notifications (`SEC` / `NOTIF`)

| ID | Priority | Requirement |
|---|---|---|
| FR-SEC-1 | M | Passwords hashed with Django's hashers; strong password validation |
| FR-SEC-2 | M | CSRF protection on all state-changing requests |
| FR-SEC-3 | M | ORM-only database access (no raw SQL with user input) |
| FR-SEC-4 | M | Role-based access control on every staff action |
| FR-SEC-5 | M | **Audit log** for sensitive actions (price/stock changes, refunds, role changes, exports) |
| FR-SEC-6 | M | Sensitive operations wrapped in database transactions |
| FR-SEC-7 | S | Rate limiting on auth and request forms **[ASSUMPTION]** |
| FR-NOTIF-1 | M | Transactional email for registration, order and request events |
| FR-NOTIF-2 | S | In-app notifications **[ASSUMPTION]** |
| FR-NOTIF-3 | S | SMS/WhatsApp notifications **[ASSUMPTION / cost decision]** |

> **Phase 10 delivered (`NOTIF`).** `FR-NOTIF-1` continues through the existing
> per-domain email senders (unchanged). `FR-NOTIF-2` is delivered by the unified
> `apps.notifications` centre: an idempotent in-app feed with per-customer
> preferences and a delivery ledger; notification rows are written synchronously
> inside the business transaction and only channel delivery is deferred
> (`transaction.on_commit`). Events a domain already emails merely mirror into the
> feed — no duplicate email is sent. `FR-NOTIF-3` ships as **optional adapters**
> (`SMS`/`WhatsApp`) that stay **inert** until an approved provider is configured
> *and* the customer opts in; unconfigured channels are recorded as skipped and no
> credentials are hardcoded.

### 5.14a Customer support centre (`SUPPORT`) — Phase 10, delivered

| ID | Priority | Requirement |
|---|---|---|
| FR-SUPPORT-1 | M | A customer can open a support ticket from their own account |
| FR-SUPPORT-2 | M | A ticket can link one of the customer's own orders/payments/enquiries/requests/enrolments (ownership resolved server-side) |
| FR-SUPPORT-3 | M | Ticket conversation with attachments; internal staff notes are never shown to the customer |
| FR-SUPPORT-4 | M | Staff status workflow with an explicit state machine and a bounded reopen window |
| FR-SUPPORT-5 | M | A capability-gated staff queue (assignment, status, priority) |
| FR-SUPPORT-6 | S | New public-reply events notify the customer in-app (and may email) |

### 5.15 Corporate website, homepage & content management (`CMS`) — Phase 3, delivered

| ID | Priority | Requirement |
|---|---|---|
| FR-CMS-1 | M | A reusable Tailwind design system (Forest/Leaf/Harvest Gold/Cream tokens) drives every public page |
| FR-CMS-2 | M | A premium **15-section homepage** communicates all six active divisions (consultancy, farming, marketing, storage, export, product sales) plus training — never oil & gas |
| FR-CMS-3 | M | Dedicated public service pages for Consultancy, Farming, Marketing, Storage and Export, rendered from CMS data |
| FR-CMS-4 | M | About, Contact, Blog (posts + categories), FAQ and CMS-managed pages, all CMS-editable |
| FR-CMS-5 | M | Contact form is validated, honeypot/rate-limit protected and **stored** as an enquiry (never emailed in Phase 3); WhatsApp, business location and social links come from site settings |
| FR-CMS-6 | M | Content models (`Page`, `HeroBanner`, `BusinessDivision`, `ServicePage`, `BlogPost`, `BlogCategory`, `FAQ`, `Testimonial`, `TeamMember`, `SiteSetting`, `MediaAsset`, `NavigationItem`, `ContactEnquiry`) support draft/published/archived, publish dates, SEO fields, slugs, ordering and image validation |
| FR-CMS-7 | M | Staff CMS dashboard lives inside the existing staff dashboard at `/dashboard/cms/` (Django templates + HTMX) behind server-side capability checks |
| FR-CMS-8 | M | Testimonials require staff approval before display; publish/unpublish actions are validated and audited |
| FR-CMS-9 | M | SEO & performance: semantic HTML, meta/canonical/OG tags, `sitemap.xml`, `robots.txt`, image alt text, lazy loading, pagination and query optimisation |
| FR-CMS-10 | S | English + Hausa **language readiness**: message catalogue and `{% translate %}` used in templates — full bilingual content is **not** claimed |
| FR-CMS-11 | M | Location/product preview sections degrade gracefully (empty states, no duplicated models) until the catalogue ships in Phase 4 |

---

## 6. Nonfunctional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Performance | Public pages target < 2 s TTFB/rendered on typical Nigerian mobile networks at realistic data volumes |
| NFR-2 | Performance | Catalogue queries must be indexed and paginated; no unbounded list pages |
| NFR-3 | Scalability | Stateless web tier; background work offloaded to Celery workers |
| NFR-4 | Availability | Health endpoint (`/healthz/`) for uptime checks; graceful DB failure reporting |
| NFR-5 | Security | Follow OWASP Top 10; secrets only via environment variables |
| NFR-6 | Privacy | Collect only necessary personal data; provide account deletion/archival path |
| NFR-7 | Accessibility | WCAG 2.1 AA targets: keyboard navigation, contrast, labels, focus states |
| NFR-8 | Usability | Mobile-first responsive design; forms with clear inline validation |
| NFR-9 | Maintainability | Ruff-clean, tested, service-layer separation, documented decisions |
| NFR-10 | Observability | Structured logging, audit trail, Celery task logging, error tracking in later phase |
| NFR-11 | Localisation | English (en-us), `Africa/Lagos` timezone, NGN currency formatting |
| NFR-12 | Compatibility | Current Chrome, Firefox, Safari, Edge; progressive enhancement (works without JS for critical flows) |
| NFR-13 | Data integrity | Foreign keys with deliberate `PROTECT`/`SET_NULL`; DB constraints for uniqueness |
| NFR-14 | Recoverability | Soft deletion/archival for business records; documented backup strategy |

---

## 7. Product categories and subcategories

- Categories are **database-driven** and support nesting to unlimited depth
  (`parent` self-FK). Breadcrumbs and "category path" are derived from ancestors.
- A product belongs to a leaf or intermediate category; listings hang off
  products.
- **No category names or state prices are hardcoded in code.**

> **[ASSUMPTION-02]** The following *candidate* top-level categories are
> proposed for owner approval. They are **not** seeded as facts and carry no
> prices or stock. Final list, names, and nesting require owner sign-off.
>
> - Grains & Cereals (maize, rice, sorghum, millet, wheat…)
> - Legumes & Pulses (cowpea, groundnut, soybean, sesame…)
> - Roots & Tubers (cassava, yam, potato, sweet potato…)
> - Oilseeds & Oils (palm oil, groundnut oil, shea…)
> - Spices & Condiments (ginger, garlic, pepper, turmeric…)
> - Fruits & Vegetables
> - Livestock, Poultry & Aquaculture
> - Agro-Inputs & Farm Supplies
> - Processed & Packaged Agro-Products
> - Export-Grade Commodities

---

## 8. State/LGA-based product listings

- Every listing records: product, origin **state**, origin **LGA**, package size
  and unit, selling price, available stock, status.
- Browsing paths: `Products → Category → Listing by State → LGA`.
- The homepage exposes a **Shop by State** navigation.
- State/LGA dropdowns are populated from imported reference data (§5.3).
- **[ASSUMPTION-03]** A product may be listed from multiple origins with
  different prices; the price shown is always listing-specific.

---

## 9. Pricing and inventory rules

- Currency: NGN base, stored as `Decimal`; amounts are never floats.
- Prices are per listing and per package size; no global per-product price.
- Availability = on-hand stock − reserved stock. Checkout reserves stock inside
  a transaction and converts reservations to deductions on payment confirmation.
- Stock movements (intake, adjustment, sale, return, damage, transfer) form an
  auditable ledger; the listing keeps a denormalised on-hand figure reconciled
  against the ledger.
- **[ASSUMPTION-04]** VAT/tax handling and delivery-fee rules require owner and
  finance decisions; the schema reserves fields but applies no rate by default.

---

## 10. Product ordering and checkout

1. Add listing(s) to cart (quantity limited by availability).
2. Review cart; price/stock re-validated.
3. Provide/confirm delivery address and contact.
4. Create order (transactional); reserve stock; issue payment intent.
5. Pay (later phase); on success, confirm order and reduce stock.
6. Fulfilment updates drive status and notify the customer.

Out-of-scope for Phase 1: any live payment call.

---

## 11. Payments and refunds

- Provider: **Paystack**, delivered in Phase 6 (`PAYSTACK_ENABLED` defaults off;
  sandbox-first, keys via environment variables only).
- The model separates `Order` from `Payment` so providers can change.
- Checkout: the server creates a `Payment` with the authoritative order total and
  redirects to Paystack's hosted page. The browser is never trusted: the callback
  re-verifies server-side and webhooks are HMAC-SHA512 signed over the raw body,
  deduplicated (`PaymentWebhookEvent`) and idempotent. A payment is `paid` only
  when currency and amount match the stored order total.
- A late payment (order expired/cancelled) is recorded and flagged
  `requires_review`; the order is not completed automatically.
- Refunds reference a payment, carry a reason and approver, cannot exceed
  captured funds, and go through `request → approve → complete` with finance
  permission (`FINANCE_MANAGE`).
- Invoices and receipts are immutable once issued; receipts exist only for
  verified payments. Bank-transfer claims require finance approval with
  settlement confirmed, and one transfer cannot settle two orders.
- **[ASSUMPTION-04]** VAT/tax rules and **[ASSUMPTION-05]** refund windows remain
  owner policy; the platform uses the configured `ORDER_TAX_RATE` and never
  invents tax details.

---

## 12. Consultancy and service bookings

Covered by FR-CON-*. A consultancy booking is a `ConsultationAppointment`
wrapping the shared `ServiceRequest`: requester, service, mode, scheduled
window, assigned consultant, status and history. Consultant availability
(`ConsultantAvailability`) is data-driven and confirmed appointments for the
same consultant may not overlap. Requests are visible to the customer in
`/account/services/` and to the consultancy queue in `/dashboard/services/`
(capability-gated). Completion records a `ConsultationReport`.

---

## 13. Storage, farming and marketing requests

Covered by FR-SRV-*. All three share the `ServiceRequest` engine (reference,
status pipeline, history, activity log, assignment, comments, attachments) and
the quotation/verified-payment flow:

- **Farming** — `FarmServiceRequest` (requested service, location, area/unit,
  crop, season, budget) → `FarmProject`; a project must be approved with an
  agreement reference before activation, and tracks milestones and progress
  reports.
- **Marketing** — `MarketingEnquiry` → narrative `MarketingProposal` (accept/
  reject by the customer) → `MarketingCampaign` (which requires an accepted
  proposal) with a dated activity log.
- **Storage** — data-driven `StorageFacility`/`StorageUnit` capacity with
  `ProduceType` acceptance, `StorageBooking` + `StorageCapacityAllocation`
  (over-allocation rejected under locks), and check-in/out + inspection records.
- A `ServiceQuotation` prices any of the above; a booking/project/request is
  activated only after a **verified** payment settles the quotation.

---

## 14. Export management & international trade

_Phase 8 — delivered in `apps.export`._

A customer raises an **export enquiry** for one or more catalogue products
against an approved-and-active destination country, with a delivery destination,
preferred shipping mode and timeline. An export officer prices it as a
**quotation** naming an explicit Incoterms 2020 rule and named place, a currency,
a deposit percentage and a validity window; approval/issue requires the
`export.approve` capability (Administrators/Owners only) and an accepted
quotation is frozen (later changes become superseded revisions). Acceptance
creates an **export order** whose commercial terms are copied from the quotation.

A **compliance checklist** is generated from the destination's document
requirements; movement to `ready_for_shipment` is blocked until it is cleared.
**Documents** use private storage and a configurable type registry (official
types enforce an expiry date), with staff review and a per-document
customer-visibility flag. **Shipments** reference freight-forwarding providers
and carry staff-entered milestones only. Settlement reuses the Phase 6 verified
payment pipeline through `orders.Payment.export_order`; a payment becomes `paid`
only on server-side verification and only verified payments count as revenue.
Customers see only their own records; destinations are external markets with no
notion of company branches.

---

## 15. Training enrollment

Covered by FR-TRN-*. Course → cohort → enrollment, with capacity limits and
statuses. Certificates/attendance are later-phase assumptions.

---

## 16. Customer portal

Covered by FR-PORTAL-*. A single authenticated area for orders, requests,
profile and addresses, with clear status visibility and mobile-first layout.

---

## 17. Staff dashboard

Covered by FR-DASH-*. Role-aware, permission-gated, with queues and CRUD for
the areas each role owns. All sensitive mutations are audited (FR-SEC-5).

---

## 18. Reporting and analytics

Covered by FR-REP-*; **delivered in Phase 11** (`apps.analytics`, see
`docs/PHASE_11_COMPLETION_REPORT.md`). Reports are read-only and filterable by a
validated date range / preset, and render with Chart.js from server-computed JSON
(`json_script`, never string-interpolated).

- **Allow-listed.** A request can only name a key from the code-defined report
  registry; there is no arbitrary SQL, model path or field list.
- **Aggregate by default.** Customer identity is absent from every dashboard and
  report.
- **Per-currency money.** No figure is summed across currencies without a
  configured exchange-rate source; the platform never invents a rate.
- **Cash is not profit.** Net verified receipts are cash received, explicitly
  labelled; no profit figure exists because there is no authoritative cost/expense
  ledger.
- **Sales-value definitions are never mixed** (placed / paid / recognised).
- **Real data only.** Every figure is derived from the authoritative records;
  empty states stay empty and no placeholder number is shipped as if real.
- **Safe exports.** CSV/XLSX/PDF are produced without new dependencies, with a
  spreadsheet formula-injection guard, private storage and a permission-checked
  download.
- **Audited.** Sensitive financial report access writes an `AuditLog` entry.

---

## 19. Security and audit logging

- Authentication: Django auth with the custom email user model; email
  verification, password reset/change and cache-backed rate limiting on the auth
  endpoints (Phase 2).
- Authorisation: the ten canonical roles + Django groups (`role:<code>`);
  server-side capability checks; object-level checks for accounts, requests,
  orders and records. Templates never gate access.
- Audit: an append-only `AuditLog` entry for every sensitive mutation, capturing
  actor, action, target, timestamp, request metadata and a redacted before/after
  summary where practical. Audit rows cannot be edited or deleted from the
  application and never contain passwords, tokens or secrets.
- Secrets: environment-only; `.env` is gitignored and `.env.example` documents
  required keys.
- Transactions: order creation, stock changes, refunds and role changes are
  atomic.

---

## 20. Acceptance criteria

Acceptance criteria are defined per phase in
`docs/IMPLEMENTATION_ROADMAP.md`. At the platform level, the following must
always hold:

- **AC-1** `uv run python manage.py check` reports no errors.
- **AC-2** Migrations apply cleanly from an empty PostgreSQL database.
- **AC-3** `uv run ruff check .` and `uv run ruff format --check .` pass.
- **AC-4** `uv run pytest` passes with no failures.
- **AC-5** The custom user model is the platform's auth model and is created
  before any dependent migration.
- **AC-6** No oil-and-gas content, multi-vendor feature or AgriTrade ERP link
  exists anywhere in the codebase.
- **AC-7** No hardcoded categories, state prices, inventory or company
  achievements exist in code or templates.

---

## 21. Approved vs assumed requirements

### 21.1 Confirmed by the brief
- Seven divisions; oil and gas excluded (OOS-1).
- Direct selling, not marketplace (OOS-2); standalone from AgriTrade ERP (OOS-3).
- Django MVT + Django Templates; no SPA (OOS-4).
- Stack: Django 5.2 LTS, PostgreSQL, Tailwind, HTMX, Alpine.js, Celery/Redis,
  Chart.js, Paystack, Pytest/pytest-django, Ruff; DRF only if needed.
- Email-first custom user model created before the first migration.
- Origin-specific listings with independent price and stock; nested categories.
- Verified Nigeria location import (36 states + FCT, 774 LGAs/area councils).

### 21.2 Assumptions requiring owner approval

| ID | Assumption | Needed by |
|---|---|---|
| ASSUMPTION-01 | Staff permission matrix / approval authority | Phase 5–10 |
| ASSUMPTION-02 | Final category list and nesting | Phase 4 (delivered — categories DB-driven; taxonomy sign-off pending) |
| ASSUMPTION-03 | Multi-origin listings per product allowed | Phase 4 (delivered — multiple listings per product supported) |
| ASSUMPTION-04 | VAT/tax and delivery-fee rules | Phase 6 (implemented via configured `ORDER_TAX_RATE`; company tax details are never invented) |
| ASSUMPTION-05 | Refund policy, windows and approvers | Phase 6 (delivered — finance `FINANCE_MANAGE` approves; refund windows remain owner policy) |
| ASSUMPTION-06 | Email verification required before checkout | Phase 5 (checkout requires authentication; the verified-email gate is **not enforced** — owner to confirm) |
| ASSUMPTION-07 | Guest checkout not permitted | Phase 5 (delivered — checkout is authenticated-only; guest carts still merge on login) |
| ASSUMPTION-08 | Export currencies beyond NGN, incoterms set | Phase 8 — resolved as data: quotations name an explicit **Incoterms 2020** rule + named place; destinations are `locations.Country` rows activated only after approval |
| ASSUMPTION-09 | Course fees/payment and certificates | Phase 9 (delivered — free/paid cohorts; a paid seat confirms only on a server-verified payment; certificates require `TRAINING_APPROVE` + completion) |
| ASSUMPTION-10 | Notifications channels (email only vs SMS/WhatsApp) | Phase 10 (delivered — email + in-app are live; SMS/WhatsApp ship as inert adapters until an approved provider is configured and the customer opts in) |
| ASSUMPTION-11 | Data-retention and account-deletion policy | Phase 11 (partly resolved — generated report files are retained for `ANALYTICS_REPORT_RETENTION_DAYS` and then cleaned up; a full data-retention/account-deletion policy remains deferred) |
| ASSUMPTION-12 | Authoritative Nigeria location dataset source | Phase 4 (importer ready; owner must supply/approve the dataset) |

### 21.3 Staff permission matrix (implemented, ASSUMPTION-01)

The authoritative matrix is `apps/accounts/roles.py` (`ROLE_CAPABILITIES`);
this table mirrors it. Administrator and Owner hold **all** capabilities; the
Customer role holds none. Treat the capability names as stable identifiers.

| Capability | Sales | Inventory | Consultant | Training Mgr | Export | Finance | Content Ed. | Admin | Owner |
|---|---|---|---|---|---|---|---|---|---|
| `staff.view` | – | – | – | – | – | – | – | ✓ | ✓ |
| `staff.manage` | – | – | – | – | – | – | – | ✓ | ✓ |
| `roles.assign` | – | – | – | – | – | – | – | ✓ | ✓ |
| `audit.view` | – | – | – | – | – | ✓ | – | ✓ | ✓ |
| `catalog.manage` | ✓ | ✓ | – | – | – | – | – | ✓ | ✓ |
| `inventory.manage` | – | ✓ | – | – | – | – | – | ✓ | ✓ |
| `orders.manage` | ✓ | ✓ | – | – | – | ✓ | – | ✓ | ✓ |
| `finance.manage` | – | – | – | – | – | ✓ | – | ✓ | ✓ |
| `content.manage` | – | – | – | ✓ | – | – | ✓ | ✓ | ✓ |
| `requests.consultancy` | – | – | ✓ | – | – | – | – | ✓ | ✓ |
| `requests.farming` | – | ✓ | – | – | – | – | – | ✓ | ✓ |
| `requests.marketing` | ✓ | – | – | – | – | – | – | ✓ | ✓ |
| `requests.storage` | – | ✓ | – | – | – | – | – | ✓ | ✓ |
| `requests.export` | – | – | – | – | ✓ | – | – | ✓ | ✓ |
| `requests.training` | – | – | – | ✓ | – | – | – | ✓ | ✓ |
| `services.manage` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | ✓ | ✓ |
| `quotations.manage` | ✓ | – | – | – | – | ✓ | – | ✓ | ✓ |
| `export.manage` | – | – | – | – | ✓ | – | – | ✓ | ✓ |
| `export.approve` | – | – | – | – | – | – | – | ✓ | ✓ |
| `training.manage` | – | – | – | ✓ | – | – | – | ✓ | ✓ |
| `training.instruct` | – | – | – | ✓ | – | – | – | ✓ | ✓ |
| `training.approve` | – | – | – | – | – | – | – | ✓ | ✓ |
| `support.manage` | ✓ | – | – | – | – | – | – | ✓ | ✓ |
| `support.approve` | – | – | – | – | – | – | – | ✓ | ✓ |
| `customers.view` | ✓ | – | – | – | – | ✓ | – | ✓ | ✓ |
| `analytics.view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | ✓ | ✓ |
| `analytics.finance` | – | – | – | – | – | ✓ | – | ✓ | ✓ |
| `reports.build` | ✓ | ✓ | – | ✓ | ✓ | ✓ | – | ✓ | ✓ |
| `reports.schedule` | – | – | – | – | – | ✓ | – | ✓ | ✓ |
| `reports.manage` | – | – | – | – | – | ✓ | – | ✓ | ✓ |

> **Assignment guard.** Owners/superusers may grant any role. Administrators may
> grant every staff role **except** `administrator`/`owner`. No one may edit
> their own account through staff management, and administrators cannot manage
> owner/superuser accounts.

---

## 22. Open questions for the owner

1. Authoritative source and licence for the Nigeria states/LGA dataset
   (ASSUMPTION-12).
2. Final top-level category taxonomy and expected nesting depth
   (ASSUMPTION-02).
3. Company contact details, legal name, registration numbers and verifiable
   achievements for public pages (none are invented here).
4. Tax/VAT registration and delivery-fee policy (ASSUMPTION-04).
5. Export currency/incoterm policy and countries served — **implemented as data**
   (explicit Incoterms 2020 + named place; countries are `locations.Country`
   records that an approver activates). The owner still decides *which* countries
   and currencies to enable operationally.
6. Refund, cancellation and returns policy (ASSUMPTION-05).
7. Notification channels and budget (ASSUMPTION-10).
8. Data-retention and account-deletion expectations (ASSUMPTION-11).

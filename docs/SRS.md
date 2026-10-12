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

### 5.6 Payments and refunds (`PAY`)

| ID | Priority | Requirement |
|---|---|---|
| FR-PAY-1 | M | Payment integration is **deferred to a later phase** (Paystack) |
| FR-PAY-2 | M | The data model must support a payment lifecycle independent of the provider |
| FR-PAY-3 | M | Payments record provider reference, amount, currency, status and raw callback |
| FR-PAY-4 | M | Webhooks are verified (signature) and idempotent |
| FR-PAY-5 | M | Refunds are recorded with reason, approver and amount |
| FR-PAY-6 | S | Partial refunds and multiple payments per order **[ASSUMPTION]** |
| FR-PAY-7 | S | Reconciliation report between orders and settlements **[ASSUMPTION]** |

### 5.7 Consultancy and service bookings (`CON`)

| ID | Priority | Requirement |
|---|---|---|
| FR-CON-1 | M | Customers submit consultancy requests (topic, crop, location, notes) |
| FR-CON-2 | M | Staff triage, assign a consultant and set a status |
| FR-CON-3 | M | Requests carry a status lifecycle and history |
| FR-CON-4 | S | Scheduling/calendar of consultations **[ASSUMPTION]** |
| FR-CON-5 | S | Deliverables/reports attached to the request **[ASSUMPTION]** |

### 5.8 Farming, marketing and storage services (`SRV`)

| ID | Priority | Requirement |
|---|---|---|
| FR-SRV-1 | M | Customers submit **farming service requests** (service type, farm location, acreage, schedule) |
| FR-SRV-2 | M | Customers submit **marketing requests** (produce, volume, target market) |
| FR-SRV-3 | M | Customers submit **storage requests** (produce, quantity, duration, facility preference) |
| FR-SRV-4 | M | Warehouse staff record intake, storage and release for storage requests |
| FR-SRV-5 | M | All service requests share a common request/status/history pattern |
| FR-SRV-6 | S | Quotations/estimates attached to requests **[ASSUMPTION]** |

### 5.9 Export enquiries (`EXP`)

| ID | Priority | Requirement |
|---|---|---|
| FR-EXP-1 | M | Export buyers submit enquiries: product, volume, destination country, incoterms, timeline |
| FR-EXP-2 | M | Destination is an **international market**, not a company branch |
| FR-EXP-3 | M | Export officers issue quotations and track status |
| FR-EXP-4 | S | Export documents/compliance checklist per destination **[ASSUMPTION]** |
| FR-EXP-5 | S | Incoterm and currency support beyond NGN **[ASSUMPTION / needs approval]** |

### 5.10 Training and academy (`TRN`)

| ID | Priority | Requirement |
|---|---|---|
| FR-TRN-1 | M | Publish training courses (title, description, level, duration, fee optional) |
| FR-TRN-2 | M | Courses may have cohorts/schedules with capacity |
| FR-TRN-3 | M | Users enroll; enrollment status tracked (pending/confirmed/completed/cancelled) |
| FR-TRN-4 | S | Attendance records and certificates **[ASSUMPTION]** |
| FR-TRN-5 | S | Course payments integrate with the payment lifecycle **[ASSUMPTION]** |

### 5.11 Customer portal (`PORTAL`)

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
| FR-REP-1 | M | Sales summary by period, division, category, origin |
| FR-REP-2 | M | Stock position and low-stock report |
| FR-REP-3 | M | Service request volumes and turnaround |
| FR-REP-4 | M | Export enquiry pipeline report |
| FR-REP-5 | S | CSV export of reports **[ASSUMPTION]** |
| FR-REP-6 | S | Chart.js visual dashboards **[ASSUMPTION on chart set]** |

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

- Provider: **Paystack — implemented in a later phase** (explicitly not now).
- The model separates `Order` from `Payment` so providers can change.
- Webhook handling: verify signature, be idempotent, store raw payload.
- Refunds reference a payment, carry a reason and approver, and go through an
  approval step (staff permission required).
- **[ASSUMPTION-05]** Refund approval authority and time windows require owner
  policy.

---

## 12. Consultancy and service bookings

Covered by FR-CON-*. Each request: requester, division, details, preferred
schedule, status, assigned staff, history. Requests are visible to the customer
in the portal and to the relevant division queue in the dashboard.

---

## 13. Storage, farming and marketing requests

Covered by FR-SRV-*. Storage additionally tracks facility, intake, storage
duration and release. Farming tracks service type, farm location (state/LGA),
acreage and schedule. Marketing tracks produce, volume and target market.

---

## 14. Export enquiries

Covered by FR-EXP-*. Enquiries capture product, volume, **destination country**,
incoterms and timeline. Export officers produce quotations and advance a
pipeline. Destinations are external markets; no notion of company branches.

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

Covered by FR-REP-*. Reports are read-only, filterable by date range, and (from
the relevant phase) render with Chart.js. Figures are computed from real data;
no placeholder numbers are shipped as if real.

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
  Chart.js, Paystack (later), Pytest/pytest-django, Ruff; DRF only if needed.
- Email-first custom user model created before the first migration.
- Origin-specific listings with independent price and stock; nested categories.
- Verified Nigeria location import (36 states + FCT, 774 LGAs/area councils).

### 21.2 Assumptions requiring owner approval

| ID | Assumption | Needed by |
|---|---|---|
| ASSUMPTION-01 | Staff permission matrix / approval authority | Phase 5–10 |
| ASSUMPTION-02 | Final category list and nesting | Phase 4 (delivered — categories DB-driven; taxonomy sign-off pending) |
| ASSUMPTION-03 | Multi-origin listings per product allowed | Phase 4 (delivered — multiple listings per product supported) |
| ASSUMPTION-04 | VAT/tax and delivery-fee rules | Phase 6 |
| ASSUMPTION-05 | Refund policy, windows and approvers | Phase 6 |
| ASSUMPTION-06 | Email verification required before checkout | Phase 5 |
| ASSUMPTION-07 | Guest checkout not permitted | Phase 5 |
| ASSUMPTION-08 | Export currencies beyond NGN, incoterms set | Phase 8 |
| ASSUMPTION-09 | Course fees/payment and certificates | Phase 8 |
| ASSUMPTION-10 | Notifications channels (email only vs SMS/WhatsApp) | Phase 9 |
| ASSUMPTION-11 | Data-retention and account-deletion policy | Phase 10 |
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
5. Export currency/incoterm policy and countries served (ASSUMPTION-08).
6. Refund, cancellation and returns policy (ASSUMPTION-05).
7. Notification channels and budget (ASSUMPTION-10).
8. Data-retention and account-deletion expectations (ASSUMPTION-11).

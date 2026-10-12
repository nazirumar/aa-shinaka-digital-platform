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
| `apps.accounts` | Custom email user, canonical roles, capability permissions, auth views, profiles, addresses, staff account services | Phases 1–2 |
| `apps.cms` | CMS content models (pages, banners, divisions, services, blog, FAQs, testimonials, media, site settings, navigation), public website, CMS dashboard, sitemap/robots | Phases 1–3 |
| `apps.catalog` | Nested categories, products, variants/packaging, origin-specific listings, price engine, inventory ledger, public catalogue, catalogue/inventory dashboard | Phase 4 |
| `apps.cms` | CMS content models (pages, banners, divisions, services, blog, FAQs, testimonials, media, site settings, navigation), public website, CMS dashboard, sitemap/robots, i18n catalogue | Phase 3 |
| `apps.catalog` | Nested categories, products, variants/packaging, origin-specific listings, price engine, inventory ledger, public catalogue, catalogue/inventory dashboard | Phase 4 |
| `apps.orders` | Cart, checkout, orders, payments, refunds | Phases 5–6 |
| `apps.services` | Consultancy, farming, marketing, storage, export, training | Phases 7–8 |
| `apps.dashboard` | Staff dashboard views, staff management, audit log, reporting | Phases 2, 10 |

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
def confirm_payment(*, payment_reference, raw_payload) -> Payment: ...
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
/consultancy/ /farming/ …      apps.services
/export/ /training/ …          apps.services
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
  vendoring them locally is a deployment-hardening task in Phase 11.

---

## 6. Background task architecture

- Broker/result backend: **Redis**, accessed through Celery (`config/celery.py`).
- `CELERY_TASK_ALWAYS_EAGER` is `False` by default; tests set it `True`.
- Task conventions: idempotent, small, call a service function; heavy work
  (reports, exports, bulk email) is queued, never run in a request.
- Planned queues/tasks:
  - `email` — transactional email (registration, order, request updates).
  - `reports` — CSV/PDF report generation (`ReportExport`).
  - `integrations` — Paystack webhook reconciliation (later phase).
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

---

## 8. Payment lifecycle (planned — later phase)

Provider: **Paystack**. Implementation is intentionally deferred; the model and
flow are defined now so the schema does not need rework.

```
create order ──> Payment(status=pending) ──> redirect/initialize with provider
      │                                            │
      │                                  webhook: verify signature
      │                                            ▼
      └────────────── confirm_payment(service, atomic) ──> Order.paid
                                             │
                                     deduct stock (StockMovement: sale)
                                             │
                              failure/cancel: release reservation
```

- Webhooks are **verified** (signature) and **idempotent** (unique provider
  reference); raw payloads are stored on `Payment.raw_payload`.
- Refunds create `Refund` rows requiring approval and are reconciled against
  the provider.
- No provider keys are committed; they come from environment variables
  (`PAYSTACK_*`).

---

## 9. Order and inventory state transitions

- Order: `pending_payment → paid → processing → dispatched → delivered →
  completed`; terminal/exception: `cancelled`, `refunded`.
- Stock: **reserve** on order creation, **deduct** on payment confirmation,
  **release** on cancellation/refund; every change is an append-only
  `StockMovement` with a `balance_after` snapshot.
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
- Error tracking (e.g. Sentry) and metrics are Phase 11 hardening items.

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
  and password-reset endpoints (Phase 2; broader form throttling is Phase 11).
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
- Phase 4 tests cover nested categories (cycles, breadcrumbs, reorder, guarded
  delete), products (CRUD, status, specs, tags), origin-specific listings and
  images, the price engine (`ListingPrice`/`PriceHistory`/`WholesalePriceTier`)
  and separate market references, the inventory ledger and low-stock reporting,
  public catalogue routes/search/compare and leakage guards, and the staff
  catalogue/inventory dashboards and their capability gates.
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

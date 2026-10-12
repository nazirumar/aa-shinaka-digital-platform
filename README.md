# AA Shinaka Digital Business Platform

A standalone agricultural commerce and services platform for **AA Shinaka
General Enterprise**. It sells AA Shinaka's own products directly (not a
marketplace) and supports consultancy, farming services, agricultural marketing,
storage & warehousing, export, product sales and a training academy.

> **Scope note.** Oil and Gas is out of scope. This platform does not integrate
> with AgriTrade ERP and has no multi-vendor marketplace features.

## Status — Phases 1–4 complete

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

Phase 5 (cart/checkout/orders) and later phases are specified in the roadmap and
need owner approval.

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

## Technology stack

Django 5.2 LTS · Django Templates (MVT) · PostgreSQL · Tailwind CSS ·
HTMX · Alpine.js · Celery + Redis · Chart.js · Paystack (later phase) ·
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
uv run python manage.py sync_roles          # creates the 10 role:<code> groups
uv run python manage.py createsuperuser     # prompts for email (no username)
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/ and http://127.0.0.1:8000/healthz/.

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
apps/services/   Consultancy, farming, marketing, storage, export, training (Phases 7–8)
apps/dashboard/  Staff dashboard, staff management, audit log, reporting (Phases 2, 10)
templates/       Shared templates and components
static/          Tailwind source (src/) and build output (css/)
tests/           pytest suite
docs/            Phase 1–4 documentation
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
| `/dashboard/` | Staff dashboard |
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

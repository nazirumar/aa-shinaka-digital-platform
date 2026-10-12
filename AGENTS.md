# AGENTS.md

## What this is

Standalone Django 5.2 LTS **MVT monolith** (Django Templates — no SPA) for the
AA Shinaka agricultural business platform. Postgres + Tailwind + HTMX + Alpine +
Celery/Redis + Chart.js. See `docs/` for the spec; `docs/IMPLEMENTATION_ROADMAP.md`
is the phase plan. Phases 1 (foundation), 2 (auth, accounts, staff permissions & core
infrastructure), 3 (corporate website, premium homepage & CMS) and 4 (catalog:
categories, products, Nigeria locations, pricing & inventory) are done. Orders
(cart/checkout/orders) is **Phase 5** — do not start it without approval.
Phase 4 work lives in `apps/catalog` (public `/shop/`, staff
`/dashboard/catalog/` and `/dashboard/inventory/`) + `apps/locations`, and
reports in `docs/PHASE_4_COMPLETION_REPORT.md`; Phase 3 reports in
`docs/PHASE_3_COMPLETION_REPORT.md`.

Hard exclusions — never add: oil & gas features, multi-vendor marketplace
features, or any AgriTrade ERP integration. Never hardcode product categories,
state-specific prices, inventory or company achievements.

## Environment & commands

- Python is managed by **uv** (Python 3.12). Always go through uv; the system
  `python` is 3.13.
- Env comes from `.env` (gitignored; `.env.example` is the template). Settings:
  `config.settings.dev` (default) / `config.settings.prod`.
- `uv sync` installs Python deps; `npm install` installs Tailwind.

| Task | Command |
|---|---|
| Test | `uv run pytest` |
| Focused test | `uv run pytest tests/test_x.py -k name` |
| Lint / format | `uv run ruff check .` · `uv run ruff format --check .` |
| System check | `uv run python manage.py check` |
| Role groups | `uv run python manage.py sync_roles` (creates/refreshes the 10 `role:<code>` groups) |
| Migrations | `uv run python manage.py makemigrations && uv run python manage.py migrate` |
| Missing-migration guard | `uv run python manage.py makemigrations --check --dry-run` |
| Build CSS | `npm run build:css` (output `static/css/app.css` is gitignored — run this after template/class changes or the UI will be unstyled) |
| Dev server | `uv run python manage.py runserver` |
| Workers | `uv run celery -A config worker -l info` |

Required order before finishing a change: `ruff check` → `ruff format --check`
→ `pytest` → `manage.py check` (+ `makemigrations --check` when models change).

## Architecture rules that are easy to get wrong

- **Apps are domain-oriented** (`core`, `locations`, `accounts`, `catalog`,
  `cms`, `orders`, `services`, `dashboard`), not layer packages. Put write logic
  in `services.py`, reads in `selectors.py`, keep `views.py` thin (service layer
  convention in `docs/ARCHITECTURE.md`).
- `AUTH_USER_MODEL = "accounts.User"` is a **UUID-pk, email-login** custom user
  (`username` removed). Use `User.objects.create_user(email=...)` /
  `create_superuser(email=...)`. Public signup can only create `customer`
  (`apps/accounts/forms.py`).
- `apps.core` has abstract `TimeStampedModel` and `SoftDeleteModel` (soft delete
  hides rows via `objects`; use `all_objects` to see archived). Concrete models
  live in `core`, `accounts` (`User`, `Address`), `dashboard` (`AuditLog`),
  `locations` (`Country`, `State`, `LGA`, `City`) and `catalog` (`Category`,
  `Product`, `ProductListing`, `ProductVariant`, `ProductImage`, `UnitOfMeasure`,
  `Tag`, `ListingPrice`, `PriceHistory`, `WholesalePriceTier`,
  `MarketReferencePrice`, `StockMovement`). Catalogue primary keys are UUIDs.
- Roles are the ten canonical `accounts.UserRole` values; each maps to a Django
  group `role:<code>` (capabilities in `apps/accounts/roles.py`, enforcement in
  `apps/accounts/permissions.py`). Run `manage.py sync_roles` after migrations.
  Never gate access in templates — they only hide navigation.
- Money must be `DecimalField`, never float. Listings own their own price/stock.
- No new dependencies without need; **DRF is deferred** — do not add it unless a
  real machine client (e.g. a webhook) requires it.

## Gotchas

- The remaining app skeletons (`orders`, `services`) have empty `models.py`
  placeholders on purpose; their pages/models arrive in later phases.
  `dashboard` now has `AuditLog`; the rest of `dashboard` is later.
- `static/css/app.css` and `.env` are gitignored — a fresh clone needs
  `npm run build:css` and a `.env`.
- Nigeria locations live in `apps.locations` (moved out of `core` in Phase 4 with
  the legacy table names preserved) and are imported, not hand-entered:
  `uv run python manage.py import_nigeria_locations --source FILE` (expects
  37 states + 774 LGAs; `--strict`/`--dry-run` available). No dataset is bundled.
- Tests use `config.settings.dev` (see `[tool.pytest.ini_options]`); DB tests
  need `pytest.mark.django_db`. `makemigrations` runs against Postgres, not sqlite.

## Do not

- Commit secrets; only `.env.example` is tracked.
- Edit committed migrations by hand; generate and review them.
- Build a separate frontend app or vibe-code React/Vue/Next.

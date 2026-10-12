# Phase 4 Completion Report — Catalog, Categories, Nigeria Locations, Pricing & Inventory

**Document ID:** AASDP-PH4-REP-001  
**Status:** Complete (for owner/engineering approval before Phase 5)  
**Date:** 2026-10-12

## Objective delivered

Phase 4 delivers the data-driven catalogue: nested categories (with cycle
protection, materialised paths, breadcrumbs and safe delete), products
(draft/published/archived, search, specs, tags and audit), origin-specific
`ProductListing` rows, optional packaging/variants backed by `UnitOfMeasure`,
the pricing engine (`ListingPrice` / `PriceHistory` separation, wholesale tiers
and a standalone market reference price), product imagery, the public `/shop/`
storefront (plus legacy aliases), homepage integration, and the staff
catalogue/inventory dashboard. Categories, products, prices and stock are all
editable data — nothing is hardcoded.

## Files created/modified

### Apps (new)
- `apps/catalog/`: `__init__.py`, `apps.py`, `models.py`, `selectors.py`,
  `services.py`, `forms.py`, `views.py`, `urls.py`, `dashboard_views.py`,
  `dashboard_urls.py`, `validators.py`, `admin.py`,
  `templatetags/catalog_tags.py`, `migrations/0001–0006`, migration package
  `__init__.py` files.
- `apps/locations/`: `__init__.py`, `apps.py`, `models.py`,
  `migrations/0001–0003`.

### Templates
- Public: `templates/catalog/shop_index.html`, `category_list.html`,
  `category_detail.html`, `product_detail.html`, `state_list.html`,
  `state_detail.html`, `lga_detail.html`, `search.html`, `compare.html`,
  `not_found.html`, `partials/_listing_results.html`, `partials/_lga_options.html`.
- Dashboard: `templates/dashboard/catalog/home.html`, `category_list.html`,
  `product_list.html`, `product_images.html`, `listing_list.html`,
  `listing_detail.html`, `object_form.html`, `reference_list.html`,
  `low_stock.html`.
- Shared components reused/extended: `product_card.html`,
  `product_card_placeholder.html`, `category_card.html`, `state_card.html`,
  `image_gallery.html`, `lazy_image.html`, `breadcrumbs.html`, `pagination.html`,
  `empty_state.html`, `metric_card.html`, `form_field.html`, `alert.html`,
  `button.html`, `modal.html`.

### Configuration & shell
- `config/settings/base.py`: registered `apps.locations` and `apps.catalog`.
- `config/urls.py`: mounted `shop/` (public catalogue) and
  `dashboard/catalog/` (staff); legacy aliases `/states/`,
  `/states/<slug>/`, `/states/<state>/<lga>/`, `/products/<slug>/`,
  `/shop/<slug>/`; and `/dashboard/inventory/` (low-stock report) mapped to
  `LowStockListView`.
- `templates/base.html` / navbar / footer and homepage (`templates/home.html`)
  wired to catalogue selectors with graceful empty states.

## Models (catalog)

All catalogue primary keys are UUIDs; money is `DecimalField` only.

- `Category` — nested, self-referential `parent` (`PROTECT`), materialised
  `path` (max_length 2000) + `depth`, auto-slug, SEO fields, `is_active`,
  `is_featured`, `sort_order`; `MAX_CATEGORY_DEPTH = 40`; helpers `ancestors`,
  `descendants`, `breadcrumbs`, `active_children`, `is_leaf`; `clean()` rejects
  self/ancestor cycles and over-deep nesting; `delete()` refuses while children
  or products reference it.
- `UnitOfMeasure` — configurable units (name/code/symbol), seeded by migration.
- `Tag` — free-form product tag with auto-slug.
- `Product` — shared attributes (category `PROTECT`, unit, specs: variety/grade/
  harvest season, tags M2M, SEO, `primary_image`), lifecycle
  draft/published/archived; publish rules validated by
  `services._validate_publishable` (category + unit + ≥1 image + ≥1 active
  listing).
- `ProductListing` — origin-specific offer: product + state + LGA,
  `package_size` / `package_unit`, denormalised `selling_price` /
  `compare_at_price`, `stock_on_hand` / `stock_reserved`,
  `low_stock_threshold`, status, origin verification + note; uniqueness on
  `(product, state, lga, package_size, package_unit)`; check constraints for
  positive package size and non-negative price/stock; `packaging`,
  `available_stock`, `in_stock`, `is_sellable`, `low_stock` helpers;
  `delete()` refused while price/stock history exists (archive instead).
- `ProductVariant` — optional priceable variant of a listing (stock stays at the
  listing level in Phase 4); unique name per listing.
- `ProductImage` — product image optionally tied to one listing; extension +
  5 MB validators; sort order; primary pointer on `Product`.
- `ListingPrice` — price engine row (variant-aware, `selling`/`promo`,
  validity window, currency, actor); one open active price per
  `(listing, variant, price_type)` via `UniqueConstraint(...,
  nulls_distinct=False)`; non-negative amount/compare constraints; window
  overlap validated in the service.
- `PriceHistory` — append-only price log (edit/delete raise `ValidationError`).
- `WholesalePriceTier` — tiered B2B pricing; unique `(listing, variant,
  min_quantity)` (`nulls_distinct=False`); positive qty / non-negative price.
- `MarketReferencePrice` — market/intelligence reference prices kept separate
  from listing prices (unique open national row and per-state rows;
  non-negative; year-bounded).
- `StockMovement` — append-only inventory ledger (intake/adjustment/sale/
  return/damage/transfer) with `balance_after`; edit/delete raise
  `ValidationError`.

## Models (locations)

Moved out of `apps.core` in Phase 4 with legacy table names preserved, so all
existing foreign keys remain valid.

- `Country` — seeded (Nigeria `NG`).
- `State` — FK to `Country`, geopolitical zone, auto-slug; `db_table =
  "core_state"`.
- `LGA` — FK to `State`, per-state unique name + slug; `db_table = "core_lga"`.
- `City` — optional LGA link, per-state unique name.
- `NigeriaLocationImport` — audit row per importer run; `db_table =
  "core_nigeria_location_import"`.
- Import path: `uv run python manage.py import_nigeria_locations --source FILE`
  (expects 37 states + 774 LGAs; `--strict` / `--dry-run` available). No dataset
  is bundled.

## Migrations

- `catalog/0001_initial.py`, `0002_initial.py` — baseline catalogue schema.
- `catalog/0003_listingprice_marketreferenceprice_pricehistory_and_more.py` —
  pricing engine, price history, wholesale tiers, market reference prices,
  stock movements, variants and images.
- `catalog/0004_fix_category_path_constraint.py` — corrected path format check.
- `catalog/0005_allow_blank_category_slug.py` — allow auto-slug generation.
- `catalog/0006_alter_category_path.py` — `Category.path` widened to 2000.
- `locations/0001_initial.py` — Country/State/LGA/City/import (legacy table
  names).
- `locations/0002_lga_slug_lga_uniq_lga_slug_per_state.py` — LGA slug + per-state
  uniqueness.
- `locations/0003_align_import_table_name.py` — align import table name.

## Public catalogue URLs

Canonical (`apps.catalog.urls`, mounted at `shop/`):
- `/shop/` (`catalog:shop_index`)
- `/shop/categories/` (`category_list`)
- `shop/category/<slug>/` (category detail)
- `shop/product/<slug>/` (product detail)
- `shop/states/` / `shop/state/<slug>/` / `shop/state/<state>/<lga>/`
- `shop/search/`, `shop/compare/`, `shop/lga-options/` (HTMX LGA dropdown; the
  staff form gets LGA PKs, the public filter passes `?state=` and gets slugs)

Legacy aliases (kept stable for shared links, `docs/UI_UX_SPEC.md` §5.2):
- `/states/`, `/states/<slug>/`, `/states/<state>/<lga>/`
- `/products/<slug>/`
- `/shop/<slug>/`

## Catalogue dashboard URLs (staff)

Mounted at `/dashboard/catalog/` (`catalog_dashboard`):

- Home; Categories (list/new/edit/delete/reorder/toggle).
- Products (list/new/edit/delete/publish/images/manage image/delete image/set
  primary).
- Listings (list/new/detail/edit/archive-status/status/price/stock/variants/
  tiers; tier delete).
- Inventory low-stock report at `/dashboard/catalog/low-stock/` and the
  canonical alias `/dashboard/inventory/` (`inventory_low_stock`).
- Market references (list/new/edit).

Every dashboard view enforces the catalogue/inventory capability server-side
(templates only hide navigation). Reads use `selectors`; writes go through
`services`, which record audit entries (`dashboard.AuditLog`) and surface
`ValidationError` as form/messages errors.

## Tests

New Phase 4 suites (143 tests):

- `tests/test_catalog_categories.py` — 21 (nesting, cycles, paths/depth,
  breadcrumbs, reorder, safe delete, slug rules).
- `tests/test_catalog_products.py` — 14 (draft start, slug collisions, tags,
  audit, publish requirements, archive-not-delete, delete guard).
- `tests/test_catalog_listings.py` — 15 (draft + opening price, packaging,
  stock math, origin/package uniqueness, LGA/state validation, status
  transitions, archive-vs-delete, variants).
- `tests/test_catalog_pricing.py` — 22 (headline sync + history chain, window
  overlap, scheduled windows, effective price selection, variant isolation,
  wholesale tiers, market reference independence).
- `tests/test_catalog_inventory.py` — 8 (adjust stock ledger, negative/bad-kind
  rejection, status toggles, reconciliation, append-only, audit).
- `tests/test_catalog_public.py` — 31 (shop index, categories, product detail,
  states/LGA, search, compare, lga-options, legacy aliases, SEO, empty states).
- `tests/test_catalog_dashboard.py` — 32 (capability gating incl. inventory vs
  catalogue and the low-stock alias, category/product/listing CRUD, publish,
  images, price/stock/tiers/references).

The six Nigeria-location import tests in `tests/test_locations_import.py`
travelled with `apps.locations` (they were part of the Phase 1–3 baseline and
remain green).

**Total:** 143 new tests; **313 collected** overall, all passing, no
regressions (Phase 1–3 baseline was 170).

## Quality gates (end of Phase 4)

- `uv run python manage.py check` — clean.
- `uv run python manage.py makemigrations --check --dry-run` — no changes.
- `uv run ruff check .` — clean; `uv run ruff format --check .` — clean.
- `uv run pytest` — 313 passed (170 baseline + 143 new).
- `npm.cmd run build:css` — Tailwind built `static/css/app.css` (gitignored).
- No secrets committed; no hardcoded categories/prices/inventory/achievements;
  no oil & gas, multi-vendor or AgriTrade ERP.

## Documentation updated in Phase 4

- `docs/IMPLEMENTATION_ROADMAP.md` — version 0.4: **Phase 4 = Catalog,
  Categories & Nigeria Locations ✅**; Phase 5 (Orders) is next.
- `docs/ARCHITECTURE.md` — version 0.4; `apps.catalog` / `apps.locations` rows,
  catalogue routes, cross-app import rule, testing notes.
- `docs/DATABASE_DESIGN.md` — version 0.4; §2 rewritten as `locations`
  (Country/State/LGA/City/import), §4 catalogue rewritten with all UUID models
  and constraints, §9 ER summary and §10.4 delivered.
- `docs/UI_UX_SPEC.md` — version 0.4; §5.1 / §5.2 public routes delivered.
- `docs/SRS.md` — version 0.4; revision note; §5.2 / §5.3 / §5.4 marked
  delivered; assumptions 02/03/12 updated.
- `README.md` — status `Phases 1–4 complete`; Phase 4 summary, docs table,
  project layout.
- `AGENTS.md` — Phases 1–4 done, catalog/locations models; Phase 5 next
  (approval required).

## Known limitations / assumptions

- Scheduled price windows (`valid_from` / `valid_to` in the future) do **not**
  auto-activate: there is no Celery beat schedule in Phase 4, so the
  denormalised headline price only changes when staff set a price or the
  effective-price selector is read. Activation automation is deferred.
- ASSUMPTION-02 (category taxonomy) and ASSUMPTION-12 (official Nigeria
  location dataset source) still need owner sign-off; the importer ships without
  a dataset, and no categories are seeded.
- `ProductVariant` is priceable but stock is tracked at the listing level in
  Phase 4; per-variant inventory is deferred.
- `ProductListing.stock_reserved` exists for future order reservations; nothing
  writes it yet (Orders is Phase 5).
- Image handling uses local storage and validators only (no CDN/transform
  pipeline this phase).

## Phase 5 recommendation

Per roadmap revision (docs updated): **Phase 5 — Orders (cart, checkout,
orders)**. Do not start until this report is approved. `stock_reserved` and the
append-only ledgers are ready for order-driven stock movements.

---

**Verification:** All tests green, system checks clean, migrations up-to-date,
styles built, docs updated.  
**STOP after Phase 4 — await approval before Phase 5.**

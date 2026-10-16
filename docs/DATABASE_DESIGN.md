# Database Design
## AA Shinaka Digital Business Platform — PostgreSQL

| | |
|---|---|
| Document ID | AASDP-DB-001 |
| Version | 0.4 (Phase 1–4) |
| Status | For owner/engineering review |
| Engine | PostgreSQL 18 (production target ≥ 15) |

> **Scope.** This document specifies the full proposed schema. `core`,
> `locations`, `accounts` and the `dashboard.AuditLog` model are implemented
> (Phases 1–4), together with the `cms` schema (Phase 3) and the `catalog`
> catalogue schema (Phase 4); all other models are planned and implemented in
> the phases listed in `docs/IMPLEMENTATION_ROADMAP.md`. Field lists are the
> design contract; review comments from the owner are expected. No real prices,
> stock counts or capacities appear here — only rules.
>
> **Revision 0.4 (Phase 4).** Geographic reference data moved from `apps.core`
> into a dedicated `apps.locations` app (`Country`, `State`, `LGA`, `City`);
> physical table names (`core_state`, `core_lga`, `core_nigeria_location_import`)
> are preserved so existing foreign keys need no data migration. The `catalog`
> schema (§4) is delivered: all catalogue keys are UUIDs, and the price/inventory
> ledgers are append-only.

---

## 1. Conventions

| Concern | Convention |
|---|---|
| Primary keys | `BigAutoField` for high-volume transactional tables; `UUIDField` for users and audit-ish/import records |
| Timestamps | Every business model inherits `TimeStampedModel`: `created_at` (indexed), `updated_at` |
| Soft deletion | `SoftDeleteModel` adds `is_deleted`, `deleted_at`; default manager hides archived rows, `all_objects` includes them |
| Money | `DecimalField(max_digits=14, decimal_places=2)`; never `FloatField` |
| Currency | `CharField(max_length=3, default="NGN")` where multi-currency is expected (export) |
| Status | `CharField` + `TextChoices`; indexed where queried |
| Naming | snake_case; related names are plural and explicit |
| Delete behaviour | `PROTECT` for reference data (State, LGA, Category), `SET_NULL` for optional actors, `CASCADE` for owned children |
| Enums | `TextChoices` classes; DB `CheckConstraint` for invariant combinations where practical |
| Indexes | Explicit indexes on all FK/status/filter/sort columns used by list pages |

### 1.1 Abstract bases (`apps.core.models`)

| Model | Fields | Purpose |
|---|---|---|
| `TimeStampedModel` | `created_at`, `updated_at` | Audit timestamps |
| `SoftDeleteModel(TimeStampedModel)` | `+ is_deleted`, `deleted_at` | Archival instead of destructive delete |

---

## 2. `locations` — Nigeria geographic reference data

> Phase 4 moved `State`, `LGA`, `GeopoliticalZone` and `NigeriaLocationImport`
> out of `apps.core` into `apps.locations`, and added `Country` and `City`. The
> physical tables keep their legacy `core_*` names, so no row or foreign key had
> to move. `import_nigeria_locations` and all existing FKs are unchanged.

### 2.1 `Country` (implemented)

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `name` | `CharField(64)` | **unique** |
| `code` | `CharField(3)` | **unique**, ISO 3166-1 alpha-2 (Nigeria = `NG`) |
| `is_active` | `BooleanField` | indexed, default True |
| timestamps | | |

- Nigeria is seeded by the importer; the table makes provenance explicit.

### 2.2 `State` (implemented)

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `country` | FK → `Country` | `PROTECT`, `related_name="states"` |
| `name` | `CharField(64)` | **unique** |
| `code` | `CharField(8)` | **unique**, e.g. `FC`, `LA` |
| `slug` | `SlugField(80)` | **unique**, auto from name |
| `zone` | `CharField(2)` | choices `NC NE NW SE SS SW`, indexed |
| `is_active` | `BooleanField` | indexed, default True |
| `created_at`,`updated_at` | DateTime | from base |

- Table: `core_state`.
- Ordering: `name`.
- Validation: `code` uppercase; `slug` generated when blank.
- Seed target: **37** rows (36 states + FCT).

### 2.3 `LGA` (implemented)

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `state` | FK → `State` | `PROTECT`, `related_name="lgas"` |
| `name` | `CharField(96)` | |
| `slug` | `SlugField(80)` | unique per state; auto-generated with collision suffix |
| `code` | `CharField(16)` | optional source code |
| `is_active` | `BooleanField` | indexed |
| timestamps | | |

- Table: `core_lga`.
- Constraints: `UniqueConstraint(state, name)` → `uniq_lga_name_per_state`;
  `UniqueConstraint(state, slug)` → `uniq_lga_slug_per_state`.
- Index: `(state, name)` → `core_lga_state_name_idx`.
- Seed target: **774** rows (LGAs + area councils).

### 2.4 `City` (optional, implemented)

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `state` | FK → `State` | `PROTECT`, `related_name="cities"` |
| `lga` | FK → `LGA` | `PROTECT`, null/blank, `related_name="cities"` |
| `name` | `CharField(96)` | |
| `is_active` | `BooleanField` | indexed, default True |
| timestamps | | |

- Constraint: `UniqueConstraint(state, name)` → `uniq_city_name_per_state`.
- Index: `(state, name)` → `loc_city_state_name_idx`. Cities are optional and
  never required for a listing (origin is always state + LGA).

### 2.5 `NigeriaLocationImport` (implemented)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `source` | `CharField(512)` | file path/URI |
| `source_checksum` | `CharField(64)` | SHA-256 of the source file |
| `states_imported` | `PositiveIntegerField` | |
| `lgas_imported` | `PositiveIntegerField` | |
| `succeeded` | `BooleanField` | |
| `message` | `TextField` | warnings/failure detail |
| `created_at` | DateTime | |

- Table: `core_nigeria_location_import`.

### 2.6 Nigeria location import strategy (verified)

1. **Source.** Obtain a dataset from an authoritative, verifiable source
   (e.g. INEC / NBS / an official gazette or a well-maintained open dataset with
   a documented licence). **The owner must approve the source** — no dataset is
   bundled or invented by the project.
2. **Format.** CSV with header
   `state_name,state_code,zone,lga_name,lga_code` (case-insensitive; UTF-8).
3. **Load.** `uv run python manage.py import_nigeria_locations --source FILE`
   - Idempotent `update_or_create` keyed on `State.code` and `(State, LGA.name)`.
   - Upserts are wrapped in a single `transaction.atomic()` block.
   - Each run writes a `NigeriaLocationImport` audit row with a SHA-256 checksum.
4. **Verify.** `--strict` refuses to write unless totals equal the expected
   national counts (default `--expected-states 37 --expected-lgas 774`). Use
   `--dry-run` to validate a file without writing.
5. **Re-verify after changes.** Re-running the command on the same file must
   report the same totals and create no duplicates.
6. **Refresh procedure.** On a dataset update: run `--dry-run --strict`, review
   the diff, then run for real; the audit rows preserve provenance.
7. **Change of state boundaries** (rare) is a data operation, not a code change.

> **[ASSUMPTION-12]** The exact dataset source is pending owner approval. The
> importer is provider-agnostic; only the CSV contract matters.

---

## 3. `accounts` — users & addresses

### 3.1 `User` (implemented)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK, default `uuid4` |
| `email` | `EmailField` | **unique**, indexed, `USERNAME_FIELD`; lower-cased |
| `password` | `CharField(128)` | hashed (Django) |
| `first_name`,`last_name` | `CharField(150)` | |
| `phone` | `CharField(20)` | indexed |
| `role` | `CharField(32)` | `UserRole` choices (10 canonical roles), indexed, default `customer` |
| `state` | FK → `core.State` | `SET_NULL`, nullable |
| `is_email_verified` | `BooleanField` | default False, indexed |
| `email_verified_at` | DateTime | nullable, set on verification |
| `email_verification_nonce` | UUID | rotated on verification (replay protection) |
| `marketing_opt_in` | `BooleanField` | default False |
| `last_seen_at` | DateTime | nullable |
| `is_active`,`is_staff`,`is_superuser` | Boolean | from `AbstractUser` |
| `last_login`,`date_joined` | DateTime | from `AbstractUser` |
| `created_at`,`updated_at` | DateTime | audit |

- `username` intentionally removed; login is by email (case-insensitive via
  `get_by_natural_key`).
- Indexes: `role`, `phone`, `email`, `is_email_verified`.
- `Meta.permissions`: `view_staff`, `add_staff`, `change_staff`,
  `deactivate_staff`, `assign_roles` — the staff-management capabilities.
- Validation: email normalised (lower-cased) and unique; role must be a valid
  `UserRole`. Customer is the only self-assignable role; superusers are forced
  to `owner`.

### 3.2 `Address` (implemented, Phase 2)

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `user` | FK → `User` | `CASCADE`, `related_name="addresses"` |
| `label` | `CharField(50)` | e.g. "Home", "Farm" (blank allowed) |
| `recipient_name` | `CharField(150)` | |
| `phone` | `CharField(20)` | |
| `country` | `CharField(64)` | default `Nigeria` |
| `state` | FK → `State` | `PROTECT`, `related_name="addresses"` |
| `lga` | FK → `LGA` | `PROTECT`, `related_name="addresses"` |
| `city` | `CharField(120)` | |
| `street_address` | `CharField(255)` | |
| `landmark` | `CharField(255)` | blank |
| `postal_code` | `CharField(16)` | blank |
| `is_default` | `BooleanField` | |
| timestamps | | |

- Constraint: at most one default per user
  (`UniqueConstraint(user, condition=is_default)` →
  `uniq_default_address_per_user`).
- Index: `(user, is_default)` → `acct_addr_user_default_idx`.
- Validation: `Address.clean()` rejects an LGA that is not in the selected state.

### 3.3 `Notification` (superseded — see §6c)

The `accounts.Notification` model sketched in earlier drafts was **not created**.
Phase 10 delivered the notification centre in the dedicated
**`apps.notifications`** app (`Notification`, `NotificationPreference`,
`NotificationDelivery`) — see §6c for the implemented schema. Keeping the feed,
its preferences and its delivery ledger with their channels and event builders in
one domain app avoids a cross-cutting model in `accounts`.

---

## 4. `catalog` — categories, products, listings, pricing, inventory

> Delivered in Phase 4 (migrations `catalog.0001`–`0006`). All catalogue primary
> keys are UUIDs. `Category`, `Product` and `ProductListing` are soft-delete
> models (default managers hide archived rows; `all_objects` includes them).
> Packaging, prices, stock and **categories are DB rows only** — nothing is
> hardcoded (FR-CAT-2, FR-LOC-4, FR-PRICE-2).

### 4.1 `Category` (nested)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `parent` | FK → self | `PROTECT`, null, `related_name="children"` |
| `name` | `CharField(120)` | unique per parent |
| `slug` | `SlugField(140)` | **unique**, auto (collision suffix) |
| `description` | `TextField` | blank |
| `image` | `ImageField` | optional (type + 5 MB validators) |
| `path` | `CharField(2000)` | materialised ancestor-PK chain (`<pk>/<pk>/`) |
| `depth` | `PositiveSmallIntegerField` | mirrored from `path`; max depth 40 |
| `is_active` | `BooleanField` | indexed |
| `is_featured` | `BooleanField` | indexed |
| `sort_order` | `IntegerField` | default 0 |
| `seo_title` / `seo_description` | `CharField(180)` / `CharField(255)` | blank |
| `is_deleted`,`deleted_at` | soft delete | |
| timestamps | | |

- Constraints: `UniqueConstraint(parent, name)`, `UniqueConstraint(slug)`
  (both conditioned on `is_deleted=False`); `CheckConstraint(package…)` n/a.
- Indexes: `parent`, `slug`, `(is_active, sort_order)`, `(is_active, is_featured)`.
- Validation: `clean()` rejects self/descendant parenting and enforces
  `MAX_CATEGORY_DEPTH`; `save()` maintains `slug`/`path`/`depth` and re-paths
  descendants on a move. `ancestors()`/`descendants()`/`breadcrumbs()` are
  path-based and cheap.
- **No categories are hardcoded**; loaded by staff through the dashboard.

### 4.2 `UnitOfMeasure`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | `CharField(64)` | unique |
| `code` | `CharField(16)` | unique (e.g. `kg`, `tonne`) |
| `symbol` | `CharField(8)` | blank |
| `is_active` | `BooleanField` | indexed |
| `sort_order` | `IntegerField` | default 0 |
| timestamps | | |

- Seeded by data migration; referenced by `Product.unit`,
  `ProductListing.package_unit` and `MarketReferencePrice.unit` (`PROTECT`).

### 4.3 `Tag`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | `CharField(60)` | unique |
| `slug` | `SlugField(80)` | unique |
| timestamps | | |

### 4.4 `Product`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `category` | FK → `Category` | `PROTECT`, `related_name="products"` |
| `name` | `CharField(180)` | |
| `slug` | `SlugField(200)` | **unique** (conditioned on not deleted) |
| `short_description` | `CharField(255)` | blank |
| `description` | `TextField` | blank |
| `unit` | FK → `UnitOfMeasure` | `PROTECT`, nullable |
| `status` | `CharField(16)` | `PublishStatus` (`draft`,`published`,`archived`), indexed |
| `is_featured` | `BooleanField` | indexed |
| `variety` / `grade` / `harvest_season` | `CharField` | blank |
| `tags` | `M2M` → `Tag` | optional |
| `primary_image` | FK → `ProductImage` | `SET_NULL`, nullable |
| `seo_title` / `seo_description` | `CharField(180)` / `CharField(255)` | blank |
| `is_deleted`,`deleted_at` | soft delete | |
| timestamps | | |

- Indexes: `(status, is_featured)`, `(category, status)`, `slug`.
- Validation: publishing requires a category, a unit, ≥1 image and ≥1
  **active** listing (enforced in `services._validate_publishable` and
  `Product.clean()`).

### 4.5 `ProductImage`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `product` | FK → `Product` | `CASCADE`, `related_name="images"` |
| `listing` | FK → `ProductListing` | `CASCADE`, null — optional link to an origin |
| `image` | `ImageField` | validated content type & 5 MB size |
| `alt_text` | `CharField(180)` | accessibility |
| `sort_order` | `IntegerField` | default 0 |
| timestamps | | |

### 4.5 `ProductListing` (origin-specific offer)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `product` | FK → `Product` | `CASCADE`, `related_name="listings"` |
| `state` | FK → `State` | `PROTECT`, `related_name="listings"` |
| `lga` | FK → `LGA` | `PROTECT`, `related_name="listings"` |
| `package_size` | `DecimalField(12,3)` | > 0, e.g. 50.000 |
| `package_unit` | FK → `UnitOfMeasure` | `PROTECT`; independent of product unit |
| `selling_price` | `DecimalField(14,2)` | **listing-specific** denormalised price, NGN |
| `currency` | `CharField(3)` | default `NGN` |
| `compare_at_price` | `DecimalField(14,2)` | nullable |
| `stock_on_hand` | `DecimalField(14,3)` | denormalised on-hand |
| `stock_reserved` | `DecimalField(14,3)` | reserved by open orders |
| `low_stock_threshold` | `DecimalField(14,3)` | nullable |
| `status` | `CharField(16)` | `ListingStatus` (`draft`,`active`,`out_of_stock`,`archived`) |
| `origin_verification` | `CharField(16)` | `OriginVerification` (`unverified`,`pending`,`verified`) |
| `origin_note` | `TextField` | provenance/quality note |
| `is_deleted`,`deleted_at` | soft delete | |
| timestamps | | |

- **Constraint:** `UniqueConstraint(product, state, lga, package_size, package_unit)`
  → `uniq_listing_origin_package` (conditioned on not deleted).
- CheckConstraints: `package_size > 0`, `selling_price >= 0`, `stock_on_hand >= 0`,
  `stock_reserved >= 0`, `stock_reserved <= stock_on_hand`.
- Indexes: `(state, lga)`, `(product, status)`, `(status, selling_price)`,
  `state`, `lga`, `status`.
- `available_stock` = `stock_on_hand - stock_reserved` (property); `low_stock`
  compares it to `low_stock_threshold`.
- **No state-specific prices are hardcoded anywhere**; all prices are rows.

### 4.5a `ProductVariant` (priceable)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `listing` | FK → `ProductListing` | `CASCADE`, `related_name="variants"` |
| `name` | `CharField(80)` | |
| `notes` | `CharField(255)` | blank |
| `sort_order` | `IntegerField` | default 0 |
| `is_active` | `BooleanField` | indexed |
| timestamps | | |

- Constraint: `UniqueConstraint(listing, name)`. Variants participate in the
  price engine (`ListingPrice`/`WholesalePriceTier`); **stock stays at listing
  level**.

### 4.5b `ListingPrice` (price engine)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `listing` | FK → `ProductListing` | `PROTECT`, `related_name="prices"` |
| `variant` | FK → `ProductVariant` | `PROTECT`, null (base price) |
| `price_type` | `CharField(16)` | `PriceType` (`selling`,`wholesale`,`market_reference`) |
| `amount` | `DecimalField(14,2)` | |
| `compare_at` | `DecimalField(14,2)` | nullable |
| `currency` | `CharField(3)` | default `NGN` |
| `valid_from` / `valid_to` | DateTime | nullable, indexed (scheduled windows) |
| `is_active` | `BooleanField` | indexed |
| `created_by` | FK → `User` | `SET_NULL`, null |
| timestamps | | |

- Constraint: at most one open-ended active price per
  `(listing, variant, price_type)` → `uniq_open_active_price`
  (`nulls_distinct=False`); CheckConstraints for non-negative amounts.
- `selectors.effective_price()` picks the live row (started, not expired),
  preferring a scheduled window over the open-ended fallback.

### 4.5c `PriceHistory` (append-only)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `listing` | FK → `ProductListing` | `PROTECT`, `related_name="price_history"` |
| `variant` | FK → `ProductVariant` | `SET_NULL`, null |
| `price_type` | `CharField(16)` | `PriceType` |
| `old_price` / `new_price` | `DecimalField(14,2)` | |
| `currency` | `CharField(3)` | default `NGN` |
| `changed_by` | FK → `User` | `SET_NULL`, null |
| `note` | `TextField` | blank |
| timestamps | | |

- Index: `(listing, -created_at)`. **Append-only** — edits/deletes raise
  `ValidationError`. Written by `set_listing_price`.

### 4.5d `WholesalePriceTier` (bulk pricing)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `listing` | FK → `ProductListing` | `CASCADE`, `related_name="wholesale_tiers"` |
| `variant` | FK → `ProductVariant` | `CASCADE`, null |
| `min_quantity` | `DecimalField(14,3)` | > 0 |
| `price` | `DecimalField(14,2)` | >= 0 |
| `currency` | `CharField(3)` | default `NGN` |
| `is_active` | `BooleanField` | indexed |
| timestamps | | |

- Constraint: `UniqueConstraint(listing, variant, min_quantity)`
  (`nulls_distinct=False`) → `uniq_tier_min_qty`.

### 4.5e `MarketReferencePrice` (informational, kept separate)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `product` | FK → `Product` | `CASCADE`, `related_name="market_references"` |
| `state` | FK → `State` | `PROTECT`, null = national reference |
| `year` | `PositiveIntegerField` | indexed, 2000–2100 |
| `season` | `CharField(60)` | blank |
| `price_per_unit` | `DecimalField(14,2)` | >= 0 |
| `unit` | FK → `UnitOfMeasure` | `PROTECT` |
| `currency` | `CharField(3)` | default `NGN` |
| `source` / `note` | `CharField(120)` / `TextField` | informational provenance |
| timestamps | | |

- Constraints: unique per `(product, state, year, season, unit)` when a state is
  set, and per `(product, year, season, unit)` for national rows
  (`nulls_distinct` not required because `state` is part of the condition).
- **Reference prices are never selling prices.** They are stored strictly
  separately from `ListingPrice` and never surfaced as a product's price.

### 4.6 `StockMovement` (auditable inventory ledger)

| Field | Type | Notes |
|---|---|---|
| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `listing` | FK → `ProductListing` | `PROTECT`, `related_name="movements"` |
| `variant` | FK → `ProductVariant` | `PROTECT`, nullable (Phase 5) |
| `warehouse` | FK → `Warehouse` | `PROTECT`, nullable (Phase 5) |
| `kind` | `CharField(16)` | `StockMovementKind` (`intake`,`adjustment`,`sale`,`return`,`damage`,`transfer`) |
| `quantity_delta` | `DecimalField(14,3)` | signed |
| `balance_after` | `DecimalField(14,3)` | snapshot |
| `reference` | `CharField(100)` | order no. / note |
| `actor` | FK → `User` | `SET_NULL`, nullable |
| `note` | `TextField` | blank |
| `created_at` | DateTime | indexed |

- Index: `(listing, -created_at)`.
- **Append-only**: movements are never edited or deleted; stock writes take a row
  lock on the `StockBalance` (and listing), apply the delta, refuse to go
  negative/reserved, and write a movement in one transaction.

### 4.7 `Warehouse` (Phase 5)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | `CharField(120)` | |
| `code` | `CharField(32)` | unique, indexed |
| `address` | `CharField(255)` | blank |
| `state`,`lga` | FK → `locations.State`/`LGA` | `PROTECT`, nullable; LGA must belong to state |
| `is_active` | Boolean | indexed |
| timestamps | | |

- Warehouses are data-driven; the default (`code="MAIN"`) is created on first
  use by `apps.catalog.inventory.default_warehouse()`.

### 4.8 `StockBalance` (Phase 5 — authoritative per-warehouse stock)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `warehouse` | FK → `Warehouse` | `CASCADE`, `related_name="balances"` |
| `listing` | FK → `ProductListing` | `CASCADE`, `related_name="balances"` |
| `variant` | FK → `ProductVariant` | `CASCADE`, nullable |
| `on_hand` | `DecimalField(14,3)` | authoritative quantity |
| `reserved` | `DecimalField(14,3)` | held by active reservations |
| timestamps | | |

- Constraint: unique `(warehouse, listing, variant)` (nulls not distinct).
- The listing's `stock_on_hand`/`stock_reserved` are **roll-ups** across
  warehouses; `available = on_hand − reserved`. Phase 4's `adjust_stock` now
  delegates here, so the ledger and balances stay consistent.

### 4.9 Status enumerations (`catalog`)

```
PublishStatus       : draft | published | archived
ListingStatus       : draft | active | out_of_stock | archived
OriginVerification  : unverified | pending | verified
PriceType           : selling | wholesale | market_reference
StockMovementKind   : intake | adjustment | sale | return | damage | transfer
```

- `UnitOfMeasure` is a **table**, not an enum (staff-editable, seeded with the
  common units).

---

## 5. `orders` — cart, checkout, orders & fulfilment

Phase 5 implements cart/checkout/orders with a **provider-independent payment
boundary**; Phase 6 adds the provider payment rows (`Payment`, `Refund`,
`Invoice`, `Receipt`, bank-transfer and webhook records — see §5.12). Both the
audited `confirm_payment` service and verified provider captures converge on the
idempotent `settle_order` service.

### 5.1 `ShippingZone`, `ShippingMethod`, `ShippingRate`

| Field | Type | Notes |
|---|---|---|
| `ShippingZone.id` | UUID | PK |
| `ShippingZone.name` | `CharField(120)` | |
| `ShippingZone.code` | `CharField(40)` | unique |
| `ShippingZone.description` | `TextField` | blank |
| `ShippingZone.states` | M2M → `State` | `related_name="shipping_zones"` |
| `ShippingZone.is_active` | Bool | default `True` |
| `ShippingMethod.name` | `CharField(120)` | |
| `ShippingMethod.code` | `CharField(40)` | unique |
| `ShippingMethod.description` | `TextField` | blank |
| `ShippingMethod.sort_order` | `PositiveInteger` | default 0 |
| `ShippingMethod.is_active` | Bool | default `True` |
| `ShippingRate.zone` | FK → `ShippingZone` | `CASCADE`, `related_name="rates"` |
| `ShippingRate.method` | FK → `ShippingMethod` | `CASCADE`, `related_name="rates"` |
| `ShippingRate.fee` | `DecimalField(14,2)` | required |
| `ShippingRate.free_over` | `DecimalField(14,2)` | nullable; free at/above |
| `ShippingRate.min_order_amount` | `DecimalField(14,2)` | required, default 0 |
| `ShippingRate.is_active` | Bool | default `True` |

- Constraint: unique `(zone, method)`.
- **No freighting is invented:** checkout is blocked unless a matching active
  rate exists for the destination state.

### 5.2 `Cart`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `user` | FK → `User` | `CASCADE`, nullable (guest carts) |
| `session_key` | `CharField(64)` | blank; guest key |
| `status` | `CharField(16)` | `CartStatus` (`active`,`converted`,`abandoned`) |
| `checked_out_at` | DateTime | nullable |
| timestamps | | |

- Constraints: at most one **active** cart per user and per session (partial
  unique constraints). Guest carts are merged into the user's cart on login.

### 5.3 `CartItem`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `cart` | FK → `Cart` | `CASCADE`, `related_name="items"` |
| `listing` | FK → `ProductListing` | `CASCADE` |
| `variant` | FK → `ProductVariant` | `CASCADE`, nullable |
| `quantity` | `DecimalField(14,3)` | > 0 |
| `unit_price_snapshot` | `DecimalField(14,2)` | indicative; recomputed at checkout |

- Constraint: unique `(cart, listing, variant)` (nulls not distinct).

### 5.4 `StockReservation`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `order` | FK → `Order` | `PROTECT`, `related_name="reservations"` |
| `order_item` | FK → `OrderItem` | `PROTECT`, nullable, `related_name="reservations"` |
| `listing` | FK → `ProductListing` | `PROTECT` |
| `variant` | FK → `ProductVariant` | `PROTECT`, nullable |
| `warehouse` | FK → `Warehouse` | `PROTECT`, nullable |
| `quantity` | `DecimalField(14,3)` | |
| `status` | `CharField(16)` | `ReservationStatus` (`active`,`committed`,`released`,`expired`) |
| `expires_at` | DateTime | indexed, nullable |
| `released_at`,`committed_at` | DateTime | nullable |

- One reservation per order item; each can leave `active` exactly once
  (idempotent lifecycle).

### 5.5 `Order`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `number` | `CharField(24)` | unique, `AS-YYYYMMDD-XXXXXX` |
| `checkout_token` | `CharField(64)` | unique — idempotency key |
| `user` | FK → `User` | `PROTECT`, `related_name="orders"` |
| `status` | `CharField(24)` | `OrderStatus`, indexed |
| `payment_status` | `CharField(20)` | `PaymentStatus`, indexed |
| `subtotal`,`shipping_amount`,`discount_amount`,`tax_amount`,`grand_total` | `DecimalField(14,2)` | |
| `currency` | `CharField(3)` | default `NGN` |
| `delivery_address` | FK → `Address` | `PROTECT`, nullable |
| `delivery_*` (`state`,`lga`,`city`, …) | snapshot `CharField` | fulfilment snapshot |
| `shipping_method` | FK → `ShippingMethod` | `SET_NULL`, nullable |
| `contact_name`,`contact_phone` | `CharField` | snapshot |
| `customer_note` | `TextField` | blank |
| `placed_at`,`cancelled_at`,`cancelled_reason` | | |
| `expires_at`,`reservation_released_at`,`stock_committed_at` | DateTime | lifecycle marks |
| timestamps | | |

- Indexes: `(user, -created_at)`, `status`, `payment_status`, `number`.
- Totals are **recomputed server-side** and line prices snapshotted; financial
  fields are never edited after payment.

### 5.6 `OrderItem`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `order` | FK → `Order` | `CASCADE`, `related_name="items"` |
| `listing` | FK → `ProductListing` | `PROTECT` |
| `variant` | FK → `ProductVariant` | `PROTECT`, nullable |
| `product_name`,`product_slug`,`sku` | snapshot | |
| `origin_state`,`origin_lga`,`packaging`,`variant_name` | snapshot | display |
| `quantity` | `DecimalField(14,3)` | |
| `unit_price` | `DecimalField(14,2)` | snapshot |
| `line_total` | `DecimalField(14,2)` | snapshot |
| `fulfilment_status` | `CharField(16)` | `FulfilmentStatus` |

- Snapshots keep historical orders accurate when a listing later changes.

### 5.7 `OrderStatusHistory` (append-only)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `order` | FK → `Order` | `CASCADE`, `related_name="history"` |
| `from_status`,`to_status` | `CharField(24)` | |
| `changed_by` | FK → `User` | `SET_NULL`, nullable |
| `reason` | `TextField` | blank |
| `created_at` | DateTime | indexed |

- `save()` rejects updates and `delete()` always raises — history is immutable.

### 5.8 `Shipment`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `order` | FK → `Order` | `CASCADE`, `related_name="shipments"` |
| `method` | FK → `ShippingMethod` | `SET_NULL`, nullable |
| `carrier`,`tracking_number` | `CharField(120)` | blank |
| `status` | `CharField(16)` | `ShipmentStatus` |
| `notes` | `TextField` | blank |
| `dispatched_at`,`delivered_at` | DateTime | nullable |
| `handled_by` | FK → `User` | `SET_NULL`, nullable |

### 5.9 `QuotationRequest`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `user` | FK → `User` | `SET_NULL`, nullable (guests allowed) |
| `listing` | FK → `ProductListing` | `PROTECT` |
| `variant` | FK → `ProductVariant` | `PROTECT`, nullable |
| `quantity` | `DecimalField(14,3)` | |
| `packaging` | `CharField` | blank |
| `destination_state`,`destination_lga`,`destination_note` | | optional |
| `requirements` | `TextField` | blank |
| `contact_name`,`contact_email`,`contact_phone` | | |
| `status` | `CharField(20)` | `QuotationStatus` |
| `response_note` | `TextField` | blank |
| `reviewed_by` | FK → `User` | `SET_NULL`, nullable |
| `reviewed_at` | DateTime | nullable |
| timestamps | | |

- Bulk pricing/acceptance workflows arrive in the quotations phase; Phase 5
  captures the request and lets staff review/respond.

### 5.10 Status enumerations (`orders`)

```
CartStatus       : active | converted | abandoned
OrderStatus      : pending_payment | payment_review | confirmed | processing
                   | ready_for_dispatch | dispatched | delivered | completed
                   | cancelled | expired | refunded
PaymentStatus    : pending | paid | failed | refunded | partially_refunded
FulfilmentStatus : pending | reserved | packed | dispatched | delivered | cancelled
ReservationStatus: active | committed | released | expired
QuotationStatus  : submitted | reviewing | quoted | accepted | declined | closed
ShipmentStatus   : pending | dispatched | in_transit | delivered | failed
```

### 5.11 Order & inventory state transitions (invariants)

```
pending_payment --review--> payment_review --confirm--> confirmed --process--> processing
     |                          |                          |                        |
     +--cancel/expire--> cancelled/expired                 |                        +--> ready_for_dispatch --dispatch--> dispatched --deliver--> delivered --> completed
                                                           +--cancel (releases)--> cancelled
                                                           +--full refund--> refunded
```

- Stock is **reserved** when an order is created, **committed** (movement `sale`)
  when payment is confirmed, and **released** on cancellation/expiry.
- `pending_payment`/`payment_review` → `confirmed` happens through
  `services.settle_order`, which is called by the audited `confirm_payment`
  (manual, capability `FINANCE_MANAGE`) **and** after a verified Paystack
  capture or a finance-approved bank transfer (Phase 6). Settlement is
  idempotent: re-verification, duplicate webhooks and repeated approvals are
  no-ops.
- Customers may move an order to `payment_review` (by starting a bank transfer)
  but never to paid; only server-side verification can set `payment_status=paid`.
- Every transition writes `OrderStatusHistory` and (where it touches stock) a
  `StockMovement`, inside one transaction.

### 5.12 Phase 6 — payments, refunds, invoices & receipts (implemented)

Phase 6 adds provider payments on top of the Phase 5 order model. All money is
`DecimalField(14,2)`; provider smallest-unit amounts (kobo) exist only at the
`apps.orders.paystack` boundary. Provider rows are UUID-pk.

`CompanyBankAccount` — verified settlement accounts shown to bank-transfer
customers (configured by finance staff only).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `bank_name` | `CharField(120)` | |
| `account_name` | `CharField(150)` | |
| `account_number` | `CharField(34)` | |
| `currency` | `CharField(3)` | default `NGN` |
| `instructions` | `TextField` | blank |
| `sort_order` | `PositiveInteger` | default 0 |
| `is_active` | Bool | indexed |

- Constraint: unique `(bank_name, account_number, currency)`.

`Payment` — one settlement attempt for one order through one provider.

| Field | Type | Notes |
|---|---|---|
| `order` | FK → `Order` | `PROTECT`, `related_name="payments"` |
| `customer` | FK → `User` | `PROTECT`, `related_name="payments"` |
| `reference` | `CharField(80)` | **unique**, internal reference |
| `provider` | `CharField(20)` | `PaymentProvider` |
| `method` | `CharField(20)` | `PaymentMethod`, blank |
| `currency` | `CharField(3)` | default `NGN` |
| `expected_amount` | `DecimalField(14,2)` | authoritative server total |
| `verified_amount` | `DecimalField(14,2)` | nullable; set only after verification |
| `status` | `CharField(20)` | `PaymentState`, indexed |
| `provider_reference` | `CharField(120)` | indexed |
| `channel` | `CharField(40)` | blank |
| `requires_review`,`review_reason` | Bool / `TextField` | manual-review flag |
| `verified_at` | DateTime | nullable |
| `note` | `TextField` | blank |

- Constraints: `expected_amount >= 0`; `verified_amount` null-or-`>= 0`.
- Indexes: `(order, status)`, `(provider, provider_reference)`,
  `(status, requires_review)`.

`PaymentAttempt` — a provider round-trip per initialise/hosted checkout
(`authorization_url`, `access_code`, `PaymentAttemptStatus`).

`PaymentWebhookEvent` — durable provider webhook record used for deduplication
and replay (`event_id`, `event_type`, redacted `payload`, `status`, `attempts`).
Unique `(provider, event_id)`.

`BankTransferSubmission` — a customer's claimed manual transfer, reviewed by
finance (`bank_name_snapshot`, `account_number_snapshot`, `transfer_reference`,
`claimed_amount`, `transfer_date`, `proof`, `status`, `settlement_confirmed`,
`reviewed_by`, `review_notes`).

- Constraints: `claimed_amount >= 0`; **unique approved transfer**
  `(transfer_reference, account_number_snapshot)` where `status=approved`, so a
  single bank transaction can never settle two orders.

`Refund` — a finance-approved reversal against a settled payment.

| Field | Type | Notes |
|---|---|---|
| `payment` | FK → `Payment` | `PROTECT`, `related_name="refunds"` |
| `reference` | `CharField(80)` | unique |
| `amount` | `DecimalField(14,2)` | `> 0` |
| `reason` | `TextField` | blank |
| `status` | `CharField(20)` | `RefundState` |
| `provider_status` | `CharField(20)` | `RefundProviderState` |
| `provider_reference` | `CharField(120)` | unique when non-blank |
| `requested_by`,`approved_by` | FK → `User` | nullable |
| `processed_at` | DateTime | nullable |
| `failure_reason` | `TextField` | blank |

- Constraints: `amount > 0`; unique `provider_reference` when set.

`Invoice` — an issued, immutable per-order invoice with a billing snapshot
(`customer_name`/`customer_email`/`customer_phone`, `billing_address`,
`subtotal`, `shipping_amount`, `discount_amount`, `tax_amount`, `total`,
`status`, `issued_at`, `due_at`, `notes`); `OneToOne` → `Order`, constraint
`total >= 0`. Immutable fields are rejected by `save()` once issued; create a
new/versioned document rather than editing it.

`Receipt` — proof of a **verified** payment (`OneToOne` → `Payment`, `number`,
`amount`, `currency`, `issued_at`, `amount >= 0`); immutable after issue and
issuable only for captured payments.

```
PaymentProvider  : paystack | bank_transfer | manual
PaymentState     : pending | processing | paid | failed | abandoned
                   | cancelled | refunded | partially_refunded
PaymentAttemptStatus : initialized | pending | succeeded | failed | abandoned
WebhookEventStatus   : received | processed | failed | ignored
BankTransferStatus   : submitted | under_review | approved | rejected
RefundState          : requested | approved | processing | completed
                       | failed | rejected
RefundProviderState  : pending | processing | success | failed | reversed
InvoiceState         : unpaid | partially_paid | paid | refunded | void
```

Phase 6 invariants:

- A payment is only marked `paid` after a **server-side** Paystack verify call or
  a signature-verified webhook whose currency and amount match `expected_amount`.
- Webhooks are processed transactionally, row-locked (`select_for_update`) and
  idempotently (`uniq_webhook_event`); duplicates and out-of-order events never
  double-settle, re-commit stock or re-issue a receipt.
- Late payment on an expired/cancelled order records the payment and flags it
  `requires_review` instead of auto-completing the order.
- `review_bank_transfer(approve=True)` requires `settlement_confirmed`, and the
  unique-approved-transfer constraint blocks one transfer settling two orders.
  Uploaded proof alone is never evidence of payment.
- Refunds cannot exceed captured funds; only `FINANCE_MANAGE` staff request,
  approve or complete refunds; a refund completes only when documented.

---

## 6. `services` — consultancy, farming, storage, marketing (Phase 7, delivered)

All four divisions share **one concrete** `ServiceRequest` plus per-division
detail records that hang off it with a `OneToOneField`. Reads live in
`apps/services/selectors.py`; every write goes through
`apps/services/services.py`. Money and quantities are always `Decimal`. Primary
keys are UUIDs. References are human-readable (`AS-SR`, `AS-QT`, `AS-FP`,
`AS-MP`, `AS-MC`, `AS-SB`) and allocated on save.

### 6.1 `ServiceRequest` (shared request record)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `reference` | `CharField(32)` | unique, `AS-SR-YYYYMMDD-XXXXXX` |
| `customer` | FK → `User` | `PROTECT`, `related_name="service_requests"` |
| `service_type` | `CharField(20)` | `ServiceType`: consultancy \| farming \| marketing \| storage |
| `status` | `CharField(20)` | `ServiceRequestStatus`, default `submitted` |
| `priority` | `CharField(10)` | `ServicePriority`: low \| normal \| high \| urgent |
| `title` / `description` | `CharField(160)` / `TextField` | |
| `assigned_to` | FK → `User` | `SET_NULL`, nullable |
| `state` / `lga` | FK → `locations.State` / `LGA` | `PROTECT`, nullable |
| `preferred_date` | Date | nullable |
| `closed_at` | DateTime | set when completed/rejected/cancelled |
| `created_at` / `updated_at` | | |

Indexes: `(service_type, status)`, `(customer, service_type)`. A custom
`ServiceRequestQuerySet` adds `.open()` and `.for_customer(user)`.

### 6.2 Request support tables

| Table | Purpose | Key fields |
|---|---|---|
| `ServiceRequestStatusHistory` | Append-only status transitions | `request`, `from_status`, `to_status`, `actor`, `note`, `created_at` |
| `ServiceAssignment` | Staff assignment to a request | `request`, `staff`, `role`, `is_active`, `note`; unique `(request, staff, role)` |
| `ServiceComment` | Thread comments | `request`, `author`, `body`, `visibility` (`customer` \| `internal`) |
| `ServiceAttachment` | Uploaded file (visibility-controlled) | `request`, `uploaded_by`, `file`, `label`, `content_type`, `size`, `is_customer_visible` |
| `ServiceActivityLog` | Append-only activity trail | `request`, `actor`, `action`, `target_type`, `target_id`, `summary`, `metadata` (JSON) |
| `ServiceNotificationLog` | Notification dedupe ledger | `event`, unique `dedupe_key` |

### 6.3 Consultancy

- `ConsultancyService` — bookable offering: `name`, `slug`, `summary`,
  `duration_minutes`, `supports_online`, `supports_onsite`, `is_active`.
- `Consultant` — `OneToOne` → `User`, plus `specialities`, `bio`, `is_active`.
- `ConsultantAvailability` — `consultant`, either a recurring `weekday`
  (`0=Mon…6=Sun`) or a one-off `specific_date` (exactly one, DB-checked),
  `start_time` < `end_time`, `is_active`.
- `ConsultationAppointment` | `request` (OneToOne → `ServiceRequest`), `service`,
  `consultant`, `mode` (`ConsultationMode`), `scheduled_start`/`scheduled_end`,
  `status` (`AppointmentStatus`), confirmation/rejection/reschedule fields.
- `ConsultationReport` | `appointment` (OneToOne), `summary`,
  `recommendations`, `file`, `recorded_by`.

### 6.4 Farming

- `FarmingService` — a farming service offering.
- `FarmServiceRequest` | `request` (OneToOne), `requested_service`, farm
  location, `farm_size`/`area_unit` (`FarmAreaUnit`), `crop_type`, `season`
  (`FarmingSeason`), expected dates, budget min/max.
- `FarmProject` — `OneToOne` to its request; `status` (`FarmProjectStatus`),
  manager, `approved_by`/`approved_at`, `agreement_reference`, activated/
  completed timestamps. Activation requires approval **and** an agreement.
- `FarmProjectMilestone` (`related_name="milestones"`) — sequence, due date,
  status (`MilestoneStatus`).
- `FarmVisit` — scheduled/actual dates, purpose, status (`VisitStatus`).
- `FarmProgressReport` — `progress_percent` (`CheckConstraint` ≤ 100), file,
  `is_customer_visible`.

### 6.4 Marketing

- `MarketingService` — offering.
- `MarketingEnquiry` — `OneToOne` to the shared request; product type,
  available quantity + unit, location, target market, requirements.
- `MarketingProposal` — narrative (`scope`, `approach`) linked to an enquiry and
  optionally a `ServiceQuotation`; `status` (`MarketingProposalStatus`:
  draft \| issued \| accepted \| rejected).
- `MarketingCampaign` — must follow an accepted proposal; `status`
  (`MarketingCampaignStatus`: planned \| active \| completed \| cancelled), officer.
- `MarketingActivity` — dated activity log entry on a campaign.
- **No third-party seller accounts** are ever created; AA Shinaka remains the
  direct seller.

### 6.5 Storage & warehousing

- `ProduceType` — reference list of accepted produce.
- `StorageFacility` — name, generated `code`, location, `capacity` + unit
  (`StorageCapacityUnit`), accepted produce types (M2M), conditions, active.
- `StorageUnit` — a capacity bay/silo inside a facility; unique `(facility, name)`.
- `StorageServiceRequest` — `OneToOne` to the shared request; produce type,
  quantity + unit, preferred facility/location, requested dates, special handling.
- `StorageBooking` — `OneToOne` to its request; facility/unit, optional
  `quotation`, quantity, `[start_date, end_date)`, `status`
  (`StorageBookingStatus`: requested \| confirmed \| checked_in \| checked_out \|
  completed \| cancelled); CheckConstraints on dates and quantity.
- `StorageCapacityAllocation` — the durable capacity ledger: booking, facility,
  unit, quantity, date range, `released_at`; CheckConstraints for positive
  quantity and ordered dates; index `(facility, start_date, end_date)`.
  Overbooking is prevented in the service layer under `select_for_update`.
- `StorageCheckIn` / `StorageCheckOut` — physical intake/release with quantity
  and condition notes; `StorageInspection` — notes/file/condition.

### 6.6 Reusable quotations

- `ServiceQuotation` — UUID pk, unique `reference` (`AS-QT`), `customer`,
  optional `request`, `currency`, `subtotal`/`tax_amount`/`total`
  (`DecimalField(14,2)`, recomputed server-side), `valid_until`, `terms`,
  `status` (`QuotationStatus`: draft \| pending_approval \| issued \| accepted \|
  rejected \| expired \| cancelled), `revision` + `supersedes` (self-FK),
  approval fields, `issued_at`/`decided_at`, and payment tracking
  (`payment_status` (`QuotationPaymentStatus`), `paid_at`). Accepted quotations
  are frozen — `save()` rejects changes to `_FROZEN_FIELDS`.
- `ServiceQuotationItem` — description, quantity, unit, `unit_price`,
  `line_total`, `sort_order`.
- `orders.Payment` gains an optional `service_quotation` FK with a check
  constraint (`chk_payment_single_target`) so a payment targets exactly one of
  order/quotation. Settlement flows through the Phase 6 verification pipeline
  (`apps.services.payments.settle_quotation_payment`).

### 6.7 Status enumerations (`services`)

```
ServiceType            : consultancy | farming | marketing | storage
ServiceRequestStatus   : submitted | under_review | quoted | confirmed |
                         in_progress | completed | rejected | cancelled
ServicePriority        : low | normal | high | urgent
AppointmentStatus      : requested | confirmed | rescheduled | completed |
                         rejected | cancelled
FarmProjectStatus      : draft | approved | active | on_hold | completed | cancelled
MilestoneStatus        : pending | in_progress | completed | blocked
VisitStatus            : planned | completed | missed | cancelled
MarketingProposalStatus: draft | issued | accepted | rejected
MarketingCampaignStatus: planned | active | completed | cancelled
StorageBookingStatus   : requested | confirmed | checked_in | checked_out |
                         completed | cancelled
QuotationStatus        : draft | pending_approval | issued | accepted |
                         rejected | expired | cancelled
QuotationPaymentStatus : unpaid | paid
```

`REQUEST_TRANSITIONS` declares the legal shared-request moves; a request acted
on straight from `submitted` is implicitly reviewed first so history reflects the
pipeline.

---

## 6a. `export` — agricultural export & international trade (Phase 8, delivered)

The dedicated `apps/export` app (kept separate from `catalog`/`orders`, matching
the domain-oriented layout). Reads live in `apps/export/selectors.py`; **every
write goes through `apps/export/services.py`**. Money and quantities are always
`Decimal`; primary keys are UUIDs (local `UUIDTimeStampedModel`, references via
`generate_reference`). Cross-app foreign keys use string references
(`catalog.*`, `locations.*`, `settings.AUTH_USER_MODEL`, `export.*`).

### 6a.1 Destination & product configuration

- `ExportDestination` — one per `locations.Country` (unique). `approval_status`
  (`ApprovalStatus`: pending/approved/rejected) and `is_active` are **separate**:
  a destination must be approved *and* activated (`EXPORT_APPROVE`) before it is
  selectable. Carries `notes`, `source`, `approved_by`/`approved_at`,
  `activated_at`. `country_code`/`country_name` are convenience properties.
- `ExportDestinationRequirement` — `RequirementType`, optional `product`/
  `category` narrow the scope; `is_active`, description, source/provenance.
- `ExportTradeRestriction` — `RestrictionType` (prohibited/restricted); optional
  `product`/`category` scope. `selectors.active_restriction_for` prefers a
  product-specific restriction over a category-wide one.
- `ExportDocumentRequirement` — ties an `ExportDocumentType` to a destination
  (optional product/category scope) and drives checklist generation.
- `ExportProductProfile` — `OneToOneField(catalog.Product)` (**no duplication**):
  `is_export_eligible`, `export_grade`, packaging, `min_export_quantity` +
  unit, specifications (`JSONField`), `export_availability`, inspection flags,
  and an `allowed_destinations` M2M (positive allow-list). `allows_destination()`
  combines the allow-list with active trade restrictions.

### 6a.2 Enquiries, quotations & orders

- `ExportEnquiry` — `reference` (`AS-EXQ`), `customer`, `destination`,
  `origin_state`/`origin_lga`, `delivery_destination`, shipping mode, requested
  period/date, `priority`, `status` (`ExportEnquiryStatus`), `closed_at`.
  `ExportEnquiryItem` (product/listing, quantity, unit, packaging);
  `ExportEnquiryStatusHistory` (append-only; `from_status`/`to_status`/actor/note).
- `ExportQuotation` — `reference`, `enquiry`, `customer`, `destination`, `status`
  (`ExportQuotationStatus`), `currency`, **`incoterm` + `incoterm_version`
  (Incoterms 2020) + `named_place`**, payment and delivery terms,
  `deposit_percentage`, `exchange_rate_reference`, `valid_until`, server-computed
  `subtotal`/`total`, approval/issue audit fields. `ExportQuotationItem`
  (product/listing, quantity, unit, `unit_price`, `charge_type` =
  product/freight/insurance/other, `line_total`). `ExportQuotationRevision`
  snapshots a quotation before it is revised; the previous revision is
  superseded. An accepted quotation is **frozen**.
- `ExportOrder` — `reference` (`AS-EXO`), `customer`, `destination`,
  `OneToOneField(ExportQuotation)`, `status` (`ExportOrderStatus`), `currency`
  (default `USD`), the frozen Incoterms/terms, `commercial_terms` (`JSONField`
  snapshot), `compliance_status`, `fulfillment_status`, `total`/`deposit_amount`/
  `balance_amount`/`amount_paid`, assignee, lifecycle timestamps. Constraints:
  `total >= 0`, `amount_paid >= 0`; index on `(status, destination)`.
  `is_compliance_cleared`, `is_fully_paid`, `balance_due` derived.
  `ExportOrderItem` copies product/listing/description/quantity/unit/unit_price
  and origin from the quotation. `ExportOrderStatusHistory` is append-only.

### 6a.3 Compliance, documents & shipments

- `ExportDocumentType` — configurable registry; `requires_expiry` means an
  official type must carry an expiry date. Seeded by `0002_seed_document_types`.
- `ExportDocument` — `order`, `document_type`, `file` (private storage),
  issuing org/reference, issue/expiry dates, `verification_status`
  (`DocumentVerificationStatus`), `is_customer_visible`. `ExportDocumentReview`
  records each review decision (`DocumentReviewDecision`).
- `ExportComplianceChecklist` — one per order; `status`
  (`ComplianceStatus`/`ComplianceChecklistStatus`), generated from the
  destination's document requirements. `ExportComplianceChecklistItem` —
  requirement, `status` (`ComplianceItemStatus`), linked document, notes.
- `LogisticsProvider` — freight-forwarding provider records. `ExportShipment` —
  `reference`, `order`, provider, mode (`ShippingMode`), carrier/booking,
  departure/arrival, `status` (`ShipmentStatus`). `ExportShipmentItem` mirrors the
  order items. `ShipmentMilestone` — **staff-entered only**
  (`is_staff_entered=True`, `recorded_by`), never fabricated live tracking.

### 6a.4 Settlement (`orders`)

`orders.Payment.export_order` (nullable FK, `related_name="payments"`) is a third
payment target alongside shop `order` and `service_quotation`; the
`chk_payment_single_target` check constraint enforces exactly one target. Export
payments reuse the Phase 6 verification pipeline — the **browser callback is
never trusted**; `apps/export/payments.py` settles only on a server-verified
payment and calls `services.record_verified_payment` (a trusted, system actor).
The settlement path uses the internal `_advance_export_order` helper, which is
not capability-gated; staff-driven order transitions use the gated
`transition_export_order`.

### 6a.5 Status enumerations (`export`)

```
ApprovalStatus             : pending | approved | rejected
ExportAvailability         : unavailable | limited | available
ExportEnquiryStatus        : submitted | under_review | requirements_requested |
                             quoted | converted | rejected | cancelled
ExportQuotationStatus      : draft | pending_approval | issued | accepted |
                             rejected | expired | superseded
ExportOrderStatus          : pending_payment | payment_verified | in_production |
                             ready_for_shipment | shipped | delivered |
                             completed | cancelled
Incoterm                   : EXW | FCA | FAS | FOB | CFR | CIF | CPT | CIP | DAP | DPU | DDP
ShippingMode               : sea | air | road | multimodal
ComplianceStatus           : pending | in_review | cleared | blocked
DocumentVerificationStatus : submitted | under_review | verified | rejected | expired
ShipmentStatus             : planned | booked | dispatched | in_transit |
                             customs_processing | arrived | delivered | cancelled
```

`EXPORT_ENQUIRY_TRANSITIONS`, `EXPORT_ORDER_TRANSITIONS` and
`SHIPMENT_TRANSITIONS` declare the legal moves. Reaching
`ready_for_shipment`/`shipped` (order) or `dispatched` (shipment) is blocked
until the order's compliance checklist is approved.

## 6b. `training` — training academy (Phase 9, delivered)

The dedicated `apps.training` app (kept separate from `catalog`/`orders`,
matching the domain-oriented layout). Reads live in `apps/training/selectors.py`;
writes live in `apps/training/services.py`. Course payment reuses the Phase 6
pipeline through `orders.Payment.training_enrollment`; certificates are rendered
with the dependency-free `apps/orders/documents` PDF helper. Primary keys are
UUIDs; money is `Decimal`. Nothing is hardcoded — categories, courses, cohorts,
instructors, venues, fees and capacities are records.

### 6b.1 Catalogue

- `TrainingCategory` — configurable and self-nesting (`parent`), `is_active`;
  never a hardcoded list. `SluggedMixin` (slug from `name`).
- `Course` — category, `title`/`slug`, summary/description and objectives,
  `delivery_mode`, duration, fee, cover image, `status` (`CourseStatus`),
  `certificate_eligible`, published timestamp. Enrolment is via a cohort.
- `CourseModule` (ordered) → `CourseLesson` (ordered, unique per module;
  `lesson_type`, `is_preview`, estimated minutes, optional media/content).
- `CourseResource` — a private document/link attached to a course or a lesson.

### 6b.2 Instructors, venues & cohorts

- `InstructorProfile` (one per user) and `InstructorAssignment` (course and/or
  session, role, active window).
- `TrainingVenue`; `TrainingSession` (cohort) with `status` (`SessionStatus`),
  capacity, fee, start/end, enrolment deadline, venue and instructor;
  `TrainingSessionSchedule` for dated topic lines.

### 6b.3 Enrolment & attendance

- `Enrollment` — `reference`, student, session, `status` (`EnrollmentStatus`),
  payment fields (`amount_paid`, `payment_status`,
  `settled_payment_references`), confirmed/completed timestamps and a derived
  `balance_due`. Capacity is enforced transactionally; a full cohort yields
  `WAITLISTED`. `EnrollmentRequirement` and `EnrollmentStatusHistory`
  (append-only).
- `AttendanceSession` (one per cohort per date, optional schedule entry) and
  `AttendanceRecord` (one per enrolment, status `AttendanceStatus`).

### 6b.4 Assessments, progress & certificates

- `Assessment` (type, max attempts, pass mark, completion-required flag,
  published) → `AssessmentQuestion` → `AssessmentOption`. Learner attempts are
  `AssessmentSubmission` (answers JSON) + `AssessmentResult` (score, pass,
  grader). Objective questions auto-grade; written answers are graded by staff.
- `LessonProgress` and `CourseProgress`; completion is **derived** from real
  records (all lessons complete **and** all published completion-required
  assessments passed), never assumed.
- `CertificateTemplate` and `Certificate` (student, course, session, issued by,
  status) plus `CertificateVerificationLog` for public look-ups.

### 6b.5 Settlement (`orders`)

`orders.Payment.training_enrollment` (nullable FK) is a fourth payment target
alongside shop `order`, `service_quotation` and `export_order`; the
`chk_payment_single_target` check constraint enforces exactly one target.
`apps.training.payments.settle_training_payment` is invoked only from the Phase 6
**verified** branch — the browser callback is never trusted. It calls the
idempotent `services.settle_enrollment_payment` (keyed on
`settled_payment_references`), applies the verified amount, and confirms the
enrolment once the required fee is met.

### 6b.6 Status enumerations (`training`)

```
CourseStatus           : draft | published | archived
DeliveryMode           : in_person | online | hybrid | self_paced
LessonType             : text | document | video | activity
ResourceType           : document | video | link | image | other
SessionStatus          : draft | scheduled | enrollment_open | enrollment_closed |
                         in_progress | completed | cancelled
EnrollmentStatus       : pending | payment_pending | confirmed | waitlisted |
                         cancelled | completed
EnrollmentPaymentStatus: not_required | pending | paid | partially_paid |
                         refunded | failed
AttendanceStatus       : present | absent | late | excused
AssessmentType         : quiz | assignment | practical | exam
QuestionType           : multiple_choice | true_false | short_answer
SubmissionStatus       : draft | submitted | graded | returned
CertificateStatus      : issued | revoked
```

`COURSE_TRANSITIONS`, `SESSION_TRANSITIONS` and `ENROLLMENT_TRANSITIONS` declare
the legal moves; enrolment completion is terminal.

---

## 6c. `notifications` — unified notification centre (Phase 10, delivered)

> Delivered in the dedicated `apps.notifications` app (migration
> `notifications.0001_initial`, generated/applied). Primary keys are UUIDs.

### 6c.1 `Notification`

One in-app notification for one recipient, created **synchronously inside the
same transaction as the business event** (so it rolls back with it) and
idempotent on `dedupe_key`.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `recipient` | FK → `User` | `CASCADE`, `related_name="notifications"` |
| `category` | `CharField(20)` | `NotificationCategory`, indexed |
| `event` | `CharField(80)` | indexed; stable event key e.g. `order.created` |
| `title` / `message` | `CharField(200)` / `TextField` | |
| `url` | `CharField(300)` | safe, same-site relative link only (`services.safe_url`) |
| `reference_type` / `reference_id` | `CharField(60/64)` | soft link to the domain object |
| `dedupe_key` | `CharField(180)` | **unique**; retried events never duplicate |
| `is_read` | `Bool` | indexed |
| `read_at` | `DateTime` | null |
| `created_at` | `DateTime` | `auto_now_add`, indexed |

Indexes: `(recipient, -created_at)`, `(recipient, is_read, -created_at)`,
`(recipient, category, -created_at)`.

### 6c.2 `NotificationPreference`

Per-user channel toggles and per-category opt-outs (one-to-one with `User`).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `user` | OneToOne → `User` | `CASCADE`, `related_name="notification_preference"` |
| `in_app_enabled` / `email_enabled` | `Bool` | default `True` |
| `sms_enabled` / `whatsapp_enabled` | `Bool` | default `False` (inert until a provider is configured) |
| `categories` | `JSONField` | `{category: bool}`, all enabled by default |
| `created_at` / `updated_at` | `DateTime` | |

### 6c.3 `NotificationDelivery`

An audit-grade ledger of one delivery attempt per `(notification, channel)`.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `notification` | FK → `Notification` | `CASCADE`, `related_name="deliveries"` |
| `channel` | `CharField(20)` | `NotificationChannel` |
| `status` | `CharField(16)` | `pending \| delivered \| skipped \| failed` |
| `attempt_count` | `PositiveSmallInt` | default 0 |
| `last_attempt_at` / `delivered_at` | `DateTime` | null |
| `provider_reference` | `CharField(200)` | optional provider id |
| `error_detail` | `TextField` | last error (never secrets) |
| `created_at` / `updated_at` | `DateTime` | |

Constraint `uniq_notification_channel` (`notification`, `channel`).

**Enumerations:** `NotificationCategory` (`orders`, `payments`, `export`,
`services`, `training`, `support`, `account`, `general`);
`NotificationChannel` (`in_app`, `email`, `sms`, `whatsapp`);
`NotificationDeliveryStatus` (`pending`, `delivered`, `skipped`, `failed`).

---

## 6d. `support` — customer support centre (Phase 10, delivered)

> Delivered in the dedicated `apps.support` app (migration
> `support.0001_initial`). `SupportTicket`/`SupportMessage`/`SupportAttachment`
> use `core.UUIDTimeStampedModel`; `SupportStatusHistory` has a UUID PK and
> `created_at` only (append-only).

### 6d.1 `SupportTicket`

| Field | Type | Notes |
|---|---|---|
| `reference` | `CharField(32)` | **unique**, `AS-ST-…`, generated on save |
| `customer` | FK → `User` | `CASCADE`, `related_name="support_tickets"` |
| `subject` | `CharField(200)` | |
| `category` | `CharField(32)` | `SupportCategory` |
| `priority` | `CharField(16)` | `SupportPriority`, default `normal` |
| `status` | `CharField(24)` | `SupportStatus`, indexed, default `open` |
| `related_type` / `related_id` | `CharField(40/64)` | optional soft link to an owned order/payment/enquiry/request/enrolment |
| `assigned_to` | FK → `User` | null, `SET_NULL`, `related_name="assigned_support_tickets"` |
| `resolved_at` / `closed_at` / `reopened_at` | `DateTime` | null |
| `last_activity_at` | `DateTime` | indexed (queue ordering) |
| `created_at` / `updated_at` | `DateTime` | |

Index `(customer, -last_activity_at)`.

### 6d.2 `SupportMessage`, `SupportAttachment`, `SupportStatusHistory`

- `SupportMessage` — `ticket` FK, `sender` FK (`SET_NULL`), `message`,
  `is_internal` (internal notes never reach the customer and never notify).
  Ordered oldest-first.
- `SupportAttachment` — `ticket` FK, optional `message` FK, private
  `file` (`support_attachments/%Y/%m/`), `original_filename`, `uploaded_by`.
  Validated by `support.validators` (allow-list + 10 MB cap).
- `SupportStatusHistory` — append-only `previous_status`/`new_status`,
  `changed_by`, `reason`, `created_at`.

**Enumerations:** `SupportCategory`, `SupportPriority`
(`low|normal|high|urgent`), `SupportStatus` (`open | assigned | in_progress |
waiting_for_customer | resolved | closed | reopened`), `SupportRelatedType`.
`SUPPORT_TRANSITIONS` declares the legal status moves; `REOPEN_WINDOW_DAYS = 30`
bounds reopening.

---

## 7. `dashboard` — audit, reporting, tasks

### 7.1 `AuditLog` (implemented, Phase 2)

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `actor` | FK → `User` | `SET_NULL`, nullable (system actions) |
| `action` | `CharField(60)` | indexed, e.g. `staff.create`, `role.assign` |
| `target_type` | `CharField(60)` | blank |
| `target_id` | `CharField(64)` | blank (PK as string) |
| `before` / `after` | `JSONField` | nullable, redacted change summary |
| `note` | `TextField` | blank |
| `ip_address` | `GenericIPAddressField` | nullable |
| `user_agent` | `CharField(300)` | blank |
| `created_at` | DateTime | indexed |

- **Append-only:** `save()` on an existing row and `delete()` raise `ValueError`;
  writes go only through `core.audit.record_audit`, inside the service
  transaction. The admin is read-only.
- Indexes: `(target_type, target_id)` → `audit_target_idx`;
  `(actor, -created_at)` → `audit_actor_idx`.
- Never records passwords, tokens or secrets.

### 7.2 Reporting artefacts moved to `apps.analytics` (Phase 11)

> **Superseded.** The reporting models drafted here as `dashboard.ReportExport` /
> `SavedReport` were delivered in the new **`apps.analytics`** app as
> `ReportExport`, `ScheduledReport`, `ReportExecution` and `ReportDelivery` (see
> §7b below). There is no `dashboard.ReportExport` or `dashboard.SavedReport`; a
> `SavedReport` (saved ad-hoc report definitions) was **not** built — scheduled
> reports cover the recurring-report need.

---

## 7b. `analytics` — reporting artefacts (Phase 11)

Analytics is **read-only** against the business domain: these four models only
record reporting artefacts (generated files, schedules, executions, deliveries)
and never store business figures of their own — every number is derived from the
authoritative source models at request time. Primary keys are UUIDs.

### 7b.1 `ReportExport`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `reference` | `CharField(32)` | unique, indexed, `AS-RPT-…`, generated |
| `report_key` | `CharField(64)` | indexed, allow-listed key |
| `export_format` | `CharField(8)` | `csv` / `xlsx` / `pdf` |
| `filters` | `JSONField` | validated, allow-listed filter snapshot |
| `currency` | `CharField(3)` | blank |
| `requested_by` | FK → `User` | `SET_NULL`, nullable |
| `status` | `CharField(12)` | `pending` / `running` / `succeeded` / `failed` / `expired` |
| `is_financial` | Bool | indexed; requires `analytics.finance` to download |
| `row_count` | `PositiveIntegerField` | |
| `file` | `FileField` | private, `analytics_reports/%Y/%m/` |
| `error` | `TextField` | blank |
| `generated_at` / `expires_at` | DateTime | `expires_at` indexed (retention) |
| `created_at` / `updated_at` | DateTime | |

- Indexes: `rpt_export_key_idx` (`report_key`, `-created_at`),
  `rpt_export_user_idx` (`requested_by`, `-created_at`).
- Files are served **only** through the permission-checked download view.

### 7b.2 `ScheduledReport`

`name`, `report_key` (indexed), `filters` `JSONField`, `frequency`
(`daily`/`weekly`/`monthly`), `export_format`, `recipients` M2M → `User`,
`is_enabled` (indexed), `next_run_at` (indexed), `last_run_at`, `created_by` FK,
timestamps.

### 7b.3 `ReportExecution`

`scheduled_report` FK (`SET_NULL`, nullable), `report_key`, `filters`,
`period_key` (indexed), `triggered_by`, `export` FK (`SET_NULL`), `triggered_by_user`
FK, `row_count`, `status`, `error`, `started_at`/`finished_at`, timestamps.

- Constraint `uniq_schedule_period_execution`: unique `(scheduled_report,
  period_key)` where `period_key <> ''` — **at most one run per period** (races
  also caught via `IntegrityError`).
- Index `rpt_exec_idx` (`status`, `-created_at`).

### 7b.4 `ReportDelivery`

`execution` FK (cascade), `recipient` FK (`SET_NULL`, nullable), `email`,
`status` (`pending`/`sent`/`failed`/`skipped`), `error`, `sent_at`, `created_at`.

- A recipient who no longer holds the report's capability is recorded `skipped`
  and never emailed.

---

## 8. Cross-cutting database rules

### 8.1 Indexing strategy
- Every FK used in list/filter joins gets an index (PostgreSQL does not create
  them automatically).
- Composite indexes match the dominant list query:
  `Listing(state, lga, status)`, `Order(user, -created_at)`,
  `Notification(user, is_read, -created_at)`.
- Status columns that drive queues are indexed.
- Slug/uniqueness columns are unique indexes.

### 8.2 Constraints
- Uniqueness: email, state code/name, lga per state, category slug,
  listing origin+package, cart item, enrollment, `Payment.reference`,
  `Invoice.number`, `Receipt.number`, `Refund.reference`, company bank account,
  `PaymentWebhookEvent(provider, event_id)` and an approved
  `BankTransferSubmission(transfer_reference, account_number_snapshot)`.
- CheckConstraints: non-negative money and stock; `stock_reserved <=
  stock_on_hand`; `selling_price >= 0`; Phase 6 adds `Payment.expected_amount
  >= 0`, `Payment.verified_amount >= 0`, `Invoice.total >= 0`,
  `Receipt.amount >= 0`, `Refund.amount > 0` and `BankTransferSubmission.claimed_amount
  >= 0`.
- Refunds never exceed captured funds: `refund.amount <= payment.settled_amount`
  is enforced in the service layer (inside a row-locked transaction), because it
  is a multi-row, cumulative rule rather than a single-table check.

### 8.3 Money
- All money is `DecimalField(14, 2)`. Quantities may use `DecimalField(14, 3)`.
- No `FloatField` for money anywhere. Comparisons/aggregations stay in `Decimal`.

### 8.4 Soft deletion / archival policy

| Data | Policy |
|---|---|
| Users | `is_active=False` (deactivate); never hard-deleted |
| Categories, Products, Listings | Soft delete (`is_deleted`); `PROTECT` prevents orphaning orders |
| Orders, Payments, Refunds, StockMovements | **Never deleted**; immutable financial/audit record |
| Service requests | Soft delete |
| Locations (State/LGA) | `PROTECT`; deactivate via `is_active`, never delete while referenced |
| Audit logs | Append-only |
| Carts/CartItems | Hard delete allowed (transient) |

### 8.5 Transactions
- Order creation, stock reservation/deduction, payment confirmation, refund
  processing and role changes run inside `transaction.atomic()` with
  `select_for_update()` on the affected listings.

### 8.6 Migration policy
- Migrations are generated with `makemigrations` and reviewed; no manual table
  edits. `makemigrations --check` must report no missing migrations in CI.
- Data migrations are separate from schema migrations.

---

## 9. Entity relationships (summary)

```
User 1─* Address
User 1─1 Cart 1─* CartItem *─1 ProductListing
User 1─* Order 1─* OrderItem *─1 ProductListing
Order 1─* Payment 1─* Refund
Order 1─* OrderStatusHistory
ProductListing *─1 Product *─1 Category (self-nesting)
ProductListing 1─* StockMovement
ProductListing *─1 State, LGA
ProductListing 1─* ListingPrice 1─* PriceHistory
ProductListing 1─* WholesalePriceTier, ProductListing 1─* ProductVariant
Product 1─* ProductImage, Product *─1 UnitOfMeasure
Product 1─* MarketReferencePrice *─1 State (nullable)
Country 1─* State 1─* LGA 1─* City
User 1─* ServiceRequest (Consultancy/Farming/Marketing/Storage)
StorageRequest 1─* StorageRecord
ServiceQuotation 1─* ServiceQuotationItem

# export (Phase 8, implemented)
User 1─* ExportEnquiry 1─* ExportEnquiryItem | ExportEnquiryStatusHistory
Country 1─1 ExportDestination 1─* ExportDestinationRequirement
        ExportDestination 1─* ExportTradeRestriction | ExportDocumentRequirement
ExportProductProfile 1─1 Product (extends the catalogue, no duplication)
ExportQuotation 1─* ExportQuotationItem; ExportQuotation 1─* ExportQuotationRevision
ExportQuotation 1─1 ExportOrder (terms frozen from the accepted quotation)
ExportOrder 1─* ExportOrderItem | ExportOrderStatusHistory | ExportDocument | ExportShipment
ExportOrder 1─1 ExportComplianceChecklist 1─* ExportComplianceChecklistItem
ShipmentMilestone *─1 ExportShipment (staff-entered only)
Order 1─* Payment | ServiceQuotation 1─* Payment | ExportOrder 1─* Payment |
Enrollment 1─* Payment
        (chk_payment_single_target: exactly one target)

# notifications (Phase 10, delivered)
User 1─* Notification 1─* NotificationDelivery
User 1─1 NotificationPreference

# support (Phase 10, delivered)
User 1─* SupportTicket 1─* SupportMessage | SupportAttachment | SupportStatusHistory

# training (Phase 9, delivered)
TrainingCategory 1─* TrainingCategory (self-nesting) 1─* Course
Course 1─* CourseModule 1─* CourseLesson; CourseLesson *─1 CourseModule
CourseResource *─1 Course | CourseLesson
InstructorProfile 1─1 User; InstructorAssignment *─1 InstructorProfile, Course, TrainingSession
TrainingVenue 1─* TrainingSession; Course 1─* TrainingSession
TrainingSession 1─* TrainingSessionSchedule | Enrollment | AttendanceSession
Enrollment 1─* EnrollmentRequirement | EnrollmentStatusHistory;
Enrollment 1─1 AttendanceRecord *─1 AttendanceSession
Course 1─* Assessment 1─* AssessmentQuestion 1─* AssessmentOption
AssessmentSubmission *─1 Enrollment, Assessment; AssessmentResult 1─1 AssessmentSubmission
LessonProgress *─1 Enrollment, CourseLesson; CourseProgress 1─1 Enrollment
Certificate *─1 Student, Course, TrainingSession; CertificateTemplate 1─* Certificate
CertificateVerificationLog *─1 Certificate

User 1─* Notification
User 1─* AuditLog

# cms (Phase 3, implemented)
SiteSetting 1─1 (singleton, pk=1)
MediaAsset 1─* HeroBanner | BusinessDivision | ServicePage | Page | BlogPost | Testimonial | TeamMember
BusinessDivision 1─* ServicePage 1─* ServiceCategory
ServicePage 1─* FAQ
BlogPost *─1 BlogCategory
User 1─* BlogPost (author), MediaAsset (uploaded_by), Testimonial (approved_by), ContactEnquiry (handled_by)
NavigationItem *─1 Page, NavigationItem self-nesting (parent/children)
```

---

## 10. `cms` — content management (Phase 3, implemented)

The public website is fully CMS-driven. These tables already exist (migration
`cms.0001_initial`). They are **live now**, unlike the catalogue/order/service
sections above which ship in later phases.

### 10.1 Shared abstract bases
- `SluggedModel` — auto-fills `slug` from a source field (`title`) with
  collision suffix (`foo`, `foo-2`, …); slug unique per model.
- `SEOModel` — `meta_title`, `meta_description`, `canonical_url`, `og_image`
  (FK→`MediaAsset`), `noindex`.
- `PublishableModel(SluggedModel, SEOModel)` — `status`
  (`PublishStatus`: `draft | published | archived`, indexed), `published_at`,
  `is_featured`, `sort_order`. `ContentQuerySet.published()` requires
  `status=published` AND (`published_at IS NULL` OR `published_at <= now`).

### 10.2 Concrete tables

| Table | Key fields / notes |
|---|---|
| `cms_mediaasset` | UUID pk; `file` (ImageField, 5 MB + extension validators), `title`, `alt_text`, `uploaded_by` FK→User |
| `cms_sitesetting` | Singleton (pk=1 via `load()`); site name/tagline/description, announcement, phone(s), `whatsapp_number`, email, address fields + `state` FK, `map_embed_url`, social URLs, `logo`/`favicon` FK→MediaAsset, `default_meta_title`/`default_meta_description`, `value_props` (JSON) |
| `cms_navigationitem` | `label`, `url_name`/`url`/`page` (one target), `placement` (`header|footer`), `parent` (self FK), `sort_order`, `is_active`, `opens_new_tab` |
| `cms_page` | `page_type` (`about|contact|terms|privacy|custom`), `title`, `summary`, `body`, `hero_image`; + Publishable/SEO |
| `cms_herobanner` | `title`, `eyebrow`, `subtitle`, CTA label/url (+secondary), `image`; + Publishable/SEO |
| `cms_businessdivision` | `name`, `short_description`, `description`, `icon`, `image`; + Publishable/SEO. Linked to canonical `core.constants.BusinessDivision` values in templates |
| `cms_servicepage` | `division` FK (nullable), `title`, `eyebrow`, `intro`, `body`, `hero_image`, `icon`, `benefits` (JSON list), `steps` (JSON list), `cta_label`/`cta_url`; + Publishable/SEO |
| `cms_servicecategory` | `service_page` FK, `name`, `description`, `icon`, `sort_order` (inline on the service form) |
| `cms_faq` | `question`, `answer`, `service_page` FK (nullable → general), `sort_order`, `is_published` |
| `cms_testimonial` | `author_name`, `author_role`, `company`, `quote`, `image`, `rating` (1–5), `is_approved`, `is_featured`, `approved_by`/`approved_at` |
| `cms_teammember` | `name`, `role_title`, `bio`, `photo`, `sort_order`, `is_active` |
| `cms_blogcategory` | `name`, `slug` (unique), `description` |
| `cms_blogpost` | `title`, `category` FK, `author` FK, `excerpt`, `body`, `featured_image`, `reading_minutes`; + Publishable/SEO |
| `cms_contactenquiry` | `name`, `email`, `phone`, `subject`, `division` (canonical value or blank), `message`, `is_handled`, `handled_by`/`handled_at`, `ip_address`, `user_agent` |

### 10.3 CMS notes
- Drafts/archived never leak publicly: all public selectors use `.published()`.
- Testimonials require staff approval (`is_approved`) before appearing on the
  homepage; approval is audited (`cms.testimonial.approved`).
- Contact submissions are stored (never emailed in Phase 3) and rate-limited;
  a honeypot field blocks bots. Only canonical division values are persisted.
- `SiteSetting` is a singleton; it is created on first access.
- Media uploads are validated (allowed extensions + 5 MB limit) before saving.

### 10.4 Catalog linkage (Phase 4, delivered)
The homepage product/category/state previews read from `apps.catalog`
(`Category`, `ProductListing`) through the `cms` selectors (`featured_products`,
`shop_by_state`) and the `product_categories` tag. No `cms` model changes were
needed, and the previews still degrade to empty states when the catalogue is
empty. Only *sellable* listings (active listing + published product + available
stock) are ever surfaced publicly.

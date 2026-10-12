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

## 3. `accounts` — users, addresses, notifications

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

### 3.3 `Notification` (planned, Phase 9)

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `user` | FK → `User` | `CASCADE`, `related_name="notifications"` |
| `kind` | `CharField(32)` | `TextChoices` |
| `title`,`body` | `CharField(200)` / `TextField` | |
| `url` | `CharField(500)` | optional deep link |
| `is_read` | `BooleanField` | indexed |
| `created_at` | DateTime | indexed |
| `read_at` | DateTime | nullable |

- Index: `(user, is_read, -created_at)`.

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
| `id` | UUID | PK |
| `listing` | FK → `ProductListing` | `PROTECT`, `related_name="movements"` |
| `kind` | `CharField(16)` | `StockMovementKind` (`intake`,`adjustment`,`sale`,`return`,`damage`,`transfer`) |
| `quantity_delta` | `DecimalField(14,3)` | signed |
| `balance_after` | `DecimalField(14,3)` | snapshot |
| `reference` | `CharField(100)` | order no. / note |
| `actor` | FK → `User` | `SET_NULL`, nullable |
| `note` | `TextField` | blank |
| `created_at` | DateTime | indexed |

- Index: `(listing, -created_at)`.
- **Append-only**: movements are never edited or deleted; `adjust_stock()` takes
  a row lock, applies the delta, refuses to go negative and writes a movement in
  one transaction.

### 4.7 Status enumerations (`catalog`)

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

## 5. `orders` — cart, orders, payments, refunds

### 5.1 `Cart`

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `user` | OneToOne → `User` | `CASCADE` (persistent cart) |
| `created_at`,`updated_at` | | |

### 5.2 `CartItem`

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `cart` | FK → `Cart` | `CASCADE`, `related_name="items"` |
| `listing` | FK → `ProductListing` | `CASCADE` |
| `quantity` | `DecimalField(14,3)` | > 0 |
| `unit_price_snapshot` | `DecimalField(14,2)` | price at add time |
| timestamps | | |

- Constraint: `UniqueConstraint(cart, listing)`.

### 5.3 `Order`

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `number` | `CharField(20)` | unique, human-readable |
| `user` | FK → `User` | `PROTECT`, `related_name="orders"` |
| `status` | `CharField(20)` | `OrderStatus`, indexed |
| `payment_status` | `CharField(20)` | `PaymentStatus`, indexed |
| `subtotal` | `DecimalField(14,2)` | |
| `delivery_fee` | `DecimalField(14,2)` | default 0.00 |
| `tax_amount` | `DecimalField(14,2)` | default 0.00 |
| `total` | `DecimalField(14,2)` | |
| `currency` | `CharField(3)` | default `NGN` |
| `delivery_address` | FK → `Address` | `PROTECT`, nullable |
| `contact_name`,`contact_phone` | `CharField` | snapshot for fulfilment |
| `customer_note` | `TextField` | blank |
| `placed_at` | DateTime | nullable |
| `cancelled_at` | DateTime | nullable |
| `is_deleted`,`deleted_at` | soft delete | |
| timestamps | | |

- Indexes: `(user, -created_at)`, `status`, `payment_status`, `number`.
- Immutability: financial fields are not edited after payment; corrections use
  refunds/adjustments.

### 5.4 `OrderItem`

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `order` | FK → `Order` | `CASCADE`, `related_name="items"` |
| `listing` | FK → `ProductListing` | `PROTECT` |
| `product_name` | `CharField(180)` | snapshot |
| `origin_state`,`origin_lga` | `CharField` | snapshot (display) |
| `package_size`,`package_unit` | snapshot | |
| `quantity` | `DecimalField(14,3)` | |
| `unit_price` | `DecimalField(14,2)` | snapshot |
| `line_total` | `DecimalField(14,2)` | |
| `fulfilment_status` | `CharField(16)` | `FulfilmentStatus` |

- Snapshots ensure historical orders remain accurate if a listing changes.

### 5.5 `OrderStatusHistory`

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `order` | FK → `Order` | `CASCADE`, `related_name="history"` |
| `from_status`,`to_status` | `CharField(20)` | |
| `changed_by` | FK → `User` | `SET_NULL` |
| `note` | `TextField` | |
| `created_at` | DateTime | indexed |

### 5.6 `Payment`

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `order` | FK → `Order` | `PROTECT`, `related_name="payments"` |
| `provider` | `CharField(20)` | `paystack` (later phases) |
| `reference` | `CharField(100)` | unique per provider |
| `provider_reference` | `CharField(100)` | blank |
| `amount` | `DecimalField(14,2)` | |
| `currency` | `CharField(3)` | |
| `status` | `CharField(20)` | `PaymentStatus`, indexed |
| `raw_payload` | `JSONField` | stored callback/webhook body |
| `verified_at` | DateTime | nullable |
| `created_at`,`updated_at` | | |

- Constraint: `UniqueConstraint(provider, reference)`.
- Webhooks are verified by signature then applied idempotently.

### 5.7 `Refund`

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `payment` | FK → `Payment` | `PROTECT`, `related_name="refunds"` |
| `amount` | `DecimalField(14,2)` | ≤ payment amount |
| `reason` | `TextField` | |
| `status` | `CharField(16)` | `RefundStatus` |
| `requested_by` | FK → `User` | `SET_NULL` |
| `approved_by` | FK → `User` | `SET_NULL`, nullable |
| `provider_reference` | `CharField(100)` | |
| `created_at`,`approved_at` | | |

### 5.8 Status enumerations (`orders`)

```
OrderStatus      : pending_payment | paid | processing | dispatched | delivered | completed | cancelled | refunded
PaymentStatus    : pending | authorized | paid | failed | refunded | partially_refunded
FulfilmentStatus : pending | reserved | packed | dispatched | delivered | cancelled
RefundStatus     : requested | approved | rejected | processed | failed
```

### 5.9 Order & inventory state transitions (invariants)

```
pending_payment --pay--> paid --pick--> processing --dispatch--> dispatched
   |                                                   |
   +--cancel--> cancelled                              +--deliver--> delivered --> completed
paid/processing --refund--> refunded
```

- Stock is **reserved** when an order is created, **deducted** (movement
  `sale`) when payment is confirmed, and **released** on cancellation/refund.
- Every transition writes `OrderStatusHistory` and (where it touches stock) a
  `StockMovement`, inside one transaction.

---

## 6. `services` — consultancy, farming, storage, marketing, export, training

All request types share a common shape: requester, division, details,
structured location, status, assigned staff, timestamps, history. They subclass
`ServiceRequest` (abstract) so the dashboard can present unified queues.

### 6.1 `ServiceRequest` (abstract base)

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `reference` | `CharField(20)` | unique per concrete table |
| `requester` | FK → `User` | `PROTECT`, `related_name="%(class)ss"` |
| `status` | `CharField(20)` | concrete `TextChoices` |
| `assigned_to` | FK → `User` | `SET_NULL`, nullable |
| `state` | FK → `State` | `PROTECT`, nullable |
| `lga` | FK → `LGA` | `PROTECT`, nullable |
| `details` | `TextField` | |
| `preferred_date` | Date | nullable |
| `is_deleted`,`deleted_at` | soft delete | |
| timestamps | | |

### 6.2 `ConsultancyRequest`

Adds: `topic` (`CharField`), `crop` (`CharField`), `consultation_mode`
(`TextChoices`: phone | onsite | online), `status`
(`ConsultancyStatus`: submitted | triaged | assigned | in_progress | completed | cancelled).

### 6.3 `FarmingServiceRequest`

Adds: `service_type` (`TextChoices`: land_preparation | planting | spraying |
harvesting | mechanisation | agronomy | other), `acreage` (`DecimalField(10,2)`),
`farm_location` (`CharField`), `status` (`FarmingStatus`).

### 6.4 `MarketingRequest`

Adds: `produce` (`CharField`), `volume` (`DecimalField(14,2)`), `volume_unit`
(`UnitOfMeasure`), `target_market` (`CharField`), `status` (`MarketingStatus`).

### 6.5 `StorageFacility`

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `name` | `CharField(150)` | |
| `state` | FK → `State` | `PROTECT` |
| `lga` | FK → `LGA` | `PROTECT` |
| `capacity` | `DecimalField(14,2)` | owner-provided (no invented default) |
| `capacity_unit` | `CharField(16)` | |
| `facility_type` | `CharField(60)` | e.g. dry, cold |
| `is_active` | `BooleanField` | indexed |
| timestamps | | |

### 6.6 `StorageRequest`

Adds: `facility` (FK, nullable until assigned), `produce` (`CharField`),
`quantity` + `quantity_unit`, `intake_date`, `expected_release_date`,
`status` (`StorageStatus`: submitted | quoted | accepted | stored | released | cancelled`),
and child `StorageRecord` rows for intake/release events.

### 6.7 `StorageRecord`

`storage_request` FK, `kind` (`intake` | `release` | `adjustment`),
`quantity`, `recorded_by` FK, `recorded_at`, `note`.

### 6.8 `ExportEnquiry`

Adds: `product` (`CharField`), `volume` + `volume_unit`,
`destination_country` (`CharField(80)`), `incoterm` (`CharField(3)`, blank),
`target_currency` (`CharField(3)`, default `USD`), `target_date`, `status`
(`ExportStatus`: submitted | reviewing | quoted | negotiating | won | lost | cancelled`).

- **Destination is an external market**; there is no branch/location concept.

### 6.9 `TrainingCourse`

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | PK |
| `title` | `CharField(180)` | |
| `slug` | `SlugField(200)` | unique |
| `summary` | `CharField(255)` | |
| `description` | `TextField` | |
| `level` | `CharField(20)` | `TextChoices` (beginner/intermediate/advanced) |
| `duration_hours` | `PositiveIntegerField` | |
| `fee` | `DecimalField(14,2)` | nullable (owner sets real value in dashboard) |
| `currency` | `CharField(3)` | default `NGN` |
| `status` | `CharField(16)` | `CourseStatus` (draft/published/archived) |
| timestamps | | |

### 6.10 `TrainingCohort`

`course` FK, `name`, `start_date`, `end_date`, `capacity`
(`PositiveIntegerField`, owner-provided), `location`, `status`
(`CohortStatus`: scheduled | open | full | in_progress | completed | cancelled`).

### 6.11 `TrainingEnrollment`

`cohort` FK, `trainee` FK → `User`, `status` (`EnrollmentStatus`: pending |
confirmed | attended | completed | cancelled), `enrolled_at`,
`unique(cohort, trainee)`, index `(trainee, status)`.

### 6.12 Status enumerations (`services`)

```
ConsultancyStatus : submitted | triaged | assigned | in_progress | completed | cancelled
FarmingStatus     : submitted | reviewed | scheduled | in_progress | completed | cancelled
MarketingStatus   : submitted | reviewed | matched | closed | cancelled
StorageStatus     : submitted | quoted | accepted | stored | released | cancelled
ExportStatus      : submitted | reviewing | quoted | negotiating | won | lost | cancelled
CourseStatus      : draft | published | archived
EnrollmentStatus  : pending | confirmed | attended | completed | cancelled
```

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

### 7.2 `ReportExport` (Phase 10)

`requested_by` FK, `report_key` `CharField`, `params` `JSONField`,
`status` (`pending | ready | failed`), `file` `FileField`, `created_at`,
`completed_at`.

### 7.3 `SavedReport` (Phase 10, optional)

`owner` FK, `name`, `report_key`, `params` `JSONField`, `is_shared`.

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
  listing origin+package, cart item, enrollment.
- CheckConstraints: non-negative money and stock; `stock_reserved <=
  stock_on_hand`; `selling_price >= 0`; `refund.amount <= payment.amount`
  enforced in the service layer with a DB check where possible.

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
User 1─* ServiceRequest (Consultancy/Farming/Marketing/Storage/Export)
StorageRequest 1─* StorageRecord
TrainingCourse 1─* TrainingCohort 1─* TrainingEnrollment *─1 User
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

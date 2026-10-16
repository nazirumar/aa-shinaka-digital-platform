# Phase 5 Completion Report — Cart, Checkout, Orders & Inventory

**Document ID:** AASDP-PH5-REP-001  
**Status:** Complete (for owner/engineering approval before Phase 6)  
**Date:** 2026-10-12

## Objective delivered

Phase 5 lets customers buy directly: a persistent, guest-capable cart
whose prices and stock are always recomputed server-side; a
transactional, authenticated-only checkout that snapshots line prices
and reserves stock per warehouse; an enforced order lifecycle with an
append-only history; and the staff orders + inventory screens to
fulfil. **No payment provider ships in this phase** — orders are
created `pending_payment` and can only become paid through an audited,
manual, staff-only approval (`FINANCE_MANAGE`). Warehouses, stock
balances and the reservation lifecycle are first-class, so stock never
goes negative under concurrent checkout.

## Files created/modified

### Apps (new)
- `apps/orders/`: `__init__.py`, `apps.py`, `models.py`,
  `selectors.py`, `services.py`, `forms.py`, `views.py`, `urls.py`,
  `dashboard_views.py`, `dashboard_urls.py`, `signals.py`,
  `tasks.py`, `context_processors.py` (cart badge),
  `management/commands/expire_orders.py`,
  `migrations/0001_initial.py`.

### Apps (modified)
- `apps/catalog/`: `inventory.py` (warehouse-aware stock service —
  new), `inventory_urls.py` (new), `dashboard_views.py` (Phase 5
  inventory views appended), `forms.py` (warehouse/stock forms),
  `services.py` (`adjust_stock` now delegates to `inventory`),
  `models.py` (`StockMovement` gained `variant`/`warehouse`),
  `migrations/0006`, `0007`.
- `apps/accounts/`: nothing structural; capabilities reused.
- `config/`: `settings/base.py` (cart context processor, Celery beat
  schedule), `urls.py` (root `orders` routes, `/dashboard/orders/`,
  `/dashboard/inventory/`).

### Templates
- Public/portal: `templates/orders/cart.html`, `checkout.html`,
  `order_list.html`, `order_detail.html`, `quotation_list.html`,
  `quotation_form.html`, `partials/cart_body.html`,
  `partials/cart_summary.html`, `partials/cart_feedback.html`,
  `partials/shipping_options.html`.
- Dashboard: `templates/dashboard/orders/*.html` (home, order list,
  order detail, shipments, quotations, shipping zones/methods/rates)
  and `templates/dashboard/inventory/*.html` (home, warehouses, stock
  list, movements, reservations, stock receive/transfer).
- Shared/nav: `templates/account/account_base.html`,
  `templates/navbar.html`, `templates/dashboard/base.html`,
  `templates/catalog/product_detail.html` (add-to-cart), cart badge.

## Models (catalog)

- `Warehouse` — name, unique `code`, address, optional
  state/LGA (`PROTECT`, LGA must belong to state), `is_active`.
  Data-driven; the default (`code="MAIN"`) is created on first use by
  `inventory.default_warehouse()`.
- `StockBalance` — authoritative per-warehouse stock:
  unique `(warehouse, listing, variant)` (`nulls_distinct=False`),
  `on_hand` (authoritative) and `reserved` (held by active
  reservations). `available = on_hand − reserved`. The listing's
  `stock_on_hand`/`stock_reserved` are **roll-ups** across
  warehouses, maintained by every stock write.
- `StockMovement` — gained `variant` and `warehouse` (both nullable,
  `PROTECT`) so each ledger row records exactly which balance it
  touched. Still append-only (edit/delete raise).

## Models (orders)

All `orders` primary keys are UUIDs; money is `DecimalField` only.

- `ShippingZone` / `ShippingMethod` / `ShippingRate` — delivery
  configuration: a zone groups states; a method is a carrier option;
  a rate is the fee for one `(zone, method)` pair (unique) with an
  optional `free_over` threshold and a `min_order_amount`. **No
  freight is invented** — checkout is blocked unless a matching active
  rate exists.
- `Cart` / `CartItem` — persistent customer cart (one active per user)
  plus guest carts (one active per session). Unique
  `(cart, listing, variant)`; `unit_price_snapshot` is indicative and
  always recomputed at checkout.
- `StockReservation` — one hold per order item: `(order, order_item,
  listing, variant, warehouse, quantity, status, expires_at)`. Each
  reservation leaves `active` exactly once (committed / released /
  expired).
- `Order` — `number` (`AS-YYYYMMDD-XXXXXX`, unique), unique
  `checkout_token` (idempotency key), status + `payment_status`,
  `subtotal`/`shipping_amount`/`discount_amount`/`tax_amount`/
  `grand_total`, currency, delivery-address snapshot fields, shipping
  method, contact snapshot, customer note, lifecycle timestamps
  (`placed_at`, `cancelled_at`, `expires_at`,
  `reservation_released_at`, `stock_committed_at`).
- `OrderItem` — line snapshots (`product_name`, `sku`, origin
  state/LGA, packaging, variant name, `quantity`, `unit_price`,
  `line_total`, `fulfilment_status`) so historical orders stay accurate.
- `OrderStatusHistory` — append-only: `save()` rejects updates and
  `delete()` always raises.
- `Shipment` — dispatch record (method, carrier, tracking, status,
  notes, handled_by, dispatch/delivery timestamps).
- `QuotationRequest` — bulk/wholesale enquiry (user nullable for
  guests, listing/variant, quantity, packaging, destination,
  requirements, contact, status, staff response).

## Migrations

- `catalog/0006_alter_category_path.py` (Phase 4 tail) and
  `catalog/0007_stockmovement_variant_warehouse_stockbalance_and_more.py`
  — `Warehouse`, `StockBalance`, and `StockMovement.variant/warehouse`.
- `orders/0001_initial.py` — the full `orders` schema above.

## Public / portal URLs (`apps.orders.urls`, mounted at site root)

- `/cart/` (`orders:cart`), `/cart/add/<pk>/`,
  `/cart/item/<pk>/` (update/remove), `/cart/count/`,
  `/cart/shipping-options/` (HTMX partial).
- `/checkout/` (`orders:checkout`) — POST-only order creation.
- `/orders/` (`orders:order_list`), `/orders/<number>/`
  (`orders:order_detail`), `/orders/<number>/cancel/`,
  `/orders/<number>/payment-review/`.
- `/quotations/` (`orders:quotation_list`),
  `/quotations/new/<listing_pk>/` (`orders:quotation_create`).

Checkout and the order portal are **authenticated-only**
(ASSUMPTION-07); guest carts still work and merge on login.

## Staff dashboard URLs

- `/dashboard/orders/` (`orders_dashboard`): home, order list/detail,
  status transition, payment confirmation (`FINANCE_MANAGE`), shipments
  (create/edit), quotation review, shipping zones/methods/rates CRUD.
- `/dashboard/inventory/` (`inventory_dashboard`): home, warehouses
  (list/create/edit), stock levels, movements, reservations, stock
  receive/transfer. The low-stock report is at
  `/dashboard/inventory/low-stock/` (`inventory_dashboard:low_stock`);
  the Phase 4 root-level `inventory_low_stock` alias is superseded by
  this namespaced route.

Every screen enforces its capability server-side (`ORDERS_MANAGE`,
`FINANCE_MANAGE`, `INVENTORY_MANAGE`); templates only hide navigation.

## Stock & reservation semantics

- Truth lives in `StockBalance.on_hand`/`reserved`; the listing's
  `stock_on_hand`/`stock_reserved` are maintained roll-ups.
- `apps.catalog.inventory` is the only writer: `adjust_stock`,
  `receive_stock`, `transfer_stock`, `place_reservation`,
  `release_reservation`, `commit_reservation`. Each takes a row lock
  (`select_for_update`) on the balance and the listing, refuses
  negative/oversell, writes an append-only `StockMovement`, and rolls
  the listing up — all inside one transaction. After the operation the
  caller's in-memory listing instance is refreshed
  (`_sync_caller`), so callers never act on stale stock.
- Phase 4's `catalog.services.adjust_stock` now delegates here, so the
  existing ledger and the new balances stay consistent.

## Order lifecycle & payment boundary

- State machine (`ORDER_TRANSITIONS` in `apps.orders.models`):
  `pending_payment → payment_review → confirmed → processing →
  ready_for_dispatch → dispatched → delivered → completed`, with
  `cancelled`/`expired` as terminal exceptions. Illegal transitions
  raise; every change appends to `OrderStatusHistory`.
- **Payment boundary:** the only path to `payment_status=paid` is
  `services.confirm_payment` (idempotent, `FINANCE_MANAGE`), which
  commits the reservations (a `sale` movement), stamps
  `stock_committed_at` and moves the order to `confirmed`. Customers
  may move their own order to `payment_review` but never to paid.
- Checkout is idempotent on `checkout_token` (a duplicate POST returns
  the existing order) and rejects a stale/oversized cart before any
  stock moves. Totals are recomputed server-side; line prices are
  snapshotted.
- Cancelling releases active reservations (or returns committed stock
  on paid orders); abandoned `pending_payment` orders expire via the
  Celery task `orders.expire_reservations` (beat-scheduled) with an
  `expire_orders` management-command fallback.

## Tests

New Phase 5 suites (73 tests):

- `tests/test_orders_cart.py` — 15 (guest session cart, login merge,
  add/update/remove, server-side pricing incl. wholesale tiers,
  cross-cart denial, zero-quantity removal).
- `tests/test_orders_checkout.py` — 12 (authenticated-only, address/
  method gating, configured-rate requirement, idempotency, client
  price ignored, shipping-options partial).
- `tests/test_orders_lifecycle.py` — 17 (state machine, payment
  confirmation commits stock, cancel/restock, expiry leaves fresh
  orders alone, append-only history, number format).
- `tests/test_orders_dashboard.py` — 12 (capability gating, order
  list/detail, transition form, payment approval by Finance only,
  shipping zone/rate creation).
- `tests/test_inventory_dashboard.py` — 9 (warehouse CRUD, stock
  receive/transfer forms, movement ledger, reservation overview).
- `tests/test_orders_public.py` — 8 (order portal isolation, cancel,
  payment-review never pays, quotation submit/list scoped to user).

## Quality gates (end of Phase 5)

- `uv run python manage.py check` — clean.
- `uv run python manage.py makemigrations --check --dry-run` — no
  changes.
- `uv run ruff check .` — clean; `uv run ruff format --check .` — clean.
- `uv run pytest` — all green (Phase 1–4 baseline + 73 new).
- `npm.cmd run build:css` — Tailwind built `static/css/app.css`
  (gitignored).
- No secrets committed; no hardcoded categories/prices/inventory/
  achievements; no oil & gas, multi-vendor or AgriTrade ERP; no
  payment provider.

## Documentation updated in Phase 5

- `docs/IMPLEMENTATION_ROADMAP.md` — version 0.5: **Phase 5 = Cart,
  Checkout, Orders & Inventory ✅**; Phase 6 (Paystack) is next and
  must not start without approval.
- `docs/ARCHITECTURE.md` — app table (`apps.catalog` Phases 4–5,
  `apps.orders` Phase 5), payment-lifecycle and state-transition
  sections rewritten for the manual-approval boundary, testing notes.
- `docs/DATABASE_DESIGN.md` — §4.6–4.9 (`StockMovement` variant/
  warehouse, `Warehouse`, `StockBalance`), §5 rewritten for the
  implemented `orders` models and enumerations; `Payment`/`Refund`
  moved to a Phase 6 placeholder.
- `docs/SRS.md` — §5.5 implementation-status note, ASSUMPTION-06/-07
  resolution.
- `README.md` — status now "Phases 1–5 complete" with the Phase 5
  feature summary.

## Open items / deviations (for owner decision)

- **ASSUMPTION-06 (email verification before checkout):** checkout
  requires authentication only; the verified-email gate is **not**
  enforced. Confirm whether verified email must be mandatory before
  checkout (a one-line gate in `apps.orders.views.checkout`).
- **ASSUMPTION-04 (VAT/tax and delivery-fee rules):** Phase 5 applies
  a single configurable tax rate and charges the configured
  `ShippingRate.fee`; no tax-table or free-shipping-rule engine yet.
- **Quotation pricing/acceptance** is captured and reviewable but not
  yet priced/convertible (dedicated quotations phase).
- Phase 6 (Paystack payments & refunds) is **not started**.

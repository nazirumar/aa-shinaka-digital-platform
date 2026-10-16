"""Warehouse-aware inventory operations (Phase 5).

Single source of truth: every on-hand quantity lives in ``StockBalance`` rows
(per warehouse × listing × variant). ``ProductListing.stock_on_hand`` is a
**denormalised roll-up** (``Σ balances.on_hand``) maintained here so the fast
public filters keep working; ``ProductListing.stock_reserved`` is the roll-up of
the active ``orders.StockReservation`` rows and is maintained by the order
services through the ``place_reservation`` / ``release_reservation`` /
``commit_reservation`` helpers below.

Quantities use the listing's package unit (the platform's single unit-of-measure
strategy for stock) and are always ``Decimal``. Every mutation takes a row lock
and runs in a transaction; the movement ledger is append-only.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from apps.core.audit import record_audit

from .models import (
    ListingStatus,
    ProductListing,
    ProductVariant,
    StockBalance,
    StockMovement,
    StockMovementKind,
    Warehouse,
)

DEFAULT_WAREHOUSE_CODE = "MAIN"
ZERO = Decimal("0.000")


def _actor(user):
    return user if getattr(user, "is_authenticated", False) else None


def _as_decimal(value) -> Decimal:
    if value is None:
        raise ValidationError("Enter a valid stock quantity.")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid stock quantity.") from exc


def default_warehouse() -> Warehouse:
    """Return (creating on first use) the platform's default warehouse."""
    warehouse, _ = Warehouse.objects.get_or_create(
        code=DEFAULT_WAREHOUSE_CODE,
        defaults={"name": "Main warehouse"},
    )
    return warehouse


def resolve_warehouse(warehouse: Warehouse | None = None) -> Warehouse:
    return warehouse or default_warehouse()


def get_balance(
    listing: ProductListing,
    *,
    warehouse: Warehouse | None = None,
    variant: ProductVariant | None = None,
    for_update: bool = False,
) -> StockBalance:
    """Return the balance row for a (warehouse, listing, variant), creating it."""
    warehouse = resolve_warehouse(warehouse)
    queryset = StockBalance.objects
    if for_update:
        queryset = queryset.select_for_update()
    balance, created = queryset.get_or_create(warehouse=warehouse, listing=listing, variant=variant)
    if created:
        # Reload so the database-coerced Decimal defaults are used (get_or_create
        # leaves the raw field defaults in memory otherwise).
        balance.refresh_from_db()
    return balance


def _rollup_on_hand(listing: ProductListing) -> Decimal:
    total = (
        StockBalance.objects.filter(listing=listing).aggregate(total=Sum("on_hand"))["total"]
        or ZERO
    )
    listing.stock_on_hand = total
    listing.save(update_fields=["stock_on_hand", "updated_at"])
    return total


def _recompute_rollup(listing: ProductListing) -> Decimal:
    """Re-derive both roll-ups from the authoritative per-warehouse balances.

    ``stock_on_hand`` and ``stock_reserved`` are denormalised sums of
    ``StockBalance`` rows. Recomputing (rather than adding/subtracting) keeps
    them exactly consistent with Σ balances even when a release targets a
    different warehouse than the one that placed the hold.
    """
    totals = StockBalance.objects.filter(listing=listing).aggregate(
        on_hand=Sum("on_hand"), reserved=Sum("reserved")
    )
    listing.stock_on_hand = totals["on_hand"] or ZERO
    listing.stock_reserved = totals["reserved"] or ZERO
    listing.save(update_fields=["stock_on_hand", "stock_reserved", "updated_at"])
    return listing.stock_on_hand


def _available_by_warehouse(
    listing: ProductListing, *, variant: ProductVariant | None = None
) -> dict:
    """Map ``warehouse_id -> unreserved available`` for a listing/variant."""
    rows = StockBalance.objects.filter(listing=listing, variant=variant, warehouse__is_active=True)
    return {balance.warehouse_id: balance.on_hand - balance.reserved for balance in rows}


def select_warehouse(
    listing: ProductListing,
    *,
    quantity,
    variant: ProductVariant | None = None,
    preferred: Warehouse | None = None,
) -> Warehouse:
    """Choose the warehouse to fulfil from — explicitly and deterministically.

    Order of preference: an explicitly named warehouse, then the platform
    default, then any active warehouse whose unreserved stock covers the line.
    Single-warehouse deployments therefore always resolve to ``MAIN``; the
    caller never has a warehouse chosen for it by luck.
    """
    amount = _as_decimal(quantity)
    if preferred is not None:
        return preferred
    default = default_warehouse()
    available = _available_by_warehouse(listing, variant=variant)
    if available.get(default.pk, ZERO) >= amount:
        return default
    # Exactly one candidate that can cover the whole line, in a stable order.
    covering = [warehouse_id for warehouse_id, qty in sorted(available.items()) if qty >= amount]
    if len(covering) == 1:
        return Warehouse.objects.get(pk=covering[0])
    if len(covering) > 1:
        # Several could cover it: prefer the one with the most headroom
        # (deterministic tie-break on the id string).
        best = max(covering, key=lambda warehouse_id: (available[warehouse_id], str(warehouse_id)))
        return Warehouse.objects.get(pk=best)
    # Nothing covers it: fall back to the default so the caller gets the
    # familiar out-of-stock error from ``place_reservation``.
    return default


def _sync_listing_status(listing: ProductListing) -> None:
    available = listing.stock_on_hand - listing.stock_reserved
    if available <= 0 and listing.status == ListingStatus.ACTIVE:
        listing.status = ListingStatus.OUT_OF_STOCK
        listing.save(update_fields=["status", "updated_at"])
    elif available > 0 and listing.status == ListingStatus.OUT_OF_STOCK:
        listing.status = ListingStatus.ACTIVE
        listing.save(update_fields=["status", "updated_at"])


def _sync_caller(original: ProductListing, locked: ProductListing) -> None:
    """Copy DB-authoritative stock fields back onto the caller's instance.

    Stock operations lock and re-read the listing row, so the object the caller
    passed in would otherwise keep stale in-memory ``stock_on_hand`` /
    ``stock_reserved`` / ``status`` values after the operation.
    """
    original.stock_on_hand = locked.stock_on_hand
    original.stock_reserved = locked.stock_reserved
    original.status = locked.status
    original.updated_at = locked.updated_at


def _write_movement(
    listing: ProductListing,
    *,
    delta: Decimal,
    kind: str,
    balance_after: Decimal,
    warehouse: Warehouse | None = None,
    variant: ProductVariant | None = None,
    reference: str = "",
    note: str = "",
    actor=None,
) -> StockMovement:
    return StockMovement.objects.create(
        listing=listing,
        variant=variant,
        warehouse=warehouse,
        kind=kind,
        quantity_delta=delta,
        balance_after=balance_after,
        reference=reference[:100],
        actor=_actor(actor),
        note=note,
    )


def adjust_stock(
    listing: ProductListing,
    *,
    delta,
    warehouse: Warehouse | None = None,
    variant: ProductVariant | None = None,
    kind: str = StockMovementKind.ADJUSTMENT,
    reference: str = "",
    note: str = "",
    actor=None,
    request=None,
) -> StockMovement:
    """Apply a signed delta to one warehouse balance and roll up the listing."""
    if kind not in StockMovementKind.values:
        raise ValidationError(f"Unknown stock movement kind '{kind}'.")
    amount = _as_decimal(delta)
    resolved = resolve_warehouse(warehouse)
    caller = listing

    with transaction.atomic():
        listing = ProductListing.objects.select_for_update().get(pk=listing.pk)
        balance = get_balance(listing, warehouse=resolved, variant=variant, for_update=True)
        new_on_hand = balance.on_hand + amount
        if new_on_hand < 0:
            raise ValidationError("Stock cannot go below zero.")
        if new_on_hand < balance.reserved:
            raise ValidationError("Stock cannot be reduced below what is already reserved.")
        before_total = listing.stock_on_hand
        balance.on_hand = new_on_hand
        balance.save(update_fields=["on_hand", "updated_at"])
        total = _rollup_on_hand(listing)
        movement = _write_movement(
            listing,
            delta=amount,
            kind=kind,
            balance_after=total,
            warehouse=resolved,
            variant=variant,
            reference=reference,
            note=note,
            actor=actor,
        )
        _sync_listing_status(listing)
        record_audit(
            actor=actor,
            action="catalog.listing.stock",
            target=listing,
            before={"stock_on_hand": str(before_total)},
            after={
                "stock_on_hand": str(listing.stock_on_hand),
                "delta": str(amount),
                "warehouse": resolved.code,
            },
            request=request,
        )
    _sync_caller(caller, listing)
    return movement


def receive_stock(
    listing: ProductListing,
    *,
    quantity,
    warehouse: Warehouse | None = None,
    variant: ProductVariant | None = None,
    reference: str = "",
    note: str = "",
    actor=None,
    request=None,
) -> StockMovement:
    """Receive (intake) a positive quantity into a warehouse."""
    amount = _as_decimal(quantity)
    if amount <= 0:
        raise ValidationError("Received quantity must be positive.")
    return adjust_stock(
        listing,
        delta=amount,
        warehouse=warehouse,
        variant=variant,
        kind=StockMovementKind.INTAKE,
        reference=reference,
        note=note,
        actor=actor,
        request=request,
    )


def transfer_stock(
    listing: ProductListing,
    *,
    quantity,
    from_warehouse: Warehouse,
    to_warehouse: Warehouse,
    variant: ProductVariant | None = None,
    reference: str = "",
    note: str = "",
    actor=None,
    request=None,
) -> tuple[StockMovement, StockMovement]:
    """Move unreserved stock between warehouses, writing both ledger legs."""
    amount = _as_decimal(quantity)
    if amount <= 0:
        raise ValidationError("Transfer quantity must be positive.")
    if from_warehouse.pk == to_warehouse.pk:
        raise ValidationError("Source and destination warehouses must differ.")

    caller = listing
    with transaction.atomic():
        listing = ProductListing.objects.select_for_update().get(pk=listing.pk)
        source = get_balance(listing, warehouse=from_warehouse, variant=variant, for_update=True)
        destination = get_balance(listing, warehouse=to_warehouse, variant=variant, for_update=True)
        if source.on_hand - amount < source.reserved:
            raise ValidationError(
                "Not enough unreserved stock in the source warehouse to transfer."
            )
        source.on_hand = source.on_hand - amount
        source.save(update_fields=["on_hand", "updated_at"])
        destination.on_hand = destination.on_hand + amount
        destination.save(update_fields=["on_hand", "updated_at"])
        total = _rollup_on_hand(listing)
        out_movement = _write_movement(
            listing,
            delta=-amount,
            kind=StockMovementKind.TRANSFER,
            balance_after=total,
            warehouse=from_warehouse,
            variant=variant,
            reference=reference,
            note=note,
            actor=actor,
        )
        in_movement = _write_movement(
            listing,
            delta=amount,
            kind=StockMovementKind.TRANSFER,
            balance_after=total,
            warehouse=to_warehouse,
            variant=variant,
            reference=reference,
            note=note,
            actor=actor,
        )
        record_audit(
            actor=actor,
            action="catalog.stock.transfer",
            target=listing,
            after={
                "from": from_warehouse.code,
                "to": to_warehouse.code,
                "quantity": str(amount),
                "reference": reference,
            },
            request=request,
        )
    _sync_caller(caller, listing)
    return out_movement, in_movement


# ---------------------------------------------------------------------------
# Reservation bookkeeping (called by the order services inside their txn)
# ---------------------------------------------------------------------------


def place_reservation(
    listing: ProductListing,
    *,
    quantity,
    variant: ProductVariant | None = None,
    warehouse: Warehouse | None = None,
) -> Decimal:
    """Hold ``quantity`` of a listing; raise if it exceeds availability."""
    amount = _as_decimal(quantity)
    if amount <= 0:
        raise ValidationError("Reservation quantity must be positive.")
    resolved = resolve_warehouse(warehouse)
    caller = listing

    with transaction.atomic():
        listing = ProductListing.objects.select_for_update().get(pk=listing.pk)
        balance = get_balance(listing, warehouse=resolved, variant=variant, for_update=True)
        available_here = balance.on_hand - balance.reserved
        if available_here < amount:
            raise ValidationError(
                f"Only {available_here} of {listing.product.name} "
                f"({listing.packaging}) is available at {resolved.name}."
            )
        balance.reserved = balance.reserved + amount
        balance.save(update_fields=["reserved", "updated_at"])
        _recompute_rollup(listing)
    _sync_caller(caller, listing)
    return amount


def release_reservation(
    listing: ProductListing,
    *,
    quantity,
    variant: ProductVariant | None = None,
    warehouse: Warehouse | None = None,
) -> None:
    """Release a previously placed reservation (never below zero).

    The roll-up is recomputed from Σ balances afterwards, so releasing against
    the wrong warehouse can never desynchronise ``stock_reserved`` from the
    per-warehouse rows.
    """
    amount = _as_decimal(quantity)
    if amount <= 0:
        raise ValidationError("Release quantity must be positive.")
    resolved = resolve_warehouse(warehouse)
    caller = listing
    with transaction.atomic():
        listing = ProductListing.objects.select_for_update().get(pk=listing.pk)
        balance = get_balance(listing, warehouse=resolved, variant=variant, for_update=True)
        balance.reserved = max(balance.reserved - amount, ZERO)
        balance.save(update_fields=["reserved", "updated_at"])
        _recompute_rollup(listing)
    _sync_caller(caller, listing)


def commit_reservation(
    listing: ProductListing,
    *,
    quantity,
    variant: ProductVariant | None = None,
    warehouse: Warehouse | None = None,
    reference: str = "",
    actor=None,
) -> StockMovement:
    """Turn a reservation into a sale: reduce on-hand and reserved together."""
    amount = _as_decimal(quantity)
    if amount <= 0:
        raise ValidationError("Committed quantity must be positive.")
    resolved = resolve_warehouse(warehouse)
    caller = listing
    with transaction.atomic():
        listing = ProductListing.objects.select_for_update().get(pk=listing.pk)
        balance = get_balance(listing, warehouse=resolved, variant=variant, for_update=True)
        if balance.on_hand < amount:
            raise ValidationError("Committed quantity exceeds stock on hand.")
        balance.on_hand = balance.on_hand - amount
        balance.reserved = max(balance.reserved - amount, ZERO)
        balance.save(update_fields=["on_hand", "reserved", "updated_at"])
        total = _recompute_rollup(listing)
        movement = _write_movement(
            listing,
            delta=-amount,
            kind=StockMovementKind.SALE,
            balance_after=total,
            warehouse=resolved,
            variant=variant,
            reference=reference[:100],
            note="Order payment confirmed",
            actor=actor,
        )
        _sync_listing_status(listing)
    _sync_caller(caller, listing)
    return movement

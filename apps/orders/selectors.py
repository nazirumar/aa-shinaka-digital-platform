"""Read-only queries for the order app (cart, checkout, orders, inventory views).

Public/customer selectors are always scoped to the requesting user (orders are
never exposed across customers). Prices are recomputed here from live catalogue
data — never taken from the client. Staff selectors back the dashboard lists.
"""

from __future__ import annotations

from django.db.models import Count, F, Q, QuerySet, Sum

from apps.catalog.models import (
    ListingStatus,
    ProductListing,
    PublishStatus,
    StockBalance,
    StockMovement,
    Warehouse,
    WholesalePriceTier,
)

from .models import (
    Cart,
    CartStatus,
    Order,
    OrderStatus,
    PaymentStatus,
    QuotationRequest,
    ReservationStatus,
    ShippingMethod,
    ShippingRate,
    StockReservation,
)

# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


def active_cart_for_user(user) -> Cart | None:
    if not getattr(user, "is_authenticated", False):
        return None
    return Cart.objects.filter(user=user, status=CartStatus.ACTIVE).first()


def active_cart_for_session(session_key: str) -> Cart | None:
    if not session_key:
        return None
    return Cart.objects.filter(session_key=session_key, status=CartStatus.ACTIVE).first()


def unit_price_for(listing: ProductListing, *, variant=None, quantity=None):
    """Authoritative unit price for a listing/variant at a quantity.

    Uses the effective ``ListingPrice`` (variant-specific when present, else the
    listing price) and applies the most specific active wholesale tier. Returns a
    ``Decimal`` (never a float, never a client-supplied value).
    """
    from apps.catalog import selectors as catalog_selectors

    price_row = catalog_selectors.effective_price(listing, variant=variant)
    base = price_row.amount if price_row is not None else listing.selling_price

    if quantity is not None:
        tier = (
            WholesalePriceTier.objects.filter(
                listing=listing,
                variant=variant,
                is_active=True,
                min_quantity__lte=quantity,
            )
            .order_by("-min_quantity")
            .first()
        )
        if tier is not None:
            return tier.price
    return base


def cart_lines(cart: Cart | None) -> list[dict]:
    """Return priced cart lines with per-line availability issues (read-only)."""
    if cart is None:
        return []
    lines: list[dict] = []
    for item in cart.items.select_related(
        "listing__product", "listing__state", "listing__lga", "variant"
    ):
        listing = item.listing
        price = unit_price_for(listing, variant=item.variant, quantity=item.quantity)
        available = listing.available_stock
        issue = ""
        unavailable = (
            listing.status != ListingStatus.ACTIVE
            or listing.product.status != PublishStatus.PUBLISHED
        )
        if unavailable:
            issue = "This product is no longer available."
        elif item.quantity > available:
            issue = f"Only {available} available (you asked for {item.quantity})."
        lines.append(
            {
                "item": item,
                "listing": listing,
                "variant": item.variant,
                "quantity": item.quantity,
                "unit_price": price,
                "line_total": price * item.quantity,
                "available": available,
                "issue": issue,
            }
        )
    return lines


def cart_totals(cart: Cart | None) -> dict:
    lines = cart_lines(cart)
    subtotal = sum((line["line_total"] for line in lines), start=0)
    issues = [line["issue"] for line in lines if line["issue"]]
    return {
        "lines": lines,
        "subtotal": subtotal,
        "item_count": len(lines),
        "total_quantity": sum((line["quantity"] for line in lines), start=0),
        "issues": issues,
        "is_checkoutable": bool(lines) and not issues,
    }


# ---------------------------------------------------------------------------
# Checkout / shipping
# ---------------------------------------------------------------------------


def shipping_options_for_state(state) -> list[dict]:
    """Configured delivery methods available for a destination state.

    A method is available when an active rate exists in a zone that covers the
    destination state. Nothing is invented: no matching rate → no option.
    """
    if state is None:
        return []
    rates = (
        ShippingRate.objects.filter(
            is_active=True,
            zone__is_active=True,
            zone__states=state,
            method__is_active=True,
        )
        .select_related("method", "zone")
        .order_by("method__sort_order", "method__name")
    )
    return [
        {"method": rate.method, "rate": rate, "zone": rate.zone, "fee": rate.fee} for rate in rates
    ]


def shipping_rate_for(state, method: ShippingMethod | None) -> ShippingRate | None:
    if state is None or method is None:
        return None
    return (
        ShippingRate.objects.filter(
            is_active=True,
            zone__is_active=True,
            zone__states=state,
            method=method,
            method__is_active=True,
        )
        .select_related("method", "zone")
        .first()
    )


def shipping_zones():
    from .models import ShippingZone

    return ShippingZone.objects.prefetch_related("states").order_by("name")


def shipping_methods_list():
    return ShippingMethod.objects.order_by("sort_order", "name")


def shipping_rates():
    return ShippingRate.objects.select_related("zone", "method").order_by(
        "zone__name", "method__sort_order", "method__name"
    )


# ---------------------------------------------------------------------------
# Customer orders
# ---------------------------------------------------------------------------


def orders_for_user(user) -> QuerySet[Order]:
    return (
        Order.objects.filter(user=user).annotate(item_count=Count("items")).order_by("-created_at")
    )


def order_for_user(user, number: str) -> Order | None:
    return (
        Order.objects.filter(user=user, number=number)
        .prefetch_related("items", "history", "shipments")
        .first()
    )


def order_timeline(order: Order):
    return order.history.select_related("changed_by").order_by("created_at")


# ---------------------------------------------------------------------------
# Staff orders
# ---------------------------------------------------------------------------


def staff_orders(
    *,
    status: str = "",
    payment_status: str = "",
    query: str = "",
    date_from=None,
    date_to=None,
) -> QuerySet[Order]:
    queryset = (
        Order.objects.select_related("user", "delivery_state", "shipping_method")
        .annotate(item_count=Count("items"))
        .order_by("-created_at")
    )
    if status:
        queryset = queryset.filter(status=status)
    if payment_status:
        queryset = queryset.filter(payment_status=payment_status)
    if query:
        queryset = queryset.filter(
            Q(number__icontains=query)
            | Q(user__email__icontains=query)
            | Q(contact_name__icontains=query)
            | Q(contact_phone__icontains=query)
        )
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    return queryset


def order_counts() -> dict:
    """Real counts for the orders dashboard (nothing fabricated)."""
    return {
        "total": Order.objects.count(),
        "pending_payment": Order.objects.filter(status=OrderStatus.PENDING_PAYMENT).count(),
        "payment_review": Order.objects.filter(status=OrderStatus.PAYMENT_REVIEW).count(),
        "open": Order.objects.filter(
            status__in=[
                OrderStatus.CONFIRMED,
                OrderStatus.PROCESSING,
                OrderStatus.READY_FOR_DISPATCH,
                OrderStatus.DISPATCHED,
            ]
        ).count(),
        "delivered": Order.objects.filter(status=OrderStatus.DELIVERED).count(),
        "cancelled": Order.objects.filter(status=OrderStatus.CANCELLED).count(),
        "unpaid": Order.objects.filter(payment_status=PaymentStatus.PENDING).count(),
        "paid": Order.objects.filter(payment_status=PaymentStatus.PAID).count(),
    }


# ---------------------------------------------------------------------------
# Inventory dashboard
# ---------------------------------------------------------------------------


def warehouse_list() -> QuerySet[Warehouse]:
    return Warehouse.objects.order_by("name")


def stock_balances(*, warehouse=None, query: str = "", low_only: bool = False):
    queryset = StockBalance.objects.select_related(
        "warehouse", "listing__product", "listing__state", "variant"
    ).order_by("warehouse__name", "listing__product__name")
    if warehouse is not None:
        queryset = queryset.filter(warehouse=warehouse)
    if query:
        queryset = queryset.filter(
            Q(listing__product__name__icontains=query) | Q(warehouse__name__icontains=query)
        )
    if low_only:
        queryset = queryset.filter(
            listing__low_stock_threshold__isnull=False,
            on_hand__lte=F("listing__low_stock_threshold"),
        )
    return queryset


def stock_movements(*, listing=None, warehouse=None, limit: int | None = None):
    queryset = StockMovement.objects.select_related(
        "listing__product", "warehouse", "actor"
    ).order_by("-created_at")
    if listing is not None:
        queryset = queryset.filter(listing=listing)
    if warehouse is not None:
        queryset = queryset.filter(warehouse=warehouse)
    return queryset[:limit] if limit else queryset


def reserved_overview() -> QuerySet[StockReservation]:
    return (
        StockReservation.objects.filter(status=ReservationStatus.ACTIVE)
        .select_related("order", "listing__product", "warehouse")
        .order_by("expires_at")
    )


def inventory_counts() -> dict:
    return {
        "warehouses": Warehouse.objects.count(),
        "active_warehouses": Warehouse.objects.filter(is_active=True).count(),
        "balances": StockBalance.objects.count(),
        "on_hand_total": StockBalance.objects.aggregate(total=Sum("on_hand"))["total"] or 0,
        "reserved_total": StockBalance.objects.aggregate(total=Sum("reserved"))["total"] or 0,
        "active_reservations": StockReservation.objects.filter(
            status=ReservationStatus.ACTIVE
        ).count(),
        "movements": StockMovement.objects.count(),
    }


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------


def quotations_for_user(user) -> QuerySet[QuotationRequest]:
    return QuotationRequest.objects.filter(user=user).select_related(
        "listing__product", "destination_state", "destination_lga"
    )


def staff_quotations(*, status: str = "", query: str = "") -> QuerySet[QuotationRequest]:
    queryset = QuotationRequest.objects.select_related(
        "listing__product", "user", "destination_state"
    ).order_by("-created_at")
    if status:
        queryset = queryset.filter(status=status)
    if query:
        queryset = queryset.filter(
            Q(contact_name__icontains=query)
            | Q(contact_email__icontains=query)
            | Q(listing__product__name__icontains=query)
        )
    return queryset


__all__ = [
    "active_cart_for_session",
    "active_cart_for_user",
    "cart_lines",
    "cart_totals",
    "inventory_counts",
    "order_counts",
    "order_for_user",
    "order_timeline",
    "orders_for_user",
    "quotations_for_user",
    "reserved_overview",
    "shipping_options_for_state",
    "shipping_rate_for",
    "shipping_rates",
    "shipping_zones",
    "shipping_methods_list",
    "staff_orders",
    "staff_quotations",
    "stock_balances",
    "stock_movements",
    "unit_price_for",
    "warehouse_list",
]

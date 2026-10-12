"""Order-app models: cart, checkout, orders, reservations, shipping, quotations.

Phase 5 ships the customer-facing commerce flow without any payment provider:
orders are created as ``pending_payment`` and only move into paid fulfilment
states through an explicit, audited staff approval (Phase 6 adds Paystack and
the signed-webhook path that calls the same commit logic).

Money is always ``DecimalField``. Historical order lines snapshot the values
they were sold at, so editing a catalogue price never rewrites an old order.
Stock reservations live here (they always belong to an order) and reference the
``catalog`` listing/warehouse tables; the per-warehouse positions themselves
live in ``apps.catalog`` (``Warehouse``/``StockBalance``).
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

User = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class UUIDTimeStampedModel(models.Model):
    """Timestamped base with a UUID primary key (matches the catalogue PKs)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CartStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CONVERTED = "converted", "Converted to order"
    MERGED = "merged", "Merged"
    ABANDONED = "abandoned", "Abandoned"


class OrderStatus(models.TextChoices):
    PENDING_PAYMENT = "pending_payment", "Pending payment"
    PAYMENT_REVIEW = "payment_review", "Payment review"
    CONFIRMED = "confirmed", "Confirmed"
    PROCESSING = "processing", "Processing"
    READY_FOR_DISPATCH = "ready_for_dispatch", "Ready for dispatch"
    DISPATCHED = "dispatched", "Dispatched"
    DELIVERED = "delivered", "Delivered"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"
    REFUNDED = "refunded", "Refunded"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"


class FulfilmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RESERVED = "reserved", "Reserved"
    PACKED = "packed", "Packed"
    DISPATCHED = "dispatched", "Dispatched"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"


class ReservationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMMITTED = "committed", "Committed"
    RELEASED = "released", "Released"
    EXPIRED = "expired", "Expired"


class QuotationStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    REVIEWING = "reviewing", "Reviewing"
    QUOTED = "quoted", "Quoted"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"
    CLOSED = "closed", "Closed"


class ShipmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PACKED = "packed", "Packed"
    IN_TRANSIT = "in_transit", "In transit"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    RETURNED = "returned", "Returned"


# Allowed order status transitions. Terminal states map to an empty set.
ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    OrderStatus.PENDING_PAYMENT: frozenset(
        {
            OrderStatus.PAYMENT_REVIEW,
            OrderStatus.CONFIRMED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.PAYMENT_REVIEW: frozenset(
        {
            OrderStatus.CONFIRMED,
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.PROCESSING, OrderStatus.CANCELLED}),
    OrderStatus.PROCESSING: frozenset({OrderStatus.READY_FOR_DISPATCH, OrderStatus.CANCELLED}),
    OrderStatus.READY_FOR_DISPATCH: frozenset({OrderStatus.DISPATCHED, OrderStatus.CANCELLED}),
    OrderStatus.DISPATCHED: frozenset({OrderStatus.DELIVERED}),
    OrderStatus.DELIVERED: frozenset({OrderStatus.COMPLETED}),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
    OrderStatus.REFUNDED: frozenset(),
}

# Statuses that may only be entered once payment is verified/approved.
PAID_FULFILMENT_STATUSES: frozenset[str] = frozenset(
    {
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
        OrderStatus.READY_FOR_DISPATCH,
        OrderStatus.DISPATCHED,
        OrderStatus.DELIVERED,
        OrderStatus.COMPLETED,
    }
)


# ---------------------------------------------------------------------------
# Shipping configuration
# ---------------------------------------------------------------------------


class ShippingZone(UUIDTimeStampedModel):
    """A group of destination states that share delivery pricing."""

    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    description = models.TextField(blank=True)
    states = models.ManyToManyField("locations.State", blank=True, related_name="shipping_zones")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]
        verbose_name = "Shipping zone"
        verbose_name_plural = "Shipping zones"

    def __str__(self) -> str:
        return self.name


class ShippingMethod(UUIDTimeStampedModel):
    """A delivery method (pickup, doorstep, dispatch rider, ...)."""

    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering: ClassVar[list[str]] = ["sort_order", "name"]
        verbose_name = "Shipping method"
        verbose_name_plural = "Shipping methods"

    def __str__(self) -> str:
        return self.name


class ShippingRate(UUIDTimeStampedModel):
    """The configured fee for a (zone, method) pair. No rate is ever invented."""

    zone = models.ForeignKey(ShippingZone, on_delete=models.CASCADE, related_name="rates")
    method = models.ForeignKey(ShippingMethod, on_delete=models.CASCADE, related_name="rates")
    fee = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    free_over = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional order subtotal at/above which delivery is free.",
    )
    min_order_amount = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    currency = models.CharField(max_length=3, default="NGN")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["zone__name", "method__sort_order"]
        verbose_name = "Shipping rate"
        verbose_name_plural = "Shipping rates"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["zone", "method"], name="uniq_shipping_rate_zone_method"
            ),
            models.CheckConstraint(condition=Q(fee__gte="0"), name="chk_shipping_fee_nonneg"),
            models.CheckConstraint(
                condition=Q(free_over__isnull=True) | Q(free_over__gte="0"),
                name="chk_shipping_free_over_nonneg",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.zone.name} · {self.method.name} · {self.fee}"

    def fee_for(self, subtotal):
        """Return the applicable fee for an order subtotal (Decimal)."""
        if self.free_over is not None and subtotal is not None and subtotal >= self.free_over:
            return self.fee * 0
        return self.fee


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


class Cart(UUIDTimeStampedModel):
    """A shopping cart.

    A signed-in customer has at most one *active* cart (persistent across
    devices); a guest has at most one active cart per session. Checkout is only
    available to signed-in customers (ASSUMPTION-07), so guest carts are merged
    into the customer cart on login.
    """

    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.CASCADE, related_name="carts"
    )
    session_key = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(
        max_length=16, choices=CartStatus.choices, default=CartStatus.ACTIVE, db_index=True
    )
    checked_out_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-updated_at"]
        verbose_name = "Cart"
        verbose_name_plural = "Carts"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status="active", user__isnull=False),
                name="uniq_active_cart_per_user",
            ),
            models.UniqueConstraint(
                fields=["session_key"],
                condition=Q(status="active", session_key__gt=""),
                name="uniq_active_cart_per_session",
            ),
        ]

    def __str__(self) -> str:
        owner = self.user.email if self.user_id else f"guest:{self.session_key[:8]}"
        return f"Cart {owner}"

    @property
    def item_count(self) -> int:
        return self.items.count()

    def total_quantity(self):
        return sum((item.quantity for item in self.items.all()), start=0)


class CartItem(UUIDTimeStampedModel):
    """A line in a cart. ``unit_price_snapshot`` is display-only.

    Authoritative prices are always recomputed server-side from the live
    listing/variant/tier data at add, update, review and order-creation time;
    the client never supplies a price.
    """

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    listing = models.ForeignKey(
        "catalog.ProductListing", on_delete=models.CASCADE, related_name="cart_items"
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="cart_items",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")

    class Meta:
        ordering: ClassVar[list[str]] = ["created_at"]
        verbose_name = "Cart item"
        verbose_name_plural = "Cart items"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["cart", "listing", "variant"],
                name="uniq_cart_listing_variant",
                nulls_distinct=False,
            ),
            models.CheckConstraint(condition=Q(quantity__gt="0"), name="chk_cartitem_qty_positive"),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["cart", "listing"]),
        ]

    def __str__(self) -> str:
        return f"{self.listing} × {self.quantity}"


# ---------------------------------------------------------------------------
# Stock reservations
# ---------------------------------------------------------------------------


class StockReservation(UUIDTimeStampedModel):
    """A hold on stock while an order awaits payment.

    Exactly one active reservation is created per order item at checkout. The
    lifecycle (active → committed on paid fulfilment, or released/expired) is
    driven by the order services and is idempotent: a reservation can only leave
    ``active`` once.
    """

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="reservations")
    order_item = models.ForeignKey(
        "orders.OrderItem",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    listing = models.ForeignKey(
        "catalog.ProductListing", on_delete=models.PROTECT, related_name="reservations"
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    warehouse = models.ForeignKey(
        "catalog.Warehouse",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    status = models.CharField(
        max_length=16,
        choices=ReservationStatus.choices,
        default=ReservationStatus.ACTIVE,
        db_index=True,
    )
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Stock reservation"
        verbose_name_plural = "Stock reservations"
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=Q(quantity__gt="0"), name="chk_reservation_qty_positive"
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["order", "status"]),
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["listing", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.listing} × {self.quantity} [{self.status}]"


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class Order(UUIDTimeStampedModel):
    """A confirmed intent to buy, with snapshotted delivery and money fields."""

    number = models.CharField(max_length=24, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(
        max_length=24,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING_PAYMENT,
        db_index=True,
    )
    payment_status = models.CharField(
        max_length=24,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    currency = models.CharField(max_length=3, default="NGN")

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    shipping_amount = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")

    # Delivery snapshot (kept even if the linked Address is later removed).
    delivery_address = models.ForeignKey(
        "accounts.Address",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    delivery_recipient_name = models.CharField(max_length=150, blank=True)
    delivery_phone = models.CharField(max_length=20, blank=True)
    delivery_country = models.CharField(max_length=64, blank=True)
    delivery_state = models.ForeignKey(
        "locations.State",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    delivery_lga = models.ForeignKey(
        "locations.LGA",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    delivery_city = models.CharField(max_length=120, blank=True)
    delivery_street = models.CharField(max_length=255, blank=True)
    delivery_landmark = models.CharField(max_length=255, blank=True)
    delivery_postal_code = models.CharField(max_length=16, blank=True)

    shipping_method = models.ForeignKey(
        ShippingMethod,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    contact_name = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    customer_note = models.TextField(blank=True)

    placed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    reservation_released_at = models.DateTimeField(null=True, blank=True)
    stock_committed_at = models.DateTimeField(null=True, blank=True)

    # Idempotency guard: a unique client-supplied checkout token.
    checkout_token = models.CharField(max_length=64, null=True, blank=True, unique=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        indexes: ClassVar[list] = [
            models.Index(fields=["user", "-created_at"], name="order_user_created_idx"),
            models.Index(fields=["status", "-created_at"], name="order_status_created_idx"),
            models.Index(
                fields=["payment_status", "-created_at"], name="order_payment_created_idx"
            ),
        ]

    def __str__(self) -> str:
        return self.number

    @property
    def is_open(self) -> bool:
        return self.status in {
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.PAYMENT_REVIEW,
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
            OrderStatus.READY_FOR_DISPATCH,
            OrderStatus.DISPATCHED,
        }

    @property
    def can_be_cancelled(self) -> bool:
        return self.status in {
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.PAYMENT_REVIEW,
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
            OrderStatus.READY_FOR_DISPATCH,
        }

    def allowed_transitions(self) -> frozenset[str]:
        return ORDER_TRANSITIONS.get(self.status, frozenset())

    def delivery_address_lines(self) -> list[str]:
        parts = [
            self.delivery_street,
            self.delivery_landmark,
            self.delivery_city,
            self.delivery_lga.name if self.delivery_lga_id else "",
            self.delivery_state.name if self.delivery_state_id else "",
            self.delivery_postal_code,
            self.delivery_country,
        ]
        return [part for part in parts if part]


class OrderItem(UUIDTimeStampedModel):
    """A snapshotted order line — immune to later catalogue edits."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    listing = models.ForeignKey(
        "catalog.ProductListing", on_delete=models.PROTECT, related_name="order_items"
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=180)
    product_slug = models.CharField(max_length=200, blank=True)
    sku = models.CharField(max_length=64, blank=True)
    origin_state = models.CharField(max_length=64, blank=True)
    origin_lga = models.CharField(max_length=96, blank=True)
    packaging = models.CharField(max_length=64, blank=True)
    variant_name = models.CharField(max_length=80, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)
    fulfilment_status = models.CharField(
        max_length=16,
        choices=FulfilmentStatus.choices,
        default=FulfilmentStatus.PENDING,
        db_index=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["created_at"]
        verbose_name = "Order item"
        verbose_name_plural = "Order items"
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=Q(quantity__gt="0"), name="chk_orderitem_qty_positive"
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte="0"), name="chk_orderitem_price_nonneg"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product_name} × {self.quantity}"


class OrderStatusHistory(models.Model):
    """Append-only record of every order status change."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24)
    changed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["created_at"]
        verbose_name = "Order status history"
        verbose_name_plural = "Order status history"
        indexes: ClassVar[list] = [
            models.Index(fields=["order", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.order.number}: {self.from_status} → {self.to_status}"

    def save(self, *args, **kwargs):  # type: ignore[override]
        if not self._state.adding:
            raise ValidationError("Order status history is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[override]
        raise ValidationError("Order status history is append-only.")


class Shipment(UUIDTimeStampedModel):
    """A dispatch record for an order (carrier, tracking, status)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="shipments")
    method = models.ForeignKey(
        ShippingMethod,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shipments",
    )
    carrier = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ShipmentStatus.choices,
        default=ShipmentStatus.PENDING,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Shipment"
        verbose_name_plural = "Shipments"

    def __str__(self) -> str:
        return f"Shipment for {self.order.number} [{self.status}]"


# ---------------------------------------------------------------------------
# Bulk quotation requests
# ---------------------------------------------------------------------------


class QuotationRequest(UUIDTimeStampedModel):
    """A bulk/wholesale quotation request from a customer.

    Quotation pricing, approval and acceptance workflows are extended in the
    dedicated quotations phase; Phase 5 captures the request and lets staff
    review/respond.
    """

    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="quotation_requests"
    )
    listing = models.ForeignKey(
        "catalog.ProductListing", on_delete=models.PROTECT, related_name="quotation_requests"
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_requests",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    packaging = models.CharField(max_length=64, blank=True)
    destination_state = models.ForeignKey(
        "locations.State",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_requests",
    )
    destination_lga = models.ForeignKey(
        "locations.LGA",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_requests",
    )
    destination_note = models.CharField(max_length=255, blank=True)
    requirements = models.TextField(blank=True)
    contact_name = models.CharField(max_length=150)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(
        max_length=16,
        choices=QuotationStatus.choices,
        default=QuotationStatus.SUBMITTED,
        db_index=True,
    )
    response_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Quotation request"
        verbose_name_plural = "Quotation requests"
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=Q(quantity__gt="0"), name="chk_quotation_qty_positive"
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Quote request · {self.listing} × {self.quantity}"


__all__ = [
    "Cart",
    "CartItem",
    "CartStatus",
    "FulfilmentStatus",
    "ORDER_TRANSITIONS",
    "Order",
    "OrderItem",
    "OrderStatus",
    "OrderStatusHistory",
    "PAID_FULFILMENT_STATUSES",
    "PaymentStatus",
    "QuotationRequest",
    "QuotationStatus",
    "ReservationStatus",
    "Shipment",
    "ShipmentStatus",
    "ShippingMethod",
    "ShippingRate",
    "ShippingZone",
    "StockReservation",
    "UUIDTimeStampedModel",
]

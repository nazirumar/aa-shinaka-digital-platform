"""Write layer for the order app: cart, checkout, order lifecycle, quotations.

Every mutation is validated server-side and audited where sensitive. Prices are
recomputed from live catalogue data (never trusted from the client) and money is
always ``Decimal``. Stock operations delegate to ``apps.catalog.inventory`` so
the per-warehouse balances and the listing roll-ups stay consistent.

Payment boundary: Phase 5 never contacts a provider. Orders are created
``pending_payment`` and only enter paid fulfilment states through
``confirm_payment`` — an explicit, capability-checked, audited **manual-payment
approval**. Phase 6 adds Paystack and calls the same commit path from a signed
webhook.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability
from apps.catalog import inventory
from apps.catalog.models import (
    ListingStatus,
    ProductListing,
    ProductVariant,
    PublishStatus,
)
from apps.core.audit import record_audit

from . import selectors
from .models import (
    ORDER_TRANSITIONS,
    PAID_FULFILMENT_STATUSES,
    Cart,
    CartItem,
    CartStatus,
    FulfilmentStatus,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentStatus,
    QuotationRequest,
    QuotationStatus,
    ReservationStatus,
    Shipment,
    ShipmentStatus,
    ShippingMethod,
    ShippingRate,
    ShippingZone,
    StockReservation,
)

CANCELLABLE_STATUSES = frozenset(
    {
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.PAYMENT_REVIEW,
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
        OrderStatus.READY_FOR_DISPATCH,
    }
)

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _actor(user):
    return user if getattr(user, "is_authenticated", False) else None


def _money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid amount.") from exc


def _quantity(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid quantity.") from exc
    if amount <= 0:
        raise ValidationError("Quantity must be greater than zero.")
    return amount


def _reservation_ttl() -> timedelta:
    hours = int(getattr(settings, "ORDER_RESERVATION_TTL_HOURS", 48))
    return timedelta(hours=hours)


def _tax_rate() -> Decimal:
    return Decimal(str(getattr(settings, "ORDER_TAX_RATE", "0.00")))


def _assert_sellable(listing: ProductListing, variant: ProductVariant | None = None) -> None:
    if listing.status != ListingStatus.ACTIVE or listing.product.status != PublishStatus.PUBLISHED:
        raise ValidationError("This product is not currently available.")
    if variant is not None and (variant.listing_id != listing.id or not variant.is_active):
        raise ValidationError("The selected option is not available for this product.")


def _generate_order_number() -> str:
    stamp = timezone.localdate().strftime("%Y%m%d")
    for _ in range(10):
        candidate = f"AS-{stamp}-{secrets.token_hex(3).upper()}"
        if not Order.objects.filter(number=candidate).exists():
            return candidate
    return f"AS-{stamp}-{uuid.uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


def get_active_cart(request, *, create: bool = False) -> Cart | None:
    """Return the active cart for the request's user/session (optionally create)."""
    user = request.user
    if getattr(user, "is_authenticated", False):
        cart = selectors.active_cart_for_user(user)
        if cart is None and create:
            cart = Cart.objects.create(user=user)
        return cart

    session_key = request.session.session_key
    if not session_key:
        if not create:
            return None
        request.session.create()
        session_key = request.session.session_key
    cart = selectors.active_cart_for_session(session_key)
    if cart is None and create:
        cart = Cart.objects.create(session_key=session_key)
    if cart is not None and request.session.get("cart_id") != str(cart.pk):
        # Remember the cart in the session: ``auth.login()`` rotates the session
        # key *before* signalling ``user_logged_in``, so the guest-cart merge on
        # login cannot rely on the (now-changed) session key — but session data
        # survives the rotation.
        request.session["cart_id"] = str(cart.pk)
    return cart


def add_to_cart(
    cart: Cart,
    *,
    listing: ProductListing,
    variant: ProductVariant | None = None,
    quantity,
    request=None,
) -> CartItem:
    _assert_sellable(listing, variant)
    amount = _quantity(quantity)

    with transaction.atomic():
        item, created = CartItem.objects.select_for_update().get_or_create(
            cart=cart,
            listing=listing,
            variant=variant,
            defaults={"quantity": amount},
        )
        if not created:
            item.quantity = item.quantity + amount
        available = listing.available_stock
        if item.quantity > available:
            raise ValidationError(
                f"Only {available} of {listing.product.name} ({listing.packaging}) is available."
            )
        item.unit_price_snapshot = selectors.unit_price_for(
            listing, variant=variant, quantity=item.quantity
        )
        item.save()
    return item


def update_cart_item(cart: Cart, item: CartItem, *, quantity, request=None) -> CartItem | None:
    if item.cart_id != cart.id:
        raise PermissionDenied("This item is not in your cart.")
    try:
        amount = Decimal(str(quantity))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid quantity.") from exc
    if amount <= 0:
        remove_cart_item(cart, item)
        return None
    _assert_sellable(item.listing, item.variant)
    available = item.listing.available_stock
    if amount > available:
        raise ValidationError(f"Only {available} available.")
    item.quantity = amount
    item.unit_price_snapshot = selectors.unit_price_for(
        item.listing, variant=item.variant, quantity=amount
    )
    item.save(update_fields=["quantity", "unit_price_snapshot", "updated_at"])
    return item


def remove_cart_item(cart: Cart, item: CartItem) -> None:
    if item.cart_id != cart.id:
        raise PermissionDenied("This item is not in your cart.")
    item.delete()


def clear_cart(cart: Cart) -> None:
    cart.items.all().delete()


def merge_guest_cart(user, *, session_key: str | None = None, cart_id=None) -> Cart | None:
    """Merge a guest cart into the customer's persistent cart on login.

    The guest cart is resolved from the session-stored ``cart_id`` first: Django
    rotates the session key *before* it signals ``user_logged_in``, so the old
    session key is no longer available to the receiver (session data survives the
    rotation). Falls back to the session key for direct callers.
    """
    guest = None
    if cart_id:
        guest = Cart.objects.filter(pk=cart_id, status=CartStatus.ACTIVE).first()
    if guest is None and session_key:
        guest = selectors.active_cart_for_session(session_key)
    if guest is None or guest.user_id == user.id:
        # Nothing to merge, or the "guest" cart already belongs to this user.
        return selectors.active_cart_for_user(user)

    with transaction.atomic():
        guest = Cart.objects.select_for_update().get(pk=guest.pk)
        guest = Cart.objects.select_for_update().get(pk=guest.pk)
        cart = Cart.objects.select_for_update().filter(user=user, status=CartStatus.ACTIVE).first()
        if cart is None:
            guest.user = user
            guest.session_key = ""
            guest.save(update_fields=["user", "session_key", "updated_at"])
            return guest
        for item in guest.items.select_related("listing", "variant"):
            if item.listing.status != ListingStatus.ACTIVE:
                continue
            target, created = CartItem.objects.select_for_update().get_or_create(
                cart=cart,
                listing=item.listing,
                variant=item.variant,
                defaults={"quantity": item.quantity},
            )
            if not created:
                available = item.listing.available_stock
                combined = target.quantity + item.quantity
                target.quantity = min(combined, available) if available > 0 else target.quantity
                target.save(update_fields=["quantity", "updated_at"])
        guest.status = CartStatus.MERGED
        guest.save(update_fields=["status", "updated_at"])
    return cart


# ---------------------------------------------------------------------------
# Checkout & order creation
# ---------------------------------------------------------------------------


def place_order(
    *,
    user,
    cart: Cart,
    address,
    shipping_method: ShippingMethod | None,
    customer_note: str = "",
    checkout_token: str | None = None,
    request=None,
) -> Order:
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Please sign in to place an order.")
    if address is None or address.user_id != user.id:
        raise ValidationError("Choose a delivery address that belongs to your account.")

    if checkout_token:
        existing = Order.objects.filter(checkout_token=checkout_token).first()
        if existing is not None:
            return existing

    with transaction.atomic():
        cart = Cart.objects.select_for_update().get(pk=cart.pk)
        if cart.status != CartStatus.ACTIVE:
            raise ValidationError("This cart has already been checked out.")
        if cart.user_id not in (None, user.id):
            raise PermissionDenied("This cart does not belong to you.")

        summary = selectors.cart_totals(cart)
        if not summary["lines"]:
            raise ValidationError("Your cart is empty.")
        if summary["issues"]:
            raise ValidationError(summary["issues"][0])

        rate = selectors.shipping_rate_for(address.state, shipping_method)
        if rate is None:
            raise ValidationError(
                f"We do not yet deliver to {address.state.name} with the selected method."
            )

        subtotal = _money(summary["subtotal"])
        shipping_amount = _money(rate.fee_for(subtotal))
        tax_amount = _money(subtotal * _tax_rate())
        discount_amount = ZERO
        grand_total = _money(subtotal + shipping_amount + tax_amount - discount_amount)

        order = Order.objects.create(
            number=_generate_order_number(),
            user=user,
            status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            currency="NGN",
            subtotal=subtotal,
            shipping_amount=shipping_amount,
            discount_amount=discount_amount,
            tax_amount=tax_amount,
            grand_total=grand_total,
            delivery_address=address,
            delivery_recipient_name=address.recipient_name,
            delivery_phone=address.phone,
            delivery_country=address.country,
            delivery_state=address.state,
            delivery_lga=address.lga,
            delivery_city=address.city,
            delivery_street=address.street_address,
            delivery_landmark=address.landmark,
            delivery_postal_code=address.postal_code,
            shipping_method=shipping_method,
            contact_name=address.recipient_name,
            contact_phone=address.phone,
            customer_note=customer_note,
            placed_at=timezone.now(),
            expires_at=timezone.now() + _reservation_ttl(),
            checkout_token=checkout_token,
        )

        for line in summary["lines"]:
            listing = line["listing"]
            variant = line["variant"]
            quantity = line["quantity"]
            unit_price = _money(line["unit_price"])
            # Choose the fulfilment warehouse deliberately (default when
            # single-warehouse, otherwise one that can cover the line).
            warehouse = inventory.select_warehouse(listing, quantity=quantity, variant=variant)
            item = OrderItem.objects.create(
                order=order,
                listing=listing,
                variant=variant,
                product_name=listing.product.name,
                product_slug=listing.product.slug,
                sku=str(listing.pk),
                origin_state=listing.state.name,
                origin_lga=listing.lga.name,
                packaging=listing.packaging,
                variant_name=variant.name if variant else "",
                quantity=quantity,
                unit_price=unit_price,
                line_total=_money(unit_price * quantity),
            )
            inventory.place_reservation(
                listing,
                quantity=quantity,
                variant=variant,
                warehouse=warehouse,
            )
            StockReservation.objects.create(
                order=order,
                order_item=item,
                listing=listing,
                variant=variant,
                warehouse=warehouse,
                quantity=quantity,
                status=ReservationStatus.ACTIVE,
                expires_at=order.expires_at,
            )

        OrderStatusHistory.objects.create(
            order=order,
            from_status="",
            to_status=OrderStatus.PENDING_PAYMENT,
            changed_by=_actor(user),
            reason="Order placed, awaiting payment.",
        )
        cart.status = CartStatus.CONVERTED
        cart.checked_out_at = timezone.now()
        cart.save(update_fields=["status", "checked_out_at", "updated_at"])

        record_audit(
            actor=user,
            action="orders.order.create",
            target=order,
            after={"number": order.number, "total": str(order.grand_total)},
            request=request,
        )

    # Phase 6: issue the (unpaid) invoice for the new order. Imported lazily to
    # avoid an import cycle (payments imports this module).
    from . import payments as payment_services

    payment_services.generate_invoice(order, request=request)

    # Phase 10: mirror the event into the customer's in-app notification feed.
    from apps.notifications import events as notification_events

    notification_events.order_created(order)
    return order


# ---------------------------------------------------------------------------
# Reservation lifecycle
# ---------------------------------------------------------------------------


def _release_active_reservations(order: Order, *, status: str, actor=None) -> int:
    released = 0
    reservations = (
        order.reservations.select_for_update()
        .filter(status=ReservationStatus.ACTIVE)
        .select_related("listing")
    )
    for reservation in reservations:
        inventory.release_reservation(
            reservation.listing,
            quantity=reservation.quantity,
            variant=reservation.variant,
            warehouse=reservation.warehouse,
        )
        reservation.status = status
        reservation.released_at = timezone.now()
        reservation.save(update_fields=["status", "released_at", "updated_at"])
        released += 1
    if released:
        released_at = timezone.now()
        Order.objects.filter(pk=order.pk).update(reservation_released_at=released_at)
        order.reservation_released_at = released_at
    return released


def _commit_reservations(order: Order, *, actor=None) -> int:
    committed = 0
    reservations = (
        order.reservations.select_for_update()
        .filter(status=ReservationStatus.ACTIVE)
        .select_related("listing")
    )
    for reservation in reservations:
        inventory.commit_reservation(
            reservation.listing,
            quantity=reservation.quantity,
            variant=reservation.variant,
            warehouse=reservation.warehouse,
            reference=order.number,
            actor=actor,
        )
        reservation.status = ReservationStatus.COMMITTED
        reservation.committed_at = timezone.now()
        reservation.save(update_fields=["status", "committed_at", "updated_at"])
        if reservation.order_item_id:
            OrderItem.objects.filter(pk=reservation.order_item_id).update(
                fulfilment_status=FulfilmentStatus.RESERVED
            )
        committed += 1
    return committed


def _restock_committed(order: Order, *, actor=None) -> None:
    """Return committed stock to the ledger when a paid order is cancelled."""
    for item in order.items.select_related("listing"):
        reservation = item.reservations.filter(status=ReservationStatus.COMMITTED).first()
        warehouse = reservation.warehouse if reservation else None
        inventory.adjust_stock(
            item.listing,
            delta=item.quantity,
            warehouse=warehouse,
            kind="return",
            reference=order.number,
            note="Order cancelled, stock returned",
            actor=actor,
        )


# ---------------------------------------------------------------------------
# Order state machine
# ---------------------------------------------------------------------------


def _apply_transition(
    order: Order, *, to_status: str, actor, reason: str = "", request=None
) -> Order:
    previous = order.status
    fields = ["status", "updated_at"]
    order.status = to_status
    if to_status == OrderStatus.CANCELLED and order.cancelled_at is None:
        order.cancelled_at = timezone.now()
        fields.append("cancelled_at")
    order.save(update_fields=fields)
    OrderStatusHistory.objects.create(
        order=order,
        from_status=previous,
        to_status=to_status,
        changed_by=_actor(actor),
        reason=reason,
    )
    record_audit(
        actor=actor,
        action="orders.order.status",
        target=order,
        after={"number": order.number, "from_status": previous, "status": to_status},
        request=request,
    )
    if to_status == OrderStatus.DISPATCHED:
        # Phase 10: dispatch is a genuine customer-facing milestone.
        from apps.notifications import events as notification_events

        notification_events.order_dispatched(order)
    return order


def transition_order(
    order: Order, *, to_status: str, actor=None, reason: str = "", request=None
) -> Order:
    """Validate and apply an explicit order-status transition."""
    if to_status not in OrderStatus.values:
        raise ValidationError(f"Unknown order status '{to_status}'.")

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if to_status == order.status:
            return order
        if to_status not in ORDER_TRANSITIONS.get(order.status, frozenset()):
            raise ValidationError(f"An order in '{order.status}' cannot move to '{to_status}'.")
        if to_status in PAID_FULFILMENT_STATUSES and order.payment_status != PaymentStatus.PAID:
            raise ValidationError(
                "Payment must be verified (or manually approved) before this step."
            )
        if to_status in {OrderStatus.CANCELLED, OrderStatus.EXPIRED}:
            # A paid order already had its reservations committed, so returning
            # the stock (not just releasing active holds) keeps the ledger true.
            if order.stock_committed_at:
                _restock_committed(order, actor=actor)
            else:
                _release_active_reservations(order, status=ReservationStatus.RELEASED, actor=actor)
        return _apply_transition(
            order, to_status=to_status, actor=actor, reason=reason, request=request
        )


def submit_payment_review(order: Order, *, actor=None, note: str = "", request=None) -> Order:
    """Customer/staff signals a manual payment for review (never marks it paid)."""
    if order.status not in {OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_REVIEW}:
        raise ValidationError("This order is not awaiting payment.")
    if order.user_id != getattr(actor, "id", None) and not has_capability(
        actor, Capability.ORDERS_MANAGE
    ):
        raise PermissionDenied("You cannot update this order.")
    return transition_order(
        order,
        to_status=OrderStatus.PAYMENT_REVIEW,
        actor=actor,
        reason=note or "Payment proof submitted for review.",
        request=request,
    )


def settle_order(
    order: Order, *, actor=None, reference: str = "", note: str = "", request=None
) -> Order:
    """Commit reservations and mark a paid order confirmed (idempotent core).

    Shared by manual finance approval and the verified Paystack / bank-transfer
    paths (Phase 6). Provider-specific checks happen in ``apps.orders.payments``;
    this only enforces the order-level invariants, inside one transaction, and is
    safe to call twice.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.payment_status == PaymentStatus.PAID:
            return order
        if order.status not in {OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_REVIEW}:
            raise ValidationError("This order cannot be confirmed from its current status.")

        committed = _commit_reservations(order, actor=actor)
        order.payment_status = PaymentStatus.PAID
        order.stock_committed_at = timezone.now()
        order.save(update_fields=["payment_status", "stock_committed_at", "updated_at"])
        note_parts = ["Payment settled."]
        if committed:
            note_parts.append(f"{committed} reservation(s) committed to stock.")
        if reference:
            note_parts.append(f"Reference: {reference}.")
        if note:
            note_parts.append(note)
        _apply_transition(
            order,
            to_status=OrderStatus.CONFIRMED,
            actor=actor,
            reason=" ".join(note_parts),
            request=request,
        )
    return order


def confirm_payment(
    order: Order, *, actor, reference: str = "", note: str = "", request=None
) -> Order:
    """Authorised manual-payment approval → commit stock and confirm the order.

    Idempotent and refuses to run for callers without the finance capability.
    Phase 6's verified provider paths reuse :func:`settle_order` directly.
    """
    if not has_capability(actor, Capability.FINANCE_MANAGE):
        raise PermissionDenied("You are not authorised to confirm payments.")
    if order.payment_status == PaymentStatus.PAID:
        return order

    settle_order(
        order,
        actor=actor,
        reference=reference,
        note=note or "Payment approved manually.",
        request=request,
    )
    record_audit(
        actor=actor,
        action="orders.order.payment_confirmed",
        target=order,
        after={"number": order.number, "reference": reference},
        request=request,
    )
    return order


def cancel_order(order: Order, *, actor=None, reason: str = "", request=None) -> Order:
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status not in CANCELLABLE_STATUSES:
            raise ValidationError("This order can no longer be cancelled.")
        if order.stock_committed_at:
            _restock_committed(order, actor=actor)
        else:
            _release_active_reservations(order, status=ReservationStatus.RELEASED, actor=actor)
        if reason:
            order.cancelled_reason = reason
            order.save(update_fields=["cancelled_reason", "updated_at"])
        return _apply_transition(
            order, to_status=OrderStatus.CANCELLED, actor=actor, reason=reason, request=request
        )


def expire_orders(*, now=None, limit: int = 500) -> int:
    """Expire overdue pending orders and release their reservations exactly once."""
    moment = now or timezone.now()
    overdue = list(
        Order.objects.filter(status=OrderStatus.PENDING_PAYMENT, expires_at__lt=moment).values_list(
            "pk", flat=True
        )[:limit]
    )
    expired = 0
    for pk in overdue:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=pk)
            if order.status != OrderStatus.PENDING_PAYMENT:
                continue
            _release_active_reservations(order, status=ReservationStatus.EXPIRED, actor=None)
            _apply_transition(
                order,
                to_status=OrderStatus.EXPIRED,
                actor=None,
                reason="Reservation expired before payment.",
            )
            expired += 1
    return expired


# ---------------------------------------------------------------------------
# Shipping configuration
# ---------------------------------------------------------------------------


def create_shipping_zone(
    *, name, code, description="", states=None, is_active=True, actor=None, request=None
) -> ShippingZone:
    zone = ShippingZone(name=name, code=code, description=description, is_active=is_active)
    zone.full_clean()
    zone.save()
    if states:
        zone.states.set(states)
    record_audit(
        actor=actor,
        action="orders.shipping_zone.create",
        target=zone,
        after={"name": zone.name, "code": zone.code},
        request=request,
    )
    return zone


def update_shipping_zone(
    zone,
    *,
    name=None,
    code=None,
    description=None,
    states=None,
    is_active=None,
    actor=None,
    request=None,
) -> ShippingZone:
    for field, value in (
        ("name", name),
        ("code", code),
        ("description", description),
        ("is_active", is_active),
    ):
        if value is not None:
            setattr(zone, field, value)
    zone.full_clean()
    zone.save()
    if states is not None:
        zone.states.set(states)
    record_audit(
        actor=actor,
        action="orders.shipping_zone.update",
        target=zone,
        after={"name": zone.name},
        request=request,
    )
    return zone


def create_shipping_method(
    *, name, code, description="", sort_order=0, is_active=True, actor=None, request=None
) -> ShippingMethod:
    method = ShippingMethod(
        name=name, code=code, description=description, sort_order=sort_order, is_active=is_active
    )
    method.full_clean()
    method.save()
    record_audit(
        actor=actor,
        action="orders.shipping_method.create",
        target=method,
        after={"name": method.name},
        request=request,
    )
    return method


def update_shipping_method(
    method,
    *,
    name=None,
    code=None,
    description=None,
    sort_order=None,
    is_active=None,
    actor=None,
    request=None,
) -> ShippingMethod:
    for field, value in (
        ("name", name),
        ("code", code),
        ("description", description),
        ("sort_order", sort_order),
        ("is_active", is_active),
    ):
        if value is not None:
            setattr(method, field, value)
    method.full_clean()
    method.save()
    record_audit(
        actor=actor,
        action="orders.shipping_method.update",
        target=method,
        after={"name": method.name},
        request=request,
    )
    return method


def create_shipping_rate(
    *,
    zone,
    method,
    fee,
    free_over=None,
    min_order_amount="0.00",
    is_active=True,
    actor=None,
    request=None,
) -> ShippingRate:
    rate = ShippingRate(
        zone=zone,
        method=method,
        fee=_money(fee),
        free_over=free_over,
        min_order_amount=min_order_amount,
        is_active=is_active,
    )
    rate.full_clean()
    rate.save()
    record_audit(
        actor=actor,
        action="orders.shipping_rate.create",
        target=rate,
        after={"zone": zone.code, "method": method.code, "fee": str(rate.fee)},
        request=request,
    )
    return rate


def update_shipping_rate(
    rate,
    *,
    fee=None,
    free_over=None,
    min_order_amount=None,
    is_active=None,
    actor=None,
    request=None,
) -> ShippingRate:
    if fee is not None:
        rate.fee = _money(fee)
    if free_over is not None:
        rate.free_over = free_over
    if min_order_amount is not None:
        rate.min_order_amount = min_order_amount
    if is_active is not None:
        rate.is_active = is_active
    rate.full_clean()
    rate.save()
    record_audit(
        actor=actor,
        action="orders.shipping_rate.update",
        target=rate,
        after={"fee": str(rate.fee)},
        request=request,
    )
    return rate


def create_shipment(
    order, *, method=None, carrier="", tracking_number="", notes="", actor=None, request=None
) -> Shipment:
    shipment = Shipment.objects.create(
        order=order,
        method=method,
        carrier=carrier,
        tracking_number=tracking_number,
        notes=notes,
        handled_by=_actor(actor),
    )
    record_audit(
        actor=actor,
        action="orders.shipment.create",
        target=order,
        after={"shipment": str(shipment.id)},
        request=request,
    )
    return shipment


def update_shipment_status(
    shipment, *, status, tracking_number=None, notes=None, actor=None, request=None
) -> Shipment:
    if status not in ShipmentStatus.values:
        raise ValidationError(f"Unknown shipment status '{status}'.")
    shipment.status = status
    if tracking_number is not None:
        shipment.tracking_number = tracking_number
    if notes is not None:
        shipment.notes = notes
    if status == ShipmentStatus.IN_TRANSIT and shipment.dispatched_at is None:
        shipment.dispatched_at = timezone.now()
    if status == ShipmentStatus.DELIVERED and shipment.delivered_at is None:
        shipment.delivered_at = timezone.now()
    shipment.handled_by = _actor(actor)
    shipment.save()
    record_audit(
        actor=actor,
        action="orders.shipment.status",
        target=shipment.order,
        after={"shipment": str(shipment.id), "status": status},
        request=request,
    )
    return shipment


# ---------------------------------------------------------------------------
# Bulk quotation requests
# ---------------------------------------------------------------------------


def create_quotation_request(
    *,
    user,
    listing,
    variant=None,
    quantity,
    packaging="",
    destination_state=None,
    destination_lga=None,
    destination_note="",
    requirements="",
    contact_name,
    contact_email,
    contact_phone="",
    request=None,
) -> QuotationRequest:
    amount = _quantity(quantity)
    quotation = QuotationRequest.objects.create(
        user=_actor(user),
        listing=listing,
        variant=variant,
        quantity=amount,
        packaging=packaging or listing.packaging,
        destination_state=destination_state,
        destination_lga=destination_lga,
        destination_note=destination_note,
        requirements=requirements,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        status=QuotationStatus.SUBMITTED,
    )
    record_audit(
        actor=_actor(user),
        action="orders.quotation.create",
        target=quotation,
        after={"listing": str(listing.pk), "quantity": str(amount)},
        request=request,
    )
    return quotation


def update_quotation(
    quotation, *, status, actor, response_note="", request=None
) -> QuotationRequest:
    if not has_capability(actor, Capability.ORDERS_MANAGE):
        raise PermissionDenied("You are not authorised to review quotation requests.")
    if status not in QuotationStatus.values:
        raise ValidationError(f"Unknown quotation status '{status}'.")
    quotation.status = status
    quotation.response_note = response_note
    quotation.reviewed_by = _actor(actor)
    quotation.reviewed_at = timezone.now()
    quotation.save(
        update_fields=["status", "response_note", "reviewed_by", "reviewed_at", "updated_at"]
    )
    record_audit(
        actor=actor,
        action="orders.quotation.status",
        target=quotation,
        after={"status": status},
        request=request,
    )
    return quotation


__all__ = [
    "add_to_cart",
    "cancel_order",
    "clear_cart",
    "confirm_payment",
    "create_quotation_request",
    "create_shipment",
    "create_shipping_method",
    "create_shipping_rate",
    "create_shipping_zone",
    "expire_orders",
    "get_active_cart",
    "merge_guest_cart",
    "place_order",
    "remove_cart_item",
    "transition_order",
    "update_cart_item",
    "update_quotation",
    "update_shipment_status",
    "update_shipping_method",
    "update_shipping_rate",
    "update_shipping_zone",
]

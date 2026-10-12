"""Phase 5 tests: reservations, order state machine, payment approval, expiry."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from catalog_helpers import make_sellable_product
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from orders_helpers import make_address, make_shipping

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.catalog.models import StockMovement, StockMovementKind
from apps.orders import services
from apps.orders.models import (
    Cart,
    Order,
    OrderStatus,
    PaymentStatus,
    ReservationStatus,
    StockReservation,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _catalog_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def finance_user(db) -> User:
    user = User.objects.create_user(
        email="finance@example.com",
        password="test-pass-12345",
        first_name="Femi",
        last_name="Ade",
        role=UserRole.FINANCE_OFFICER,
        is_staff=True,
    )
    sync_user_groups(user)
    return user


def _make_order(customer, *, quantity="2", stock="20.000", price="25000.00", fee="1500.00"):
    _, listing = make_sellable_product(stock=stock, price=price)
    zone, method, rate = make_shipping(listing.state, fee=fee)
    address = make_address(customer, state=listing.state)
    cart = Cart.objects.create(user=customer)
    services.add_to_cart(cart, listing=listing, quantity=quantity)
    order = services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token=f"tok-{listing.pk}",
    )
    return order, listing


# ---------------------------------------------------------------------------
# Order creation invariants
# ---------------------------------------------------------------------------


def test_order_number_format(customer):
    order, _ = _make_order(customer)

    assert re.fullmatch(r"AS-\d{8}-[0-9A-F]{6}", order.number)


def test_order_creation_writes_status_history(customer):
    order, _ = _make_order(customer)

    entry = order.history.get()
    assert entry.from_status == ""
    assert entry.to_status == OrderStatus.PENDING_PAYMENT


def test_order_status_history_is_append_only(customer):
    order, _ = _make_order(customer)
    entry = order.history.first()

    entry.to_status = OrderStatus.CONFIRMED
    with pytest.raises(ValidationError):
        entry.save()

    with pytest.raises(ValidationError):
        entry.delete()


# ---------------------------------------------------------------------------
# Payment approval boundary
# ---------------------------------------------------------------------------


def test_customer_cannot_confirm_payment(customer):
    order, _ = _make_order(customer)

    with pytest.raises(PermissionDenied):
        services.confirm_payment(order, actor=customer)


def test_sales_officer_cannot_confirm_payment(customer, staff_user):
    order, _ = _make_order(customer)

    with pytest.raises(PermissionDenied):
        services.confirm_payment(order, actor=staff_user)


def test_finance_officer_confirms_payment_and_commits_stock(customer, finance_user):
    order, listing = _make_order(customer, quantity="2", stock="20.000")

    result = services.confirm_payment(order, actor=finance_user, reference="TRF-123")

    assert result.pk == order.pk
    order.refresh_from_db()
    assert order.status == OrderStatus.CONFIRMED
    assert order.payment_status == PaymentStatus.PAID
    assert order.stock_committed_at is not None
    assert order.reservations.get().status == ReservationStatus.COMMITTED

    listing.refresh_from_db()
    assert listing.stock_on_hand == Decimal("18.000")
    assert listing.stock_reserved == Decimal("0.000")
    assert StockMovement.objects.filter(listing=listing, kind=StockMovementKind.SALE).exists()


def test_confirm_payment_is_idempotent(customer, finance_user):
    order, listing = _make_order(customer, quantity="2", stock="20.000")

    services.confirm_payment(order, actor=finance_user)
    services.confirm_payment(order, actor=finance_user)

    listing.refresh_from_db()
    assert listing.stock_on_hand == Decimal("18.000")
    assert StockReservation.objects.filter(order=order).count() == 1


def test_confirm_payment_rejects_expired_order(customer, finance_user):
    order, _ = _make_order(customer)
    Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(hours=1))
    services.expire_orders()

    with pytest.raises(ValidationError):
        services.confirm_payment(order, actor=finance_user)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def test_fulfilment_requires_verified_payment(customer, finance_user):
    order, _ = _make_order(customer)

    with pytest.raises(ValidationError):
        services.transition_order(order, to_status=OrderStatus.PROCESSING, actor=finance_user)


def test_invalid_transition_rejected(customer, finance_user):
    order, _ = _make_order(customer)

    with pytest.raises(ValidationError):
        services.transition_order(order, to_status=OrderStatus.DISPATCHED, actor=finance_user)


def test_unpaid_fulfilment_chain_after_confirmation(customer, finance_user):
    order, _ = _make_order(customer)
    services.confirm_payment(order, actor=finance_user)

    services.transition_order(order, to_status=OrderStatus.PROCESSING, actor=finance_user)
    services.transition_order(order, to_status=OrderStatus.READY_FOR_DISPATCH, actor=finance_user)
    services.transition_order(order, to_status=OrderStatus.DISPATCHED, actor=finance_user)
    services.transition_order(order, to_status=OrderStatus.DELIVERED, actor=finance_user)
    order.refresh_from_db()

    assert order.status == OrderStatus.DELIVERED


def test_submit_payment_review_never_marks_paid(customer):
    order, _ = _make_order(customer)

    services.submit_payment_review(order, actor=customer, note="Bank transfer sent")
    order.refresh_from_db()

    assert order.status == OrderStatus.PAYMENT_REVIEW
    assert order.payment_status == PaymentStatus.PENDING


# ---------------------------------------------------------------------------
# Cancellation & expiry
# ---------------------------------------------------------------------------


def test_cancel_releases_active_reservation(customer):
    order, listing = _make_order(customer, quantity="3", stock="10.000")

    services.cancel_order(order, actor=customer, reason="Changed my mind")

    order.refresh_from_db()
    listing.refresh_from_db()
    assert order.status == OrderStatus.CANCELLED
    assert order.cancelled_at is not None
    assert order.reservations.get().status == ReservationStatus.RELEASED
    assert listing.stock_reserved == Decimal("0.000")
    assert listing.stock_on_hand == Decimal("10.000")


def test_cancel_committed_order_returns_stock(customer, finance_user):
    order, listing = _make_order(customer, quantity="2", stock="20.000")
    services.confirm_payment(order, actor=finance_user)
    listing.refresh_from_db()
    assert listing.stock_on_hand == Decimal("18.000")

    services.cancel_order(order, actor=finance_user, reason="Out of stock")

    order.refresh_from_db()
    listing.refresh_from_db()
    assert order.status == OrderStatus.CANCELLED
    assert listing.stock_on_hand == Decimal("20.000")


def test_cancel_rejected_after_dispatch(customer, finance_user):
    order, _ = _make_order(customer)
    services.confirm_payment(order, actor=finance_user)
    services.transition_order(order, to_status=OrderStatus.PROCESSING, actor=finance_user)
    services.transition_order(order, to_status=OrderStatus.READY_FOR_DISPATCH, actor=finance_user)
    services.transition_order(order, to_status=OrderStatus.DISPATCHED, actor=finance_user)

    with pytest.raises(ValidationError):
        services.cancel_order(order, actor=finance_user)


def test_expire_orders_releases_and_is_idempotent(customer):
    order, listing = _make_order(customer, quantity="2", stock="20.000")
    Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(hours=1))

    expired = services.expire_orders()

    assert expired == 1
    order.refresh_from_db()
    listing.refresh_from_db()
    assert order.status == OrderStatus.EXPIRED
    assert order.reservations.get().status == ReservationStatus.EXPIRED
    assert listing.stock_reserved == Decimal("0.000")
    assert listing.stock_on_hand == Decimal("20.000")
    assert services.expire_orders() == 0


def test_expire_orders_leaves_fresh_orders_alone(customer):
    order, _ = _make_order(customer)

    assert services.expire_orders() == 0

    order.refresh_from_db()
    assert order.status == OrderStatus.PENDING_PAYMENT

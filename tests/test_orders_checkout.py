"""Phase 5 tests: checkout, order creation, server totals and idempotency."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from catalog_helpers import make_sellable_product
from django.core.exceptions import ValidationError
from django.urls import reverse
from orders_helpers import make_address, make_shipping

from apps.orders import services
from apps.orders.models import (
    Cart,
    CartItem,
    CartStatus,
    Order,
    OrderStatus,
    PaymentStatus,
    ReservationStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _catalog_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def _login(client, user) -> None:
    assert client.login(email=user.email, password="test-pass-12345")


def _cart_with(user, listing, quantity="2") -> Cart:
    cart = Cart.objects.create(user=user)
    services.add_to_cart(cart, listing=listing, quantity=quantity)
    return cart


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


def test_checkout_requires_login(client):
    response = client.get(reverse("orders:checkout"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_checkout_redirects_when_cart_empty(client, customer):
    _login(client, customer)

    response = client.get(reverse("orders:checkout"))

    assert response.status_code == 302
    assert response.url == reverse("orders:cart")


# ---------------------------------------------------------------------------
# Order creation
# ---------------------------------------------------------------------------


def test_place_order_snapshots_totals_and_reserves_stock(customer):
    _, listing = make_sellable_product(stock="20.000", price="25000.00")
    zone, method, rate = make_shipping(listing.state, fee="1500.00")
    address = make_address(customer, state=listing.state)
    cart = _cart_with(customer, listing, quantity="2")

    order = services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token="tok-totals",
    )

    assert re.fullmatch(r"AS-\d{8}-[0-9A-F]{6}", order.number)
    assert order.status == OrderStatus.PENDING_PAYMENT
    assert order.payment_status == PaymentStatus.PENDING
    assert order.subtotal == Decimal("50000.00")
    assert order.shipping_amount == Decimal("1500.00")
    assert order.tax_amount == Decimal("0.00")
    assert order.grand_total == Decimal("51500.00")

    item = order.items.get()
    assert order.items.count() == 1
    assert item.quantity == Decimal("2.000")
    assert item.unit_price == Decimal("25000.00")
    assert item.line_total == Decimal("50000.00")
    assert item.product_name == listing.product.name

    listing.refresh_from_db()
    assert listing.stock_on_hand == Decimal("20.000")
    assert listing.stock_reserved == Decimal("2.000")
    reservation = order.reservations.get()
    assert reservation.status == ReservationStatus.ACTIVE
    assert reservation.quantity == Decimal("2.000")

    cart.refresh_from_db()
    assert cart.status == CartStatus.CONVERTED


def test_free_shipping_threshold_is_applied(customer):
    _, listing = make_sellable_product(stock="20.000", price="25000.00")
    zone, method, rate = make_shipping(listing.state, fee="1500.00", free_over="40000.00")
    address = make_address(customer, state=listing.state)
    cart = _cart_with(customer, listing, quantity="2")

    order = services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token="tok-free",
    )

    assert order.subtotal == Decimal("50000.00")
    assert order.shipping_amount == Decimal("0.00")
    assert order.grand_total == Decimal("50000.00")


def test_place_order_is_idempotent_per_token(customer):
    _, listing = make_sellable_product(stock="20.000")
    zone, method, rate = make_shipping(listing.state)
    address = make_address(customer, state=listing.state)
    cart = _cart_with(customer, listing, quantity="2")

    first = services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token="tok-once",
    )
    second = services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token="tok-once",
    )

    assert first.pk == second.pk
    assert Order.objects.count() == 1
    listing.refresh_from_db()
    assert listing.stock_reserved == Decimal("2.000")


def test_place_order_requires_configured_shipping_rate(customer):
    _, listing = make_sellable_product(stock="20.000")
    address = make_address(customer, state=listing.state)
    method = services.create_shipping_method(name="Courier", code="courier")
    cart = _cart_with(customer, listing, quantity="2")

    with pytest.raises(ValidationError):
        services.place_order(
            user=customer,
            cart=cart,
            address=address,
            shipping_method=method,
            checkout_token="tok-norate",
        )

    assert Order.objects.count() == 0
    listing.refresh_from_db()
    assert listing.stock_reserved == Decimal("0.000")


def test_place_order_rejects_stale_cart_exceeding_stock(customer):
    _, listing = make_sellable_product(stock="2.000")
    zone, method, rate = make_shipping(listing.state)
    address = make_address(customer, state=listing.state)
    cart = Cart.objects.create(user=customer)
    # Bypass add_to_cart's guard to simulate a cart that went stale.
    CartItem.objects.create(cart=cart, listing=listing, quantity=Decimal("5.000"))

    with pytest.raises(ValidationError):
        services.place_order(
            user=customer,
            cart=cart,
            address=address,
            shipping_method=method,
            checkout_token="tok-over",
        )

    assert Order.objects.count() == 0
    listing.refresh_from_db()
    assert listing.stock_reserved == Decimal("0.000")
    assert listing.stock_on_hand == Decimal("2.000")


# ---------------------------------------------------------------------------
# Checkout view
# ---------------------------------------------------------------------------


def test_checkout_view_creates_pending_order(client, customer):
    _, listing = make_sellable_product(stock="20.000", price="25000.00")
    address = make_address(customer, state=listing.state)
    zone, method, rate = make_shipping(listing.state)
    _login(client, customer)
    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "2"})

    response = client.post(
        reverse("orders:checkout"),
        {
            "address": str(address.pk),
            "shipping_method": str(method.pk),
            "customer_note": "Leave at the gate",
            "checkout_token": "tok-view",
        },
    )

    order = Order.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("orders:order_detail", args=[order.number])
    assert order.status == OrderStatus.PENDING_PAYMENT
    assert order.payment_status == PaymentStatus.PENDING
    assert order.customer_note == "Leave at the gate"
    assert order.grand_total == Decimal("50000.00") + rate.fee


def test_checkout_view_ignores_client_supplied_price(client, customer):
    _, listing = make_sellable_product(stock="20.000", price="25000.00")
    address = make_address(customer, state=listing.state)
    zone, method, rate = make_shipping(listing.state)
    _login(client, customer)
    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "2"})

    client.post(
        reverse("orders:checkout"),
        {
            "address": str(address.pk),
            "shipping_method": str(method.pk),
            "unit_price": "1.00",
            "grand_total": "2.00",
            "checkout_token": "tok-tamper",
        },
    )

    order = Order.objects.get()
    assert order.items.get().unit_price == Decimal("25000.00")
    assert order.grand_total == Decimal("50000.00") + rate.fee


def test_checkout_view_without_rate_creates_no_order(client, customer):
    _, listing = make_sellable_product(stock="20.000")
    address = make_address(customer, state=listing.state)
    services.create_shipping_method(name="Courier", code="courier")
    _login(client, customer)
    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "2"})

    response = client.post(
        reverse("orders:checkout"),
        {"address": str(address.pk), "shipping_method": "", "checkout_token": "tok-view-none"},
    )

    assert response.status_code == 200
    assert Order.objects.count() == 0


def test_shipping_options_partial_only_lists_configured_rates(client, customer):
    _, listing = make_sellable_product(stock="20.000")
    zone, method, rate = make_shipping(listing.state)
    address = make_address(customer, state=listing.state)
    _login(client, customer)

    response = client.get(reverse("orders:checkout_shipping_options"), {"address": str(address.pk)})

    assert response.status_code == 200
    assert method.name.encode() in response.content


def test_reservation_status_defaults_to_active(customer):
    _, listing = make_sellable_product(stock="20.000")
    zone, method, rate = make_shipping(listing.state)
    address = make_address(customer, state=listing.state)
    cart = _cart_with(customer, listing, quantity="1")

    order = services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token="tok-res",
    )

    assert order.reservations.get().status == ReservationStatus.ACTIVE
    assert order.expires_at is not None

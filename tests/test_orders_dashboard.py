"""Phase 5 tests: staff orders dashboard access, listings, actions, config."""

from __future__ import annotations

import pytest
from catalog_helpers import make_sellable_product, make_state
from django.urls import reverse
from orders_helpers import make_address, make_shipping

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.orders import services
from apps.orders.models import Cart, OrderStatus, PaymentStatus, ShippingZone

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _catalog_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def _make(role, email, **extra) -> User:
    user = User.objects.create_user(
        email=email,
        password="test-pass-12345",
        role=role,
        is_staff=True,
        first_name="Bala",
        last_name="Yusuf",
        **extra,
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def orders_manager(db) -> User:
    return _make(UserRole.SALES_OFFICER, "sales-dash@example.com")


@pytest.fixture
def finance_user(db) -> User:
    return _make(UserRole.FINANCE_OFFICER, "finance-dash@example.com")


def _order(customer):
    _, listing = make_sellable_product(stock="20.000")
    zone, method, rate = make_shipping(listing.state)
    address = make_address(customer, state=listing.state)
    cart = Cart.objects.create(user=customer)
    services.add_to_cart(cart, listing=listing, quantity="2")
    return services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token=f"tok-{listing.pk}",
    )


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_orders_dashboard_requires_login(client):
    response = client.get(reverse("orders_dashboard:home"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_customer_is_forbidden(client, customer):
    assert client.login(email=customer.email, password="test-pass-12345")

    assert client.get(reverse("orders_dashboard:home")).status_code == 403


def test_orders_manager_can_view_home(client, orders_manager):
    assert client.login(email=orders_manager.email, password="test-pass-12345")

    response = client.get(reverse("orders_dashboard:home"))

    assert response.status_code == 200
    assert "counts" in response.context


def test_order_list_and_detail_render(client, orders_manager, customer):
    order = _order(customer)
    assert client.login(email=orders_manager.email, password="test-pass-12345")

    assert client.get(reverse("orders_dashboard:order_list")).status_code == 200
    detail = client.get(reverse("orders_dashboard:order_detail", args=[order.number]))
    assert detail.status_code == 200
    assert order.number.encode() in detail.content


# ---------------------------------------------------------------------------
# Order actions
# ---------------------------------------------------------------------------


def test_order_status_transition_is_gated_by_payment(client, orders_manager, customer):
    order = _order(customer)
    assert client.login(email=orders_manager.email, password="test-pass-12345")

    client.post(
        reverse("orders_dashboard:order_status", args=[order.number]),
        {"status": OrderStatus.PROCESSING, "reason": "rush"},
    )

    order.refresh_from_db()
    assert order.status == OrderStatus.PENDING_PAYMENT


def test_orders_manager_cannot_confirm_payment(client, orders_manager, customer):
    order = _order(customer)
    assert client.login(email=orders_manager.email, password="test-pass-12345")

    response = client.post(
        reverse("orders_dashboard:order_confirm_payment", args=[order.number]), {}
    )

    assert response.status_code == 403
    order.refresh_from_db()
    assert order.payment_status == PaymentStatus.PENDING


def test_finance_confirms_payment_via_dashboard(client, finance_user, customer):
    order = _order(customer)
    assert client.login(email=finance_user.email, password="test-pass-12345")

    response = client.post(
        reverse("orders_dashboard:order_confirm_payment", args=[order.number]),
        {"reference": "TRF-9", "note": ""},
    )

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.payment_status == PaymentStatus.PAID
    assert order.status == OrderStatus.CONFIRMED


def test_staff_cancel_order(client, orders_manager, customer):
    order = _order(customer)
    assert client.login(email=orders_manager.email, password="test-pass-12345")

    client.post(
        reverse("orders_dashboard:order_cancel", args=[order.number]),
        {"reason": "Customer called"},
    )

    order.refresh_from_db()
    assert order.status == OrderStatus.CANCELLED


# ---------------------------------------------------------------------------
# Shipping configuration
# ---------------------------------------------------------------------------


def test_shipping_config_lists_render(client, orders_manager):
    assert client.login(email=orders_manager.email, password="test-pass-12345")

    assert client.get(reverse("orders_dashboard:shipping_zone_list")).status_code == 200
    assert client.get(reverse("orders_dashboard:shipping_method_list")).status_code == 200
    assert client.get(reverse("orders_dashboard:shipping_rate_list")).status_code == 200


def test_create_shipping_zone_via_dashboard(client, orders_manager):
    make_state()
    assert client.login(email=orders_manager.email, password="test-pass-12345")

    response = client.post(
        reverse("orders_dashboard:shipping_zone_create"),
        {"name": "North", "code": "NORTH", "description": "", "is_active": "on"},
    )

    assert response.status_code == 302

    assert ShippingZone.objects.filter(code="NORTH").exists()


def test_create_shipping_rate_via_dashboard(client, orders_manager):
    state = make_state()
    method = services.create_shipping_method(name="Standard", code="standard")
    zone = services.create_shipping_zone(name="North", code="north", states=[state])
    assert client.login(email=orders_manager.email, password="test-pass-12345")

    response = client.post(
        reverse("orders_dashboard:shipping_rate_create"),
        {
            "zone": str(zone.pk),
            "method": str(method.pk),
            "fee": "2500.00",
            "min_order_amount": "0.00",
            "is_active": "on",
        },
    )

    assert response.status_code == 302
    from apps.orders.models import ShippingRate

    assert ShippingRate.objects.filter(zone=zone, method=method).count() == 1


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------


def test_quotation_review(client, orders_manager, customer):
    _, listing = make_sellable_product()
    quotation = services.create_quotation_request(
        user=customer,
        listing=listing,
        quantity="100",
        contact_name="Chioma",
        contact_email="chioma@example.com",
    )
    assert client.login(email=orders_manager.email, password="test-pass-12345")

    response = client.post(
        reverse("orders_dashboard:quotation_review", args=[quotation.pk]),
        {"status": "quoted", "response_note": "N4,500 per unit"},
    )

    assert response.status_code == 302
    quotation.refresh_from_db()
    assert quotation.status == "quoted"
    assert quotation.response_note == "N4,500 per unit"

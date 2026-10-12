"""Phase 5 tests: customer order portal and quotation requests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from catalog_helpers import make_sellable_product
from django.urls import reverse
from orders_helpers import make_address, make_shipping

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.orders import services
from apps.orders.models import Cart, OrderStatus, PaymentStatus, QuotationRequest

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _catalog_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


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
# Order portal
# ---------------------------------------------------------------------------


def test_order_list_requires_login(client):
    response = client.get(reverse("orders:order_list"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_customer_sees_own_order(client, customer):
    order = _order(customer)
    assert client.login(email=customer.email, password="test-pass-12345")

    response = client.get(reverse("orders:order_list"))

    assert response.status_code == 200
    assert order.number.encode() in response.content


def test_customer_cannot_view_another_customers_order(client, customer):
    order = _order(customer)
    other = User.objects.create_user(
        email="other@example.com", password="test-pass-12345", role=UserRole.CUSTOMER
    )
    sync_user_groups(other)
    assert client.login(email=other.email, password="test-pass-12345")

    response = client.get(reverse("orders:order_detail", args=[order.number]))

    assert response.status_code == 302
    assert response.url == reverse("orders:order_list")


def test_customer_can_cancel_pending_order(client, customer):
    order = _order(customer)
    assert client.login(email=customer.email, password="test-pass-12345")

    response = client.post(
        reverse("orders:order_cancel", args=[order.number]), {"reason": "Found cheaper"}
    )

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.status == OrderStatus.CANCELLED


def test_customer_payment_review_never_marks_paid(client, customer):
    order = _order(customer)
    assert client.login(email=customer.email, password="test-pass-12345")

    client.post(
        reverse("orders:order_payment_review", args=[order.number]), {"note": "I have paid"}
    )

    order.refresh_from_db()
    assert order.status == OrderStatus.PAYMENT_REVIEW
    assert order.payment_status == PaymentStatus.PENDING


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------


def test_quotation_form_is_public(client):
    _, listing = make_sellable_product()

    response = client.get(reverse("orders:quotation_create", args=[listing.pk]))

    assert response.status_code == 200


def test_public_can_submit_quotation(client):
    _, listing = make_sellable_product()

    response = client.post(
        reverse("orders:quotation_create", args=[listing.pk]),
        {
            "quantity": "500",
            "contact_name": "Chioma Okafor",
            "contact_email": "chioma@example.com",
            "contact_phone": "08030000000",
            "requirements": "Bulk order for a restaurant.",
        },
    )

    assert response.status_code == 302
    quotation = QuotationRequest.objects.get()
    assert quotation.quantity == Decimal("500.000")
    assert quotation.contact_email == "chioma@example.com"
    assert quotation.user_id is None


def test_quotation_list_is_scoped_to_user(client, customer):
    _, listing = make_sellable_product()
    services.create_quotation_request(
        user=customer,
        listing=listing,
        quantity="10",
        contact_name="Chioma",
        contact_email="chioma@example.com",
    )
    assert client.login(email=customer.email, password="test-pass-12345")

    response = client.get(reverse("orders:quotation_list"))

    assert response.status_code == 200
    assert len(response.context["quotations"]) == 1

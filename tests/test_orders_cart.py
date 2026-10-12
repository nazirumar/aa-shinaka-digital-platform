"""Phase 5 tests: cart services/views, guest merge, live pricing, stock guards."""

from __future__ import annotations

from decimal import Decimal

import pytest
from catalog_helpers import make_sellable_product
from django.urls import reverse

from apps.catalog import services as catalog_services
from apps.orders import selectors, services
from apps.orders.models import Cart, CartItem, CartStatus

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _catalog_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def _login(client, user) -> None:
    assert client.login(email=user.email, password="test-pass-12345")


# ---------------------------------------------------------------------------
# Cart views
# ---------------------------------------------------------------------------


def test_cart_page_renders_for_guest(client):
    assert client.get(reverse("orders:cart")).status_code == 200


def test_guest_add_creates_session_cart(client):
    _, listing = make_sellable_product(stock="50.000")

    response = client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "5"})

    assert response.status_code == 302
    cart = Cart.objects.get(status=CartStatus.ACTIVE)
    assert cart.user_id is None
    assert cart.session_key
    item = cart.items.get()
    assert item.quantity == Decimal("5.000")
    assert item.unit_price_snapshot == Decimal("25000.00")


def test_adding_same_listing_merges_quantity(client):
    _, listing = make_sellable_product()
    url = reverse("orders:cart_add", args=[listing.pk])

    client.post(url, {"quantity": "2"})
    client.post(url, {"quantity": "3"})

    cart = Cart.objects.get(status=CartStatus.ACTIVE)
    assert cart.items.count() == 1
    assert cart.items.get().quantity == Decimal("5.000")


def test_add_beyond_available_is_rejected(client):
    _, listing = make_sellable_product(stock="4.000")

    response = client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "10"})

    assert response.status_code == 302
    assert not CartItem.objects.exists()


def test_add_beyond_available_htmx_returns_400(client):
    _, listing = make_sellable_product(stock="4.000")

    response = client.post(
        reverse("orders:cart_add", args=[listing.pk]),
        {"quantity": "10"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 400


def test_update_and_remove_cart_item(client):
    _, listing = make_sellable_product(stock="50.000")
    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "5"})
    cart = Cart.objects.get(status=CartStatus.ACTIVE)
    item = cart.items.get()

    client.post(reverse("orders:cart_item_update", args=[item.pk]), {"quantity": "8"})
    item.refresh_from_db()
    assert item.quantity == Decimal("8.000")

    client.post(reverse("orders:cart_item_remove", args=[item.pk]))
    assert not cart.items.exists()


def test_update_to_zero_removes_item(client):
    _, listing = make_sellable_product()
    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "5"})
    cart = Cart.objects.get(status=CartStatus.ACTIVE)
    item = cart.items.get()

    client.post(reverse("orders:cart_item_update", args=[item.pk]), {"quantity": "0"})

    assert not cart.items.exists()


def test_clear_cart(client):
    _, listing = make_sellable_product()
    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "3"})

    client.post(reverse("orders:cart_clear"))

    cart = Cart.objects.get(status=CartStatus.ACTIVE)
    assert not cart.items.exists()


def test_cart_badge_context_processor(client):
    _, listing = make_sellable_product()
    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "3"})

    response = client.get(reverse("orders:cart"))

    assert response.context["cart_item_count"] == 1


# ---------------------------------------------------------------------------
# Server-side pricing (client can never inject money)
# ---------------------------------------------------------------------------


def test_cart_totals_recompute_live_price(client):
    _, listing = make_sellable_product(price="25000.00")
    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "2"})

    catalog_services.set_listing_price(listing, amount="30000.00")

    cart = Cart.objects.get(status=CartStatus.ACTIVE)
    totals = selectors.cart_totals(cart)
    assert totals["subtotal"] == Decimal("60000.00")
    # The stale display snapshot is not authoritative for money.
    assert totals["lines"][0]["item"].unit_price_snapshot == Decimal("25000.00")


def test_wholesale_tier_applies_to_cart_line(client):
    _, listing = make_sellable_product(price="25000.00")
    catalog_services.set_wholesale_tier(listing, min_quantity="10", price="22000.00")

    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "10"})

    cart = Cart.objects.get(status=CartStatus.ACTIVE)
    assert selectors.cart_totals(cart)["subtotal"] == Decimal("220000.00")


# ---------------------------------------------------------------------------
# Guest cart merge on login
# ---------------------------------------------------------------------------


def test_guest_cart_merged_on_login(client, customer):
    _, listing = make_sellable_product()

    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "4"})
    assert Cart.objects.get(status=CartStatus.ACTIVE).user_id is None

    _login(client, customer)

    user_cart = Cart.objects.get(user=customer, status=CartStatus.ACTIVE)
    assert user_cart.items.get().listing_id == listing.id
    assert user_cart.items.get().quantity == Decimal("4.000")
    assert not Cart.objects.filter(status=CartStatus.ACTIVE, user__isnull=True).exists()


def test_guest_cart_merges_into_existing_user_cart(client, customer):
    _, listing = make_sellable_product(stock="50.000")

    user_cart = Cart.objects.create(user=customer)
    services.add_to_cart(user_cart, listing=listing, quantity="2")

    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "3"})
    _login(client, customer)

    user_cart.refresh_from_db()
    assert user_cart.items.get().quantity == Decimal("5.000")
    assert Cart.objects.filter(status=CartStatus.MERGED).count() == 1


def test_login_without_guest_cart_keeps_user_cart(client, customer):
    _, listing = make_sellable_product()
    user_cart = Cart.objects.create(user=customer)
    services.add_to_cart(user_cart, listing=listing, quantity="1")

    _login(client, customer)

    user_cart.refresh_from_db()
    assert user_cart.status == CartStatus.ACTIVE
    assert user_cart.items.get().quantity == Decimal("1.000")


# ---------------------------------------------------------------------------
# Service-level guards
# ---------------------------------------------------------------------------


def test_update_item_from_other_cart_is_denied(customer, administrator):
    _, listing = make_sellable_product()
    cart = Cart.objects.create(user=customer)
    item = services.add_to_cart(cart, listing=listing, quantity="1")

    other_cart = Cart.objects.create(user=administrator)
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services.update_cart_item(other_cart, item, quantity="2")

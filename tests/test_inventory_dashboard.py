"""Phase 5 tests: inventory dashboard access, warehouses, stock operations."""

from __future__ import annotations

from decimal import Decimal

import pytest
from catalog_helpers import make_sellable_product, make_state
from django.urls import reverse

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.catalog import inventory, services
from apps.catalog.models import StockMovement, Warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _catalog_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def _make(role, email) -> User:
    user = User.objects.create_user(
        email=email,
        password="test-pass-12345",
        first_name="Ife",
        last_name="Obi",
        role=role,
        is_staff=True,
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def inventory_officer(db) -> User:
    return _make(UserRole.INVENTORY_OFFICER, "inventory2@example.com")


@pytest.fixture
def sales_officer(db) -> User:
    return _make(UserRole.SALES_OFFICER, "sales4@example.com")


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_inventory_requires_login(client):
    response = client.get(reverse("inventory_dashboard:home"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_sales_officer_is_forbidden(client, sales_officer):
    assert client.login(email=sales_officer.email, password="test-pass-12345")

    assert client.get(reverse("inventory_dashboard:home")).status_code == 403


def test_inventory_officer_can_view_home(client, inventory_officer):
    assert client.login(email=inventory_officer.email, password="test-pass-12345")

    response = client.get(reverse("inventory_dashboard:home"))

    assert response.status_code == 200
    assert "counts" in response.context


def test_lists_render(client, inventory_officer):
    make_sellable_product()
    assert client.login(email=inventory_officer.email, password="test-pass-12345")

    for name in ("stock_list", "movement_list", "reservation_list", "warehouse_list", "low_stock"):
        assert client.get(reverse(f"inventory_dashboard:{name}")).status_code == 200


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------


def test_warehouse_create(client, inventory_officer):
    state = make_state()
    assert client.login(email=inventory_officer.email, password="test-pass-12345")

    response = client.post(
        reverse("inventory_dashboard:warehouse_create"),
        {"name": "Kano Hub", "code": "KANO", "address": "", "state": state.pk, "is_active": "on"},
    )

    assert response.status_code == 302
    assert Warehouse.objects.filter(code="KANO").exists()


def test_warehouse_create_requires_name(client, inventory_officer):
    assert client.login(email=inventory_officer.email, password="test-pass-12345")

    response = client.post(
        reverse("inventory_dashboard:warehouse_create"),
        {"name": "", "code": "BLANK", "is_active": "on"},
    )

    assert response.status_code == 200
    assert not Warehouse.objects.filter(code="BLANK").exists()


# ---------------------------------------------------------------------------
# Stock receive / transfer
# ---------------------------------------------------------------------------


def test_receive_stock_via_dashboard(client, inventory_officer):
    _, listing = make_sellable_product(stock="10.000")
    assert client.login(email=inventory_officer.email, password="test-pass-12345")

    response = client.post(
        reverse("inventory_dashboard:stock_receive", args=[listing.pk]),
        {"quantity": "5.000", "reference": "GRN-1", "note": ""},
    )

    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.stock_on_hand == Decimal("15.000")
    assert StockMovement.objects.filter(listing=listing, kind="intake").exists()


def test_transfer_stock_between_warehouses(client, inventory_officer):
    _, listing = make_sellable_product(stock="10.000")
    main = inventory.default_warehouse()
    destination = services.create_warehouse(name="Kano Hub", code="KANO2")
    assert client.login(email=inventory_officer.email, password="test-pass-12345")

    response = client.post(
        reverse("inventory_dashboard:stock_transfer", args=[listing.pk]),
        {
            "quantity": "4.000",
            "from_warehouse": str(main.pk),
            "to_warehouse": str(destination.pk),
            "reference": "",
            "note": "",
        },
    )

    assert response.status_code == 302
    assert inventory.get_balance(listing, warehouse=main).on_hand == Decimal("6.000")
    assert inventory.get_balance(listing, warehouse=destination).on_hand == Decimal("4.000")
    assert StockMovement.objects.filter(listing=listing, kind="transfer").count() == 2


def test_transfer_beyond_unreserved_stock_rejected(client, inventory_officer):
    _, listing = make_sellable_product(stock="5.000")
    main = inventory.default_warehouse()
    destination = services.create_warehouse(name="Overflow", code="OVF")
    assert client.login(email=inventory_officer.email, password="test-pass-12345")

    response = client.post(
        reverse("inventory_dashboard:stock_transfer", args=[listing.pk]),
        {
            "quantity": "99.000",
            "from_warehouse": str(main.pk),
            "to_warehouse": str(destination.pk),
            "reference": "",
            "note": "",
        },
    )

    assert response.status_code == 200
    assert inventory.get_balance(listing, warehouse=main).on_hand == Decimal("5.000")
    assert inventory.get_balance(listing, warehouse=destination).on_hand == Decimal("0.000")

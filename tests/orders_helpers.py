"""Reusable builders for the Phase 5 order/inventory tests.

Arranging fixtures may write directly to the ORM, but anything that is itself the
behaviour under test goes through ``apps.orders.services`` /
``apps.catalog.services`` so the tests exercise the real write path (validation,
auditing, stock ledger). Money and quantities are always ``Decimal``.
"""

from __future__ import annotations

from apps.accounts.models import Address
from apps.orders import services


def make_address(user, *, state=None, lga=None, **kwargs) -> Address:
    """Create a delivery address owned by ``user`` (state/lga are data-driven)."""
    from catalog_helpers import make_lga, make_state

    state = state or make_state()
    lga = lga or make_lga(state)
    data = {
        "user": user,
        "recipient_name": "Chioma Okafor",
        "phone": "08030000000",
        "state": state,
        "lga": lga,
        "city": "Zaria",
        "street_address": "12 Farm Road",
    }
    data.update(kwargs)
    return Address.objects.create(**data)


def make_shipping(
    state,
    *,
    name="Standard delivery",
    code="standard",
    fee="1500.00",
    free_over=None,
    min_order_amount="0.00",
):
    """Configure a method + zone + rate that serves ``state``; return all three."""
    method = services.create_shipping_method(name=name, code=code)
    zone = services.create_shipping_zone(
        name=f"{state.name} {code} zone",
        code=f"{code}-zone",
        states=[state],
    )
    rate = services.create_shipping_rate(
        zone=zone,
        method=method,
        fee=fee,
        free_over=free_over,
        min_order_amount=min_order_amount,
    )
    return zone, method, rate


def stock_balance(listing, *, warehouse=None):
    """Return the StockBalance row backing ``listing`` for a warehouse."""
    from apps.catalog import inventory

    return inventory.get_balance(listing, warehouse=warehouse)


def reload_listing(listing):
    listing.refresh_from_db()
    return listing

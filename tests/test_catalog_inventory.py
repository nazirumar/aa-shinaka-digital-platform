"""Phase 4 tests: append-only inventory ledger and status transitions."""

from __future__ import annotations

import pytest
from catalog_helpers import make_category, make_lga, make_listing, make_product, make_state
from django.core.exceptions import ValidationError

from apps.catalog import services
from apps.catalog.models import ListingStatus, StockMovement, StockMovementKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def listing(db):
    state = make_state()
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    return make_listing(product, state, make_lga(state), price="100.00")


def test_adjust_stock_increases_balance_and_logs_movement(listing, staff_user):
    movement = services.adjust_stock(listing, delta="30.000", reference="GRN-1", actor=staff_user)
    listing.refresh_from_db()

    assert listing.stock_on_hand == 30
    assert movement.balance_after == 30
    assert movement.quantity_delta == 30
    assert movement.actor == staff_user


def test_reducing_below_zero_is_rejected_and_leaves_stock_untouched(listing):
    services.adjust_stock(listing, delta="5.000")

    with pytest.raises(ValidationError):
        services.adjust_stock(listing, delta="-6.000")

    listing.refresh_from_db()
    assert listing.stock_on_hand == 5
    assert StockMovement.objects.filter(listing=listing).count() == 1


def test_unknown_movement_kind_is_rejected(listing):
    with pytest.raises(ValidationError):
        services.adjust_stock(listing, delta="1.000", kind="bogus")


def test_invalid_delta_is_rejected(listing):
    with pytest.raises(ValidationError):
        services.adjust_stock(listing, delta="not-a-number")


def test_status_toggles_when_stock_runs_out_and_returns(listing):
    services.adjust_stock(listing, delta="5.000")
    services.set_listing_status(listing, status=ListingStatus.ACTIVE)

    services.adjust_stock(listing, delta="-5.000")
    listing.refresh_from_db()
    assert listing.status == ListingStatus.OUT_OF_STOCK

    services.adjust_stock(listing, delta="3.000")
    listing.refresh_from_db()
    assert listing.status == ListingStatus.ACTIVE


def test_ledger_deltas_reconcile_with_on_hand(listing):
    services.adjust_stock(listing, delta="50.000", kind=StockMovementKind.RETURN)
    services.adjust_stock(listing, delta="-10.000", kind=StockMovementKind.ADJUSTMENT)
    services.adjust_stock(listing, delta="5.000", kind=StockMovementKind.ADJUSTMENT)
    listing.refresh_from_db()

    total = sum(
        StockMovement.objects.filter(listing=listing).values_list("quantity_delta", flat=True)
    )
    assert total == listing.stock_on_hand == 45


def test_stock_movements_are_append_only(listing, staff_user):
    movement = services.adjust_stock(listing, delta="5.000", actor=staff_user)

    movement.quantity_delta = 1
    with pytest.raises(ValidationError):
        movement.save()
    with pytest.raises(ValidationError):
        movement.delete()


def test_adjust_stock_writes_an_audit_entry(listing, staff_user):
    from apps.dashboard.models import AuditLog

    services.adjust_stock(listing, delta="5.000", actor=staff_user)

    assert AuditLog.objects.filter(
        action="catalog.listing.stock", target_id=str(listing.pk)
    ).exists()

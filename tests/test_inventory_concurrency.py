"""Phase 13, Step 5 — inventory hardening tests.

Covers per-warehouse oversell protection, explicit warehouse selection,
correct reservation release/commit, single-warehouse compatibility and genuine
PostgreSQL row-lock concurrency (two writers racing for the last units).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from catalog_helpers import make_category, make_lga, make_listing, make_product, make_state
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.db.models import Sum

from apps.catalog import inventory
from apps.catalog.models import StockBalance, Warehouse

pytestmark = pytest.mark.django_db


_CANONICAL_UNITS = [
    ("Kilogram", "kg", "kg", 10),
    ("Gram", "g", "g", 20),
    ("Tonne", "tonne", "t", 30),
    ("Bag", "bag", "bag", 40),
    ("Crate", "crate", "crate", 50),
    ("Litre", "litre", "L", 60),
    ("Piece", "piece", "pc", 70),
    ("Bunch", "bunch", "bunch", 80),
    ("Carton", "carton", "carton", 90),
]


@pytest.fixture(autouse=True)
def ensure_units(db):
    """transaction=True tests flush the DB, dropping migration-seeded units.

    Re-seed them idempotently so every test in this module can build a listing
    regardless of ordering."""
    from apps.catalog.models import UnitOfMeasure

    for name, code, symbol, sort_order in _CANONICAL_UNITS:
        UnitOfMeasure.objects.get_or_create(
            code=code, defaults={"name": name, "symbol": symbol, "sort_order": sort_order}
        )


@pytest.fixture
def listing(db):
    state = make_state()
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    return make_listing(product, state, make_lga(state), price="100.00")


@pytest.fixture
def warehouse_b(db):
    return Warehouse.objects.create(name="Kano hub", code="KANO", is_active=True)


def _balance(listing, warehouse, variant=None):
    return StockBalance.objects.get(listing=listing, warehouse=warehouse, variant=variant)


# ---------------------------------------------------------------------------
# Single-warehouse compatibility
# ---------------------------------------------------------------------------
def test_single_warehouse_defaults_to_main(listing):
    inventory.receive_stock(listing, quantity="10.000")
    warehouse = inventory.select_warehouse(listing, quantity="4.000")
    assert warehouse.code == inventory.DEFAULT_WAREHOUSE_CODE

    inventory.place_reservation(listing, quantity="4.000", warehouse=warehouse)
    listing.refresh_from_db()
    assert listing.stock_reserved == 4
    assert listing.available_stock == 6


def test_select_warehouse_with_no_stock_falls_back_to_default(listing):
    assert inventory.select_warehouse(listing, quantity="1.000").code == "MAIN"


# ---------------------------------------------------------------------------
# Explicit multi-warehouse selection
# ---------------------------------------------------------------------------
def test_select_warehouse_prefers_default_when_it_can_cover(listing, warehouse_b):
    inventory.receive_stock(listing, quantity="10.000")  # MAIN
    inventory.receive_stock(listing, quantity="10.000", warehouse=warehouse_b)
    chosen = inventory.select_warehouse(listing, quantity="4.000")
    assert chosen.code == "MAIN"


def test_select_warehouse_picks_a_covering_warehouse(listing, warehouse_b):
    inventory.receive_stock(listing, quantity="2.000")  # MAIN too small
    inventory.receive_stock(listing, quantity="20.000", warehouse=warehouse_b)
    chosen = inventory.select_warehouse(listing, quantity="5.000")
    assert chosen.pk == warehouse_b.pk


def test_explicit_preferred_warehouse_is_respected(listing, warehouse_b):
    assert (
        inventory.select_warehouse(listing, quantity="1.000", preferred=warehouse_b) is warehouse_b
    )


# ---------------------------------------------------------------------------
# No oversell (per warehouse)
# ---------------------------------------------------------------------------
def test_reservation_cannot_exceed_warehouse_stock(listing):
    inventory.receive_stock(listing, quantity="5.000")
    inventory.place_reservation(listing, quantity="5.000")
    with pytest.raises(ValidationError):
        inventory.place_reservation(listing, quantity="1.000")
    listing.refresh_from_db()
    assert listing.stock_reserved == 5
    assert listing.available_stock == 0


def test_reservation_cannot_exceed_a_specific_warehouse(listing, warehouse_b):
    inventory.receive_stock(listing, quantity="100.000")  # MAIN plenty
    inventory.receive_stock(listing, quantity="3.000", warehouse=warehouse_b)
    with pytest.raises(ValidationError):
        inventory.place_reservation(listing, quantity="4.000", warehouse=warehouse_b)
    # Roll-up is untouched after the refusal.
    listing.refresh_from_db()
    assert listing.stock_reserved == 0


def test_stock_cannot_be_reduced_below_warehouse_reserved(listing):
    inventory.receive_stock(listing, quantity="5.000")
    inventory.place_reservation(listing, quantity="5.000")
    with pytest.raises(ValidationError):
        inventory.adjust_stock(listing, delta="-1.000")


# ---------------------------------------------------------------------------
# Correct reservation release / commit
# ---------------------------------------------------------------------------
def test_release_restores_availability(listing):
    inventory.receive_stock(listing, quantity="5.000")
    inventory.place_reservation(listing, quantity="3.000")
    inventory.release_reservation(listing, quantity="3.000")
    listing.refresh_from_db()
    assert listing.stock_reserved == 0
    assert listing.available_stock == 5


def test_release_is_warehouse_accurate(listing, warehouse_b):
    inventory.receive_stock(listing, quantity="10.000")  # MAIN
    inventory.receive_stock(listing, quantity="10.000", warehouse=warehouse_b)
    inventory.place_reservation(listing, quantity="4.000", warehouse=warehouse_b)
    main = inventory.resolve_warehouse()
    inventory.release_reservation(listing, quantity="4.000", warehouse=warehouse_b)

    listing.refresh_from_db()
    assert _balance(listing, warehouse_b).reserved == 0
    assert _balance(listing, main).reserved == 0
    assert listing.stock_reserved == 0


def test_release_never_goes_below_zero(listing):
    inventory.receive_stock(listing, quantity="5.000")
    inventory.release_reservation(listing, quantity="9.000")
    listing.refresh_from_db()
    assert listing.stock_reserved == 0


def test_release_requires_positive_quantity(listing):
    with pytest.raises(ValidationError):
        inventory.release_reservation(listing, quantity="0")


def test_commit_reduces_on_hand_and_reserved_together(listing):
    inventory.receive_stock(listing, quantity="10.000")
    inventory.place_reservation(listing, quantity="4.000")
    inventory.commit_reservation(listing, quantity="4.000", reference="ORD-1")

    listing.refresh_from_db()
    assert listing.stock_on_hand == 6
    assert listing.stock_reserved == 0
    assert _balance(listing, inventory.resolve_warehouse()).on_hand == 6


def test_commit_beyond_on_hand_is_rejected(listing):
    inventory.receive_stock(listing, quantity="2.000")
    with pytest.raises(ValidationError):
        inventory.commit_reservation(listing, quantity="3.000")


def test_rollup_stays_consistent_with_balances(listing, warehouse_b):
    inventory.receive_stock(listing, quantity="7.000")
    inventory.receive_stock(listing, quantity="5.000", warehouse=warehouse_b)
    inventory.place_reservation(listing, quantity="2.000", warehouse=warehouse_b)
    inventory.place_reservation(listing, quantity="3.000")
    listing.refresh_from_db()
    totals = StockBalance.objects.filter(listing=listing).aggregate(
        on_hand=Sum("on_hand"), reserved=Sum("reserved")
    )
    assert listing.stock_on_hand == totals["on_hand"]
    assert listing.stock_reserved == totals["reserved"]


# ---------------------------------------------------------------------------
# Real concurrency (PostgreSQL row locks) — transaction=True so threads commit
# ---------------------------------------------------------------------------
def _reserve_worker(listing_id, warehouse_id, quantity, barrier):
    """Reserve in a worker thread on its own connection; return the outcome."""
    from apps.catalog.models import ProductListing

    try:
        barrier.wait(timeout=10)
        listing = ProductListing.objects.get(pk=listing_id)
        warehouse = Warehouse.objects.get(pk=warehouse_id)
        inventory.place_reservation(listing, quantity=quantity, warehouse=warehouse)
        return "ok"
    except ValidationError:
        return "refused"
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_concurrent_reservations_never_oversell(listing):
    inventory.receive_stock(listing, quantity="5.000")
    main = inventory.resolve_warehouse()
    listing_id, warehouse_id = listing.pk, main.pk

    import threading

    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_reserve_worker, listing_id, warehouse_id, "5.000", barrier)
            for _ in range(2)
        ]
        outcomes = [f.result(timeout=30) for f in futures]

    assert sorted(outcomes) == ["ok", "refused"]
    balance = StockBalance.objects.get(listing_id=listing_id, warehouse_id=warehouse_id)
    assert balance.reserved == Decimal("5.000")
    assert balance.on_hand == Decimal("5.000")


@pytest.mark.django_db(transaction=True)
def test_concurrent_partial_reservations_do_not_exceed_stock(listing):
    inventory.receive_stock(listing, quantity="10.000")
    main = inventory.resolve_warehouse()
    listing_id, warehouse_id = listing.pk, main.pk

    import threading

    barrier = threading.Barrier(2)
    # Both try to reserve 7 of 10; only one may succeed.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_reserve_worker, listing_id, warehouse_id, "7.000", barrier)
            for _ in range(2)
        ]
        outcomes = [f.result(timeout=30) for f in futures]

    assert sorted(outcomes) == ["ok", "refused"]
    balance = StockBalance.objects.get(listing_id=listing_id, warehouse_id=warehouse_id)
    assert balance.reserved == Decimal("7.000")


@pytest.mark.django_db(transaction=True)
def test_concurrent_commits_do_not_drive_stock_negative(listing):
    """Two workers each confirm the same single reservation: only one commits."""
    inventory.receive_stock(listing, quantity="5.000")
    main = inventory.resolve_warehouse()
    inventory.place_reservation(listing, quantity="5.000", warehouse=main)
    listing_id = listing.pk

    def worker():
        from apps.catalog.models import ProductListing

        try:
            target = ProductListing.objects.get(pk=listing_id)
            inventory.commit_reservation(target, quantity="5.000", warehouse=main)
            return "ok"
        except ValidationError:
            return "refused"
        finally:
            connections.close_all()

    import threading

    barrier = threading.Barrier(2)

    def gated_worker():
        barrier.wait(timeout=10)
        return worker()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(gated_worker) for _ in range(2)]
        outcomes = [f.result(timeout=30) for f in futures]

    assert sorted(outcomes) == ["ok", "refused"]
    balance = StockBalance.objects.get(listing_id=listing_id, warehouse_id=main.pk)
    assert balance.on_hand >= 0
    assert balance.reserved >= 0


def teardown_module(module):  # pragma: no cover - connection hygiene
    connection.close()

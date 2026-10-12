"""Phase 4 tests: origin-specific listings, package uniqueness, variants."""

from __future__ import annotations

import pytest
from catalog_helpers import (
    make_category,
    make_lga,
    make_listing,
    make_product,
    make_state,
    upload,
)
from django.core.exceptions import ValidationError

from apps.catalog.models import (
    ListingStatus,
    PriceHistory,
    ProductListing,
    ProductVariant,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def origin(db):
    state = make_state()
    return state, make_lga(state)


@pytest.fixture
def listing(origin):
    state, lga = origin
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    return make_listing(product, state, lga, price="25000.00")


# ---------------------------------------------------------------------------
# Creation & opening ledger
# ---------------------------------------------------------------------------


def test_create_listing_is_draft_and_records_opening_price(listing):
    assert listing.status == ListingStatus.DRAFT
    assert listing.selling_price == 25000
    assert listing.prices.count() == 1
    history = PriceHistory.objects.get(listing=listing, note="Opening price")
    assert history.old_price == 0
    assert history.new_price == 25000


def test_listing_packaging_uses_unit_symbol(listing):
    assert listing.packaging == "50kg"


def test_available_stock_is_on_hand_minus_reserved(listing):
    from apps.catalog import services as svc

    svc.adjust_stock(listing, delta="30.000")
    listing.refresh_from_db()

    assert listing.stock_on_hand == 30
    assert listing.available_stock == 30


# ---------------------------------------------------------------------------
# Constraints & validation
# ---------------------------------------------------------------------------


def test_duplicate_origin_and_package_is_rejected(listing):
    with pytest.raises(ValidationError):
        make_listing(
            listing.product,
            listing.state,
            listing.lga,
            package_size="50.000",
            price="26000.00",
        )


def test_same_origin_different_package_is_allowed(listing):
    second = make_listing(
        listing.product,
        listing.state,
        listing.lga,
        package_size="100.000",
        price="48000.00",
    )

    assert second.pk != listing.pk


def test_lga_must_belong_to_the_selected_state(listing):
    other_state = make_state(name="Oyo", code="OY", zone="SW")
    other_lga = make_lga(other_state, name="Ibadan", code="IB")

    with pytest.raises(ValidationError):
        make_listing(listing.product, listing.state, other_lga)


def test_package_size_must_be_positive(listing):
    with pytest.raises(ValidationError):
        make_listing(
            listing.product,
            listing.state,
            listing.lga,
            package_size="0.000",
        )


def test_set_listing_status_rejects_unknown_status(listing):
    from apps.catalog import services as svc

    with pytest.raises(ValidationError):
        svc.set_listing_status(listing, status="nonsense")


# ---------------------------------------------------------------------------
# Status & archive
# ---------------------------------------------------------------------------


def test_setting_listing_active_makes_it_sellable_once_published(listing):
    from apps.catalog import services as svc

    svc.add_product_image(listing.product, image=upload())
    svc.adjust_stock(listing, delta="10.000")
    svc.set_listing_status(listing, status=ListingStatus.ACTIVE)
    svc.set_product_status(listing.product, status="published")
    listing.refresh_from_db()

    assert listing.is_sellable is True


def test_archive_listing_hides_it_but_keeps_history(listing):
    from apps.catalog import services as svc

    svc.add_product_image(listing.product, image=upload())
    svc.set_listing_status(listing, status=ListingStatus.ACTIVE)
    svc.set_product_status(listing.product, status="published")

    svc.archive_listing(listing)
    listing.refresh_from_db()

    assert listing.status == ListingStatus.ARCHIVED
    assert listing.price_history.exists()
    assert ProductListing.objects.sellable().filter(pk=listing.pk).count() == 0


def test_listing_with_history_cannot_be_deleted(listing):
    with pytest.raises(ValidationError):
        listing.delete()


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------


def test_update_listing_changes_origin_note_and_verification(listing):
    from apps.catalog import services as svc

    svc.update_listing(
        listing,
        origin_note="Stored in a clean, dry warehouse.",
        origin_verification="verified",
    )
    listing.refresh_from_db()

    assert listing.origin_note.startswith("Stored")
    assert listing.origin_verification == "verified"


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


def test_create_variant(listing):
    from apps.catalog import services as svc

    variant = svc.create_variant(listing, name="Grade A", notes="Hand-sorted")

    assert variant.listing_id == listing.pk
    assert list(listing.variants.values_list("name", flat=True)) == ["Grade A"]


def test_variant_names_are_unique_per_listing(listing):
    from apps.catalog import services as svc

    svc.create_variant(listing, name="Grade A")

    with pytest.raises(ValidationError):
        svc.create_variant(listing, name="Grade A")


def test_two_listings_can_reuse_a_variant_name(origin):
    from apps.catalog import services as svc

    state, lga = origin
    category = make_category(name="Grains")
    first = make_listing(make_product(category, name="Maize"), state, lga)
    second = make_listing(make_product(category, name="Rice"), state, lga, package_size="25.000")

    svc.create_variant(first, name="Grade A")
    svc.create_variant(second, name="Grade A")

    assert ProductVariant.objects.filter(name="Grade A").count() == 2

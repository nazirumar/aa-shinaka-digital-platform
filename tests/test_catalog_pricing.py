"""Phase 4 tests: pricing engine, history, tiers and market references."""

from __future__ import annotations

from datetime import timedelta

import pytest
from catalog_helpers import (
    make_category,
    make_lga,
    make_listing,
    make_product,
    make_state,
    unit,
)
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog import selectors, services
from apps.catalog.models import (
    ListingPrice,
    MarketReferencePrice,
    PriceHistory,
    WholesalePriceTier,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def listing(db):
    state = make_state()
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    return make_listing(product, state, make_lga(state), price="100.00")


# ---------------------------------------------------------------------------
# set_listing_price
# ---------------------------------------------------------------------------


def test_setting_price_syncs_headline_and_records_history(listing):
    services.set_listing_price(listing, amount="250.00")
    listing.refresh_from_db()

    assert listing.selling_price == 250
    # ``created_at`` is ``auto_now_add`` and rows created within the same clock
    # tick tie, so select the historical row by its unique new price rather than
    # relying on recency ordering.
    history = PriceHistory.objects.get(listing=listing, new_price="250.00")
    assert history.old_price == 100
    assert history.new_price == 250


def test_successive_prices_build_an_append_only_chain(listing):
    services.set_listing_price(listing, amount="250.00")
    services.set_listing_price(listing, amount="310.00")
    listing.refresh_from_db()

    assert listing.selling_price == 310
    assert PriceHistory.objects.filter(listing=listing).count() == 3
    latest = PriceHistory.objects.get(listing=listing, new_price="310.00")
    assert (latest.old_price, latest.new_price) == (250, 310)


def test_retired_prices_are_deactivated(listing):
    services.set_listing_price(listing, amount="250.00")

    active = ListingPrice.objects.filter(listing=listing, is_active=True)
    assert active.count() == 1
    assert active.first().amount == 250


def test_negative_amount_is_rejected(listing):
    with pytest.raises(ValidationError):
        services.set_listing_price(listing, amount="-1.00")


def test_negative_compare_at_is_rejected(listing):
    with pytest.raises(ValidationError):
        services.set_listing_price(listing, amount="100.00", compare_at="-5.00")


def test_unknown_price_type_is_rejected(listing):
    with pytest.raises(ValidationError):
        services.set_listing_price(listing, amount="100.00", price_type="nonsense")


def test_valid_from_after_valid_to_is_rejected(listing):
    now = timezone.now()
    with pytest.raises(ValidationError):
        services.set_listing_price(
            listing, amount="100.00", valid_from=now + timedelta(days=2), valid_to=now
        )


# ---------------------------------------------------------------------------
# Scheduled windows
# ---------------------------------------------------------------------------


def test_scheduled_price_does_not_change_headline(listing):
    now = timezone.now()
    services.set_listing_price(
        listing,
        amount="200.00",
        valid_from=now + timedelta(days=1),
        valid_to=now + timedelta(days=3),
    )
    listing.refresh_from_db()

    assert listing.selling_price == 100


def test_effective_price_picks_live_window_over_open_fallback(listing):
    now = timezone.now()
    services.set_listing_price(
        listing,
        amount="200.00",
        valid_from=now - timedelta(hours=1),
        valid_to=now + timedelta(hours=1),
    )

    effective = selectors.effective_price(listing)

    assert effective.amount == 200


def test_effective_price_falls_back_to_open_price_outside_window(listing):
    future = timezone.now() + timedelta(days=5)
    services.set_listing_price(
        listing,
        amount="200.00",
        valid_from=future,
        valid_to=future + timedelta(days=1),
    )

    assert selectors.effective_price(listing).amount == 100
    assert selectors.effective_price(listing, at=future + timedelta(hours=1)).amount == 200


def test_overlapping_price_windows_are_rejected(listing):
    now = timezone.now()
    services.set_listing_price(
        listing,
        amount="200.00",
        valid_from=now,
        valid_to=now + timedelta(days=2),
    )

    with pytest.raises(ValidationError):
        services.set_listing_price(
            listing,
            amount="210.00",
            valid_from=now + timedelta(hours=1),
            valid_to=now + timedelta(days=3),
        )


def test_setting_a_current_price_keeps_future_schedule(listing):
    future = timezone.now() + timedelta(days=10)
    services.set_listing_price(
        listing, amount="200.00", valid_from=future, valid_to=future + timedelta(days=1)
    )

    services.set_listing_price(listing, amount="150.00")
    listing.refresh_from_db()

    scheduled = ListingPrice.objects.filter(listing=listing, valid_from=future)
    assert scheduled.count() == 1
    assert scheduled.first().is_active is True
    assert listing.selling_price == 150


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


def test_variant_price_is_isolated_from_headline(listing):
    variant = services.create_variant(listing, name="Grade A")

    services.set_variant_price(listing, variant=variant, amount="175.00")
    listing.refresh_from_db()

    assert listing.selling_price == 100
    assert selectors.effective_price(listing, variant=variant).amount == 175


# ---------------------------------------------------------------------------
# History immutability
# ---------------------------------------------------------------------------


def test_price_history_is_append_only(listing):
    history = PriceHistory.objects.get(listing=listing, note="Opening price")

    history.new_price = 1
    with pytest.raises(ValidationError):
        history.save()
    with pytest.raises(ValidationError):
        history.delete()


# ---------------------------------------------------------------------------
# Wholesale tiers
# ---------------------------------------------------------------------------


def test_wholesale_tier_create_and_update(listing):
    services.set_wholesale_tier(listing, min_quantity="10", price="24000.00")
    services.set_wholesale_tier(listing, min_quantity="10", price="23000.00")

    tiers = WholesalePriceTier.objects.filter(listing=listing)
    assert tiers.count() == 1
    assert tiers.first().price == 23000


def test_wholesale_tier_requires_positive_quantity(listing):
    with pytest.raises(ValidationError):
        services.set_wholesale_tier(listing, min_quantity="0", price="23000.00")


def test_wholesale_tier_rejects_negative_price(listing):
    with pytest.raises(ValidationError):
        services.set_wholesale_tier(listing, min_quantity="10", price="-1.00")


def test_remove_wholesale_tier(listing):
    tier = services.set_wholesale_tier(listing, min_quantity="10", price="23000.00")

    services.remove_wholesale_tier(tier)

    assert WholesalePriceTier.objects.filter(listing=listing).count() == 0


# ---------------------------------------------------------------------------
# Market reference prices (stored separately from selling prices)
# ---------------------------------------------------------------------------


def test_market_reference_is_separate_from_listing_price(listing):
    services.record_market_reference(
        listing.product, year=2026, price_per_unit="500.00", unit=unit(), season="Dry"
    )

    assert MarketReferencePrice.objects.filter(product=listing.product).count() == 1
    assert ListingPrice.objects.filter(listing=listing).count() == 1


def test_market_reference_national_upserts(listing):
    services.record_market_reference(
        listing.product, year=2026, price_per_unit="500.00", unit=unit()
    )
    services.record_market_reference(
        listing.product, year=2026, price_per_unit="550.00", unit=unit()
    )

    assert MarketReferencePrice.objects.filter(product=listing.product).count() == 1


def test_market_reference_state_variant_coexists_with_national(listing):
    state = listing.state
    services.record_market_reference(
        listing.product, year=2026, price_per_unit="500.00", unit=unit()
    )
    services.record_market_reference(
        listing.product, year=2026, price_per_unit="600.00", unit=unit(), state=state
    )

    assert MarketReferencePrice.objects.filter(product=listing.product).count() == 2
    assert selectors.market_reference_prices(listing.product, year=2026).count() == 2


def test_market_reference_rejects_negative_price(listing):
    with pytest.raises(ValidationError):
        services.record_market_reference(
            listing.product, year=2026, price_per_unit="-1.00", unit=unit()
        )

"""Phase 4 tests: public catalogue routes, leakage guards and filters."""

from __future__ import annotations

import pytest
from catalog_helpers import (
    make_category,
    make_lga,
    make_sellable_product,
    make_state,
)
from django.urls import reverse

from apps.catalog import selectors
from apps.catalog.models import Category

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _catalog_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


# ---------------------------------------------------------------------------
# Index & categories
# ---------------------------------------------------------------------------


def test_shop_index_renders(client):
    response = client.get(reverse("catalog:shop_index"))

    assert response.status_code == 200


def test_shop_index_shows_featured_product(client):
    product, _ = make_sellable_product(name="Featured Maize", featured=True)

    response = client.get(reverse("catalog:shop_index"))

    assert product.name.encode() in response.content


def test_category_list_renders(client):
    make_category(name="Grains")

    response = client.get(reverse("catalog:category_list"))

    assert response.status_code == 200
    assert b"Grains" in response.content


def test_category_detail_lists_published_product(client):
    product, _ = make_sellable_product(name="Yellow Maize")

    response = client.get(product.category.get_absolute_url())

    assert response.status_code == 200
    assert b"Yellow Maize" in response.content


def test_category_detail_hides_draft_products(client):
    product, _ = make_sellable_product(name="Secret Crop", publish=False)

    response = client.get(product.category.get_absolute_url())

    assert response.status_code == 200
    assert b"Secret Crop" not in response.content


def test_category_detail_includes_descendant_categories(client):
    root = make_category(name="Grains")
    child = make_category(name="Rice", parent=root)
    product, _ = make_sellable_product(category=child, name="Ofada Rice")

    response = client.get(root.get_absolute_url())

    assert b"Ofada Rice" in response.content


def test_inactive_category_is_not_found(client):
    category = make_category(name="Hidden")
    category.is_active = False
    category.save(update_fields=["is_active"])

    assert client.get(category.get_absolute_url()).status_code == 404


def test_unknown_category_is_not_found(client):
    assert client.get(reverse("catalog:category_detail", args=["nope"])).status_code == 404


def test_category_detail_hx_returns_partial(client):
    make_sellable_product(name="Yellow Maize")
    category = Category.objects.get(name="Grains")

    response = client.get(category.get_absolute_url(), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b"<html" not in response.content


# ---------------------------------------------------------------------------
# Product detail
# ---------------------------------------------------------------------------


def test_product_detail_renders_for_published_product(client):
    product, _ = make_sellable_product(name="Yellow Maize")

    response = client.get(product.get_absolute_url())

    assert response.status_code == 200
    assert b"Yellow Maize" in response.content


def test_product_detail_hidden_for_draft(client):
    product, _ = make_sellable_product(name="Secret Crop", publish=False)

    assert client.get(product.get_absolute_url()).status_code == 404


def test_product_detail_hidden_after_archive(client):
    from apps.catalog import services

    product, _ = make_sellable_product(name="Old Crop")
    services.archive_product(product)

    assert client.get(product.get_absolute_url()).status_code == 404


# ---------------------------------------------------------------------------
# States & LGAs
# ---------------------------------------------------------------------------


def test_state_list_renders(client):
    make_sellable_product(name="Yellow Maize")

    response = client.get(reverse("catalog:state_list"))

    assert response.status_code == 200
    assert b"Kaduna" in response.content


def test_state_detail_lists_listings(client):
    product, _ = make_sellable_product(name="Yellow Maize")

    response = client.get(product.listings.first().state.get_absolute_url())

    assert response.status_code == 200
    assert b"Yellow Maize" in response.content


def test_lga_detail_lists_listings(client):
    product, _ = make_sellable_product(name="Yellow Maize")
    lga = product.listings.first().lga

    response = client.get(lga.get_absolute_url())

    assert response.status_code == 200
    assert b"Yellow Maize" in response.content


def test_unknown_state_and_lga_are_not_found(client):
    assert client.get(reverse("catalog:state_detail", args=["nope"])).status_code == 404
    assert client.get(reverse("catalog:lga_detail", args=["nope", "nope"])).status_code == 404


# ---------------------------------------------------------------------------
# Legacy aliases
# ---------------------------------------------------------------------------


def test_legacy_product_alias_resolves(client):
    product, _ = make_sellable_product(name="Yellow Maize")

    response = client.get(reverse("product_detail", args=[product.slug]))

    assert response.status_code == 200
    assert b"Yellow Maize" in response.content


def test_legacy_state_aliases(client):
    product, _ = make_sellable_product(name="Yellow Maize")
    listing = product.listings.first()

    assert client.get(reverse("state_list")).status_code == 200
    assert client.get(reverse("state_detail", args=[listing.state.slug])).status_code == 200
    assert (
        client.get(reverse("lga_detail", args=[listing.state.slug, listing.lga.slug])).status_code
        == 200
    )


def test_legacy_shop_slug_alias_is_category_detail(client):
    make_category(name="Grains")

    response = client.get(reverse("category_detail_legacy", args=["grains"]))

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Search & compare
# ---------------------------------------------------------------------------


def test_search_matches_product_name(client):
    make_sellable_product(name="Yellow Maize")
    make_sellable_product(name="Brown Beans", category=make_category(name="Legumes"))

    response = client.get(reverse("catalog:search"), {"q": "maize"})

    assert response.status_code == 200
    assert b"Yellow Maize" in response.content
    assert b"Brown Beans" not in response.content


def test_search_min_price_filters_results(client):
    make_sellable_product(name="Cheap Maize", price="100.00")
    make_sellable_product(name="Pricey Maize", price="900.00")

    response = client.get(reverse("catalog:search"), {"min_price": "500"})
    results = list(response.context["listings"])

    assert [listing.selling_price for listing in results] == [900]


def test_search_in_stock_filter(client):
    make_sellable_product(name="Empty Maize", stock="0.000")

    response = client.get(reverse("catalog:search"), {"q": "maize", "in_stock": "1"})

    assert list(response.context["listings"]) == []


def test_search_sorts_by_price(client):
    make_sellable_product(name="High Maize", price="900.00")
    make_sellable_product(name="Low Maize", price="100.00")

    response = client.get(reverse("catalog:search"), {"q": "maize", "sort": "price_asc"})
    results = list(response.context["listings"])

    assert [listing.selling_price for listing in results] == [100, 900]


def test_compare_only_returns_published_products(client):
    published, _ = make_sellable_product(name="Published Maize")
    draft, _ = make_sellable_product(name="Draft Maize", publish=False)

    response = client.get(reverse("catalog:compare"), {"slugs": f"{published.slug},{draft.slug}"})
    products = list(response.context["products"])

    assert products == [published]


# ---------------------------------------------------------------------------
# HTMX LGA options
# ---------------------------------------------------------------------------


def test_lga_options_default_returns_primary_keys(client):
    state = make_state()
    lga = make_lga(state, name="Zaria")

    response = client.get(reverse("catalog:lga_options"), {"state": str(state.pk)})

    assert response.status_code == 200
    assert str(lga.pk).encode() in response.content
    assert b"Zaria" in response.content


def test_lga_options_value_slug_returns_slugs(client):
    state = make_state()
    lga = make_lga(state, name="Zaria")

    response = client.get(reverse("catalog:lga_options"), {"state": state.slug, "value": "slug"})

    assert lga.slug.encode() in response.content


def test_lga_options_excludes_inactive(client):
    state = make_state()
    lga = make_lga(state, name="Zaria")
    lga.is_active = False
    lga.save(update_fields=["is_active"])

    response = client.get(reverse("catalog:lga_options"), {"state": str(state.pk)})

    assert b"Zaria" not in response.content


# ---------------------------------------------------------------------------
# Selectors / homepage integration
# ---------------------------------------------------------------------------


def test_price_bands_are_derived_from_data(client):
    make_sellable_product(name="Maize", price="1000.00")

    bands = selectors.build_price_bands()

    assert len(bands) == 5
    assert bands[-1]["max"] is None


def test_price_bands_empty_without_listings(client):
    assert selectors.build_price_bands() == []


def test_homepage_integrates_featured_catalogue_products(client):
    product, _ = make_sellable_product(name="Featured Maize", featured=True)

    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    assert product.name.encode() in response.content


def test_state_list_count_only_counts_sellable(client):
    make_sellable_product(name="Published Maize")
    make_sellable_product(name="Draft Maize", category=make_category(name="Legumes"), publish=False)

    state = selectors.state_by_slug("kaduna")
    assert state is not None
    counts = {item.pk: item.listing_count for item in selectors.state_list() if item.pk == state.pk}
    assert counts[state.pk] == 1

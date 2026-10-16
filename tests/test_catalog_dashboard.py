"""Phase 4 tests: staff catalogue/inventory dashboard access and CRUD."""

from __future__ import annotations

import pytest
from catalog_helpers import (
    make_category,
    make_lga,
    make_listing,
    make_product,
    make_state,
    unit,
    upload,
)
from django.urls import reverse

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.catalog import services
from apps.catalog.models import (
    Category,
    ListingStatus,
    MarketReferencePrice,
    Product,
    ProductImage,
    ProductListing,
    ProductVariant,
    PublishStatus,
    WholesalePriceTier,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _catalog_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def inventory_officer(db) -> User:
    user = User.objects.create_user(
        email="inventory@example.com",
        password="test-pass-12345",
        first_name="Ife",
        last_name="Obi",
        role=UserRole.INVENTORY_OFFICER,
        is_staff=True,
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def listing(db):
    state = make_state()
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    return make_listing(product, state, make_lga(state), price="100.00")


def _login(client, user) -> None:
    assert client.login(email=user.email, password="test-pass-12345")


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_anonymous_is_redirected_to_login(client):
    response = client.get(reverse("catalog_dashboard:home"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_customer_is_forbidden(client, customer):
    _login(client, customer)

    assert client.get(reverse("catalog_dashboard:home")).status_code == 403


def test_sales_officer_can_reach_catalog_dashboard(client, staff_user):
    _login(client, staff_user)

    response = client.get(reverse("catalog_dashboard:home"))

    assert response.status_code == 200
    assert "counts" in response.context


def test_sales_officer_cannot_reach_inventory_views(client, staff_user):
    _login(client, staff_user)

    assert client.get(reverse("catalog_dashboard:low_stock")).status_code == 403


def test_inventory_officer_can_reach_inventory_views(client, inventory_officer):
    _login(client, inventory_officer)

    assert client.get(reverse("catalog_dashboard:low_stock")).status_code == 200


def test_inventory_low_stock_alias_is_gated(client, staff_user, inventory_officer):
    _login(client, staff_user)
    assert client.get(reverse("inventory_dashboard:low_stock")).status_code == 403

    client.logout()
    _login(client, inventory_officer)
    assert client.get(reverse("inventory_dashboard:low_stock")).status_code == 200


def test_owner_can_reach_catalog_dashboard(client, owner):
    client.force_login(owner)

    assert client.get(reverse("catalog_dashboard:home")).status_code == 200


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def test_category_list_renders(client, staff_user):
    make_category(name="Grains")
    _login(client, staff_user)

    response = client.get(reverse("catalog_dashboard:category_list"))

    assert response.status_code == 200
    assert b"Grains" in response.content


def test_create_category(client, staff_user):
    _login(client, staff_user)

    response = client.post(
        reverse("catalog_dashboard:category_create"),
        {
            "parent": "",
            "name": "Legumes",
            "description": "Beans and pulses.",
            "is_active": "on",
            "is_featured": "",
            "sort_order": "0",
            "seo_title": "",
            "seo_description": "",
        },
    )

    assert response.status_code == 302
    assert Category.objects.filter(name="Legumes").exists()


def test_toggle_category_visibility(client, staff_user):
    category = make_category(name="Grains")
    _login(client, staff_user)

    response = client.post(reverse("catalog_dashboard:category_toggle", args=[category.pk]))

    assert response.status_code == 302
    category.refresh_from_db()
    assert category.is_active is False


def test_reorder_category(client, staff_user):
    first = make_category(name="Grains", sort_order=0)
    second = make_category(name="Legumes", sort_order=1)
    _login(client, staff_user)

    client.post(reverse("catalog_dashboard:category_reorder", args=[second.pk]), {"step": "-1"})

    first.refresh_from_db()
    second.refresh_from_db()
    assert second.sort_order == 0
    assert first.sort_order == 1


def test_archive_refused_when_category_has_children(client, staff_user):
    root = make_category(name="Grains")
    make_category(name="Rice", parent=root)
    _login(client, staff_user)

    client.post(reverse("catalog_dashboard:category_delete", args=[root.pk]))

    assert Category.objects.filter(pk=root.pk).exists()


def test_archive_empty_category(client, staff_user):
    category = make_category(name="Grains")
    _login(client, staff_user)

    client.post(reverse("catalog_dashboard:category_delete", args=[category.pk]))

    assert not Category.objects.filter(pk=category.pk).exists()


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


def test_create_product(client, staff_user):
    category = make_category(name="Grains")
    _login(client, staff_user)

    response = client.post(
        reverse("catalog_dashboard:product_create"),
        {
            "name": "Yellow Maize",
            "category": str(category.pk),
            "short_description": "Fresh harvest.",
            "description": "",
            "unit": str(unit().pk),
            "variety": "",
            "grade": "",
            "harvest_season": "",
            "seo_title": "",
            "seo_description": "",
        },
    )

    assert response.status_code == 302
    product = Product.objects.get(name="Yellow Maize")
    assert product.status == PublishStatus.DRAFT


def test_publish_incomplete_product_reports_error(client, staff_user):
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    _login(client, staff_user)

    response = client.post(
        reverse("catalog_dashboard:product_publish", args=[product.pk]),
        {"status": "published"},
    )

    assert response.status_code == 302
    product.refresh_from_db()
    assert product.status == PublishStatus.DRAFT


def test_publish_ready_product(client, staff_user):
    state = make_state()
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    services.add_product_image(product, image=upload())
    listing = make_listing(product, state, make_lga(state))
    services.set_listing_status(listing, status=ListingStatus.ACTIVE)
    _login(client, staff_user)

    client.post(
        reverse("catalog_dashboard:product_publish", args=[product.pk]), {"status": "published"}
    )

    product.refresh_from_db()
    assert product.status == PublishStatus.PUBLISHED


def test_delete_draft_product(client, staff_user):
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    _login(client, staff_user)

    client.post(reverse("catalog_dashboard:product_delete", args=[product.pk]))

    assert not Product.all_objects.filter(pk=product.pk).exists()


# ---------------------------------------------------------------------------
# Product images
# ---------------------------------------------------------------------------


def test_upload_product_image_sets_primary(client, staff_user):
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    _login(client, staff_user)

    response = client.post(
        reverse("catalog_dashboard:product_images", args=[product.pk]),
        {"image": upload(), "alt_text": "A basket of maize", "sort_order": "0"},
    )

    assert response.status_code == 302
    photo = ProductImage.objects.get(product=product)
    product.refresh_from_db()
    assert product.primary_image_id == photo.pk


def test_delete_product_image(client, staff_user):
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    photo = services.add_product_image(product, image=upload())
    _login(client, staff_user)

    client.post(reverse("catalog_dashboard:product_image_delete", args=[product.pk, photo.pk]))

    assert not ProductImage.objects.filter(pk=photo.pk).exists()


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


def test_listing_list_renders(client, staff_user, listing):
    _login(client, staff_user)

    response = client.get(reverse("catalog_dashboard:listing_list"))

    assert response.status_code == 200


def test_create_listing_redirects_to_detail(client, staff_user):
    state = make_state()
    lga = make_lga(state)
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    _login(client, staff_user)

    response = client.post(
        reverse("catalog_dashboard:listing_create"),
        {
            "product": str(product.pk),
            "state": str(state.pk),
            "lga": str(lga.pk),
            "package_size": "25.000",
            "package_unit": str(unit().pk),
            "compare_at_price": "",
            "low_stock_threshold": "",
            "origin_verification": "unverified",
            "origin_note": "",
        },
    )

    assert response.status_code == 302
    listing = ProductListing.objects.get(product=product)
    assert reverse("catalog_dashboard:listing_detail", args=[listing.pk]) == response.url


def test_listing_detail_renders(client, staff_user, listing):
    _login(client, staff_user)

    response = client.get(reverse("catalog_dashboard:listing_detail", args=[listing.pk]))

    assert response.status_code == 200
    assert response.context["listing"].pk == listing.pk


def test_set_listing_price_through_dashboard(client, staff_user, listing):
    _login(client, staff_user)

    response = client.post(
        reverse("catalog_dashboard:listing_price", args=[listing.pk]),
        {"amount": "275.00", "compare_at": "", "price_type": "selling", "variant": ""},
    )

    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.selling_price == 275


def test_listing_status_change(client, staff_user, listing):
    _login(client, staff_user)

    client.post(
        reverse("catalog_dashboard:listing_status", args=[listing.pk]),
        {"status": "active"},
    )

    listing.refresh_from_db()
    assert listing.status == ListingStatus.ACTIVE


def test_archive_listing_action(client, staff_user, listing):
    _login(client, staff_user)

    client.post(reverse("catalog_dashboard:listing_archive", args=[listing.pk]))

    listing.refresh_from_db()
    assert listing.status == ListingStatus.ARCHIVED


# ---------------------------------------------------------------------------
# Variants, tiers & stock
# ---------------------------------------------------------------------------


def test_create_variant(client, staff_user, listing):
    _login(client, staff_user)

    client.post(
        reverse("catalog_dashboard:variant_create", args=[listing.pk]),
        {"name": "Grade A", "notes": "", "sort_order": "0"},
    )

    assert ProductVariant.objects.filter(listing=listing, name="Grade A").exists()


def test_sales_officer_cannot_adjust_stock(client, staff_user, listing):
    _login(client, staff_user)

    response = client.post(
        reverse("catalog_dashboard:listing_stock", args=[listing.pk]),
        {"kind": "adjustment", "delta": "10", "reference": "", "note": ""},
    )

    assert response.status_code == 403
    listing.refresh_from_db()
    assert listing.stock_on_hand == 0


def test_inventory_officer_can_adjust_stock(client, inventory_officer, listing):
    _login(client, inventory_officer)

    response = client.post(
        reverse("catalog_dashboard:listing_stock", args=[listing.pk]),
        {"kind": "adjustment", "delta": "10", "reference": "", "note": ""},
    )

    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.stock_on_hand == 10


def test_create_and_delete_wholesale_tier(client, staff_user, listing):
    _login(client, staff_user)

    client.post(
        reverse("catalog_dashboard:tier_create", args=[listing.pk]),
        {"variant": "", "min_quantity": "10", "price": "9000.00"},
    )
    tier = WholesalePriceTier.objects.get(listing=listing)

    client.post(reverse("catalog_dashboard:tier_delete", args=[tier.pk]))

    assert not WholesalePriceTier.objects.filter(pk=tier.pk).exists()


# ---------------------------------------------------------------------------
# Low stock & references
# ---------------------------------------------------------------------------


def test_low_stock_lists_only_low_threshold_listings(client, inventory_officer):
    state = make_state()
    category = make_category(name="Grains")
    low = make_listing(make_product(category, name="Maize"), state, make_lga(state))
    healthy = make_listing(
        make_product(category, name="Rice"), state, make_lga(state), package_size="25.000"
    )
    for listing, stock in ((low, "5.000"), (healthy, "50.000")):
        services.adjust_stock(listing, delta=stock)
        services.update_listing(listing, low_stock_threshold="10.000")
        services.set_listing_status(listing, status=ListingStatus.ACTIVE)
    _login(client, inventory_officer)

    response = client.get(reverse("catalog_dashboard:low_stock"))
    results = list(response.context["listings"])

    assert results == [low]


def test_create_market_reference(client, staff_user):
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    _login(client, staff_user)

    response = client.post(
        reverse("catalog_dashboard:reference_create"),
        {
            "product": str(product.pk),
            "state": "",
            "year": "2026",
            "season": "Dry",
            "price_per_unit": "500.00",
            "unit": str(unit().pk),
            "source": "Field survey",
            "note": "",
        },
    )

    assert response.status_code == 302
    assert MarketReferencePrice.objects.filter(product=product, year=2026).exists()


def test_edit_market_reference(client, staff_user):
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    reference = services.record_market_reference(
        product, year=2026, price_per_unit="500.00", unit=unit()
    )
    _login(client, staff_user)

    response = client.post(
        reverse("catalog_dashboard:reference_edit", args=[reference.pk]),
        {
            "product": str(product.pk),
            "state": "",
            "year": "2026",
            "season": "",
            "price_per_unit": "550.00",
            "unit": str(unit().pk),
            "source": "",
            "note": "",
        },
    )

    assert response.status_code == 302
    reference.refresh_from_db()
    assert reference.price_per_unit == 550

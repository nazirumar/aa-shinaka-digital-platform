"""Phase 4 tests: product lifecycle, publish rules, delete rules and audit."""

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
from django.core.exceptions import ValidationError

from apps.catalog import services
from apps.catalog.models import ListingStatus, Product, PublishStatus
from apps.dashboard.models import AuditLog

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Creation & slugs
# ---------------------------------------------------------------------------


def test_create_product_starts_as_draft_with_generated_slug():
    category = make_category(name="Grains")

    product = make_product(category, name="Yellow Maize")

    assert product.status == PublishStatus.DRAFT
    assert product.slug == "yellow-maize"
    assert product.unit_id == unit().pk


def test_product_slug_collisions_are_suffixed():
    category = make_category(name="Grains")

    first = make_product(category, name="Maize")
    second = make_product(category, name="Maize")

    assert first.slug == "maize"
    assert second.slug == "maize-2"


def test_create_product_records_tags():
    category = make_category(name="Grains")
    tag = services.ensure_tag("Premium")

    product = make_product(category, name="Maize", tags=[tag])

    assert list(product.tags.values_list("name", flat=True)) == ["Premium"]


def test_create_product_writes_an_audit_entry():
    category = make_category(name="Grains")

    product = make_product(category, name="Maize")

    entry = AuditLog.objects.get(action="catalog.product.create", target_id=str(product.pk))
    assert entry.after["name"] == "Maize"


# ---------------------------------------------------------------------------
# Publish validation
# ---------------------------------------------------------------------------


def _ready_for_publish(*, with_image=True, with_listing=True, with_unit=True):
    category = make_category(name="Grains")
    state = make_state()
    lga = make_lga(state)
    product = services.create_product(
        name="Maize", category=category, unit=unit() if with_unit else None
    )
    if with_image:
        services.add_product_image(product, image=upload())
    if with_listing:
        listing = make_listing(product, state, lga)
        services.set_listing_status(listing, status=ListingStatus.ACTIVE)
    return product


def test_publish_requires_a_unit():
    product = _ready_for_publish(with_unit=False)

    with pytest.raises(ValidationError):
        services.set_product_status(product, status=PublishStatus.PUBLISHED)


def test_publish_requires_an_image():
    product = _ready_for_publish(with_image=False)

    with pytest.raises(ValidationError):
        services.set_product_status(product, status=PublishStatus.PUBLISHED)


def test_publish_requires_an_active_listing():
    product = _ready_for_publish(with_listing=False)

    with pytest.raises(ValidationError):
        services.set_product_status(product, status=PublishStatus.PUBLISHED)


def test_publish_succeeds_when_all_requirements_are_met():
    product = _ready_for_publish()

    services.set_product_status(product, status=PublishStatus.PUBLISHED)

    product.refresh_from_db()
    assert product.status == PublishStatus.PUBLISHED
    assert product.is_featured is False


def test_set_product_status_rejects_unknown_status():
    product = _ready_for_publish()

    with pytest.raises(ValidationError):
        services.set_product_status(product, status="nonsense")


def test_archiving_a_product_is_a_status_change():
    product = _ready_for_publish()
    services.set_product_status(product, status=PublishStatus.PUBLISHED)

    services.archive_product(product)

    product.refresh_from_db()
    assert product.status == PublishStatus.ARCHIVED


# ---------------------------------------------------------------------------
# Delete rules
# ---------------------------------------------------------------------------


def test_published_products_are_archived_not_deleted():
    product = _ready_for_publish()
    services.set_product_status(product, status=PublishStatus.PUBLISHED)

    with pytest.raises(ValidationError):
        services.delete_product(product)

    assert Product.objects.filter(pk=product.pk).exists()


def test_product_with_listings_cannot_be_deleted():
    product = _ready_for_publish()

    with pytest.raises(ValidationError):
        services.delete_product(product)

    assert Product.objects.filter(pk=product.pk).exists()


def test_untouched_draft_can_be_hard_deleted():
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")

    services.delete_product(product)

    assert not Product.all_objects.filter(pk=product.pk).exists()


def test_product_delete_writes_audit_entry():
    category = make_category(name="Grains")
    product = make_product(category, name="Maize")
    product_pk = product.pk

    services.delete_product(product)

    assert AuditLog.objects.filter(
        action="catalog.product.delete", target_id=str(product_pk)
    ).exists()

"""Reusable builders for the Phase 4 catalogue tests.

Arranging fixtures may write directly to the ORM; anything that is itself the
behaviour under test goes through ``apps.catalog.services`` so the tests cover
the real write path (validation, auditing, price/stock ledgers).
"""

from __future__ import annotations

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog import services
from apps.catalog.models import (
    Category,
    ListingStatus,
    Product,
    ProductListing,
    PublishStatus,
    UnitOfMeasure,
)
from apps.locations.models import LGA, Country, State


def unit(code: str = "kg") -> UnitOfMeasure:
    return UnitOfMeasure.objects.get(code=code)


def png_bytes(size: tuple[int, int] = (4, 4)) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


def upload(name: str = "produce.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, png_bytes(), content_type="image/png")


def make_state(name: str = "Kaduna", code: str = "KD", zone: str = "NW") -> State:
    country, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria"})
    state, _ = State.objects.get_or_create(
        name=name, defaults={"code": code, "zone": zone, "country": country}
    )
    return state


def make_lga(state: State, name: str = "Zaria", code: str = "ZA") -> LGA:
    lga, _ = LGA.objects.get_or_create(state=state, name=name, defaults={"code": code})
    return lga


def make_category(name: str = "Grains", **kwargs) -> Category:
    return services.create_category(name=name, **kwargs)


def make_product(category: Category, *, name: str = "Maize", unit_code: str = "kg", **kwargs):
    return services.create_product(name=name, category=category, unit=unit(unit_code), **kwargs)


def make_listing(
    product: Product,
    state: State,
    lga: LGA,
    *,
    package_size: str = "50.000",
    price: str = "25000.00",
    **kwargs,
) -> ProductListing:
    package_unit_code = kwargs.pop("package_unit_code", "kg")
    return services.create_listing(
        product=product,
        state=state,
        lga=lga,
        package_size=package_size,
        package_unit=unit(package_unit_code),
        selling_price=price,
        **kwargs,
    )


def make_sellable_product(
    *,
    category: Category | None = None,
    state: State | None = None,
    lga: LGA | None = None,
    name: str = "Maize",
    price: str = "25000.00",
    stock: str = "100.000",
    featured: bool = False,
    publish: bool = True,
) -> tuple[Product, ProductListing]:
    """Return ``(product, listing)`` ready for public catalogue tests."""
    category = category or Category.objects.filter(name="Grains", parent__isnull=True).first()
    if category is None:
        category = make_category()
    state = state or make_state()
    lga = lga or make_lga(state)
    product = make_product(category, name=name)
    if featured:
        product.is_featured = True
        product.save(update_fields=["is_featured", "updated_at"])
    services.add_product_image(product, image=upload())
    listing = make_listing(product, state, lga, price=price)
    services.adjust_stock(listing, delta=stock)
    services.set_listing_status(listing, status=ListingStatus.ACTIVE)
    if publish:
        services.set_product_status(product, status=PublishStatus.PUBLISHED)
    return product, listing

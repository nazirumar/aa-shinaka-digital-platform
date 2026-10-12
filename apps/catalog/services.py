"""Write operations for the catalogue (service layer).

Every sensitive mutation goes through here so it is validated, transactional
where multi-step, and recorded in the audit log. Views stay thin. Prices are
always written as ``DecimalField`` rows and never hardcoded.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.audit import record_audit

from . import inventory
from .models import (
    Category,
    ListingPrice,
    ListingStatus,
    MarketReferencePrice,
    PriceHistory,
    PriceType,
    Product,
    ProductImage,
    ProductListing,
    ProductVariant,
    PublishStatus,
    StockMovement,
    StockMovementKind,
    Tag,
    UnitOfMeasure,
    Warehouse,
    WholesalePriceTier,
)

# Sentinel for update helpers: distinguishes "field not supplied" from an
# explicit reset (e.g. moving a category back to the root with ``parent=None``).
_UNSET = object()


def _actor(user):
    return user if getattr(user, "is_authenticated", False) else None


def _as_decimal(value):
    """Coerce a decimal-ish value (str/Decimal/int) to ``Decimal`` or ``None``."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid decimal amount.") from exc


# ---------------------------------------------------------------------------
# Tags & units
# ---------------------------------------------------------------------------


def ensure_tag(name: str) -> Tag:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Tag name is required.")
    return Tag.objects.get_or_create(name=name)[0]


def ensure_unit(code: str) -> UnitOfMeasure:
    code = (code or "").strip()
    if not code:
        raise ValidationError("A unit is required.")
    unit = UnitOfMeasure.objects.filter(code__iexact=code).first()
    if unit is None:
        raise ValidationError(f"Unknown unit of measure '{code}'.")
    return unit


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def create_category(
    *,
    name: str,
    parent: Category | None = None,
    description: str = "",
    image=None,
    is_active: bool = True,
    is_featured: bool = False,
    sort_order: int = 0,
    seo_title: str = "",
    seo_description: str = "",
    actor=None,
    request=None,
) -> Category:
    category = Category(
        name=name,
        parent=parent,
        description=description,
        image=image,
        is_active=is_active,
        is_featured=is_featured,
        sort_order=sort_order,
        seo_title=seo_title,
        seo_description=seo_description,
    )
    category.full_clean(exclude=["image"])
    category.save()
    record_audit(
        actor=actor,
        action="catalog.category.create",
        target=category,
        after={"name": category.name, "parent": str(parent.pk) if parent else None},
        request=request,
    )
    return category


def update_category(
    category: Category,
    *,
    name=None,
    parent=_UNSET,
    description=None,
    image=None,  # noqa: PLR0913
    clear_image: bool = False,
    is_active=None,
    is_featured=None,
    sort_order=None,
    seo_title=None,
    seo_description=None,
    actor=None,
    request=None,
) -> Category:
    before = {"name": category.name, "is_active": category.is_active}
    if name is not None:
        category.name = name
    if parent is not _UNSET:
        category.parent = parent
    fields = {
        "description": description,
        "image": image,
        "is_active": is_active,
        "is_featured": is_featured,
        "sort_order": sort_order,
        "seo_title": seo_title,
        "seo_description": seo_description,
    }
    for field, value in fields.items():
        if value is not None:
            setattr(category, field, value)
    if clear_image:
        category.image = None
    category.full_clean(exclude=["image"])
    category.save()
    record_audit(
        actor=actor,
        action="catalog.category.update",
        target=category,
        before=before,
        after={"name": category.name, "is_active": category.is_active},
        request=request,
    )
    return category


def archive_category(category: Category, *, actor=None, request=None) -> None:
    """Soft-delete a category (refused while children/products reference it)."""
    category.delete()  # Category.delete() raises if not empty
    record_audit(
        actor=actor,
        action="catalog.category.archive",
        target=category,
        after={"name": category.name},
        request=request,
    )


def reorder_category(category: Category, *, step: int, actor=None, request=None) -> None:
    """Move a category up/down among its siblings by swapping ``sort_order``."""
    siblings = Category.objects.filter(parent=category.parent)
    ordered = list(siblings.order_by("sort_order", "name"))
    index = next(i for i, item in enumerate(ordered) if item.pk == category.pk)
    target = index + step
    if target < 0 or target >= len(ordered):
        return
    ordered[index], ordered[target] = ordered[target], ordered[index]
    for position, item in enumerate(ordered):
        item.sort_order = position
        item.save(update_fields=["sort_order", "updated_at"])
    record_audit(
        actor=actor,
        action="catalog.category.reorder",
        target=category,
        after={"name": category.name, "sort_order": category.sort_order},
        request=request,
    )


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


def _validate_publishable(product: Product) -> None:
    if not product.category_id:
        raise ValidationError("A published product needs a category.")
    if not product.unit_id:
        raise ValidationError("A published product needs a unit of measure.")
    if not ProductImage.objects.filter(product=product).exists():
        raise ValidationError("A published product needs at least one image.")
    if not ProductListing.objects.filter(product=product, status=ListingStatus.ACTIVE).exists():
        raise ValidationError("A published product needs at least one active listing.")


def create_product(
    *,
    name: str,
    category: Category,
    short_description: str = "",
    description: str = "",
    unit: UnitOfMeasure | None = None,
    variety: str = "",
    grade: str = "",
    harvest_season: str = "",
    tags: list[Tag] | None = None,
    seo_title: str = "",
    seo_description: str = "",
    actor=None,
    request=None,
) -> Product:
    product = Product(
        name=name,
        category=category,
        short_description=short_description,
        description=description,
        unit=unit,
        variety=variety,
        grade=grade,
        harvest_season=harvest_season,
        seo_title=seo_title,
        seo_description=seo_description,
        status=PublishStatus.DRAFT,  # products always start as drafts
    )
    product.save()
    if tags:
        product.tags.set(tags)
    record_audit(
        actor=actor,
        action="catalog.product.create",
        target=product,
        after={"name": product.name, "category": category.name},
        request=request,
    )
    return product


def update_product(  # noqa: PLR0913
    product: Product,
    *,
    name=None,
    category=None,
    short_description=None,
    description=None,
    unit=None,
    variety=None,
    grade=None,
    harvest_season=None,
    tags=None,
    seo_title=None,
    seo_description=None,
    actor=None,
    request=None,
) -> Product:
    before = {"name": product.name, "status": product.status}
    for field in (
        "name",
        "category",
        "short_description",
        "description",
        "unit",
        "variety",
        "grade",
        "harvest_season",
        "seo_title",
        "seo_description",
    ):
        value = locals()[field]
        if value is not None:
            setattr(product, field, value)
    product.full_clean()
    product.save()
    if tags is not None:
        product.tags.set(tags)
    record_audit(
        actor=actor,
        action="catalog.product.update",
        target=product,
        before=before,
        after={"name": product.name, "status": product.status},
        request=request,
    )
    return product


def set_product_status(product: Product, *, status: str, actor=None, request=None) -> Product:
    if status not in PublishStatus.values:
        raise ValidationError(f"Unknown product status '{status}'.")
    if status == PublishStatus.PUBLISHED:
        _validate_publishable(product)
    before = {"status": product.status}
    product.status = status
    product.save(update_fields=["status", "updated_at"])
    record_audit(
        actor=actor,
        action="catalog.product.status",
        target=product,
        before=before,
        after={"status": status},
        request=request,
    )
    return product


def archive_product(product: Product, *, actor=None, request=None) -> Product:
    return set_product_status(product, status=PublishStatus.ARCHIVED, actor=actor, request=request)


def delete_product(product: Product, *, actor=None, request=None) -> None:
    """Permanent removal is only for never-published drafts; enforced here."""
    if product.status == PublishStatus.PUBLISHED:
        raise ValidationError("Published products are archived, not deleted.")
    has_ledger = (
        ListingPrice.objects.filter(listing__product=product).exists()
        or StockMovement.objects.filter(listing__product=product).exists()
    )
    if product.listings.exists() or has_ledger:
        raise ValidationError(
            "Products referenced by listings or price/stock history are archived, not deleted."
        )
    # Audit before the hard delete so the (now-cleared) pk is still recorded.
    record_audit(
        actor=actor,
        action="catalog.product.delete",
        target=product,
        before={"name": product.name},
        request=request,
    )
    product.hard_delete()


# ---------------------------------------------------------------------------
# Product images
# ---------------------------------------------------------------------------


def add_product_image(
    product: Product,
    *,
    image,
    alt_text: str = "",
    sort_order: int = 0,
    listing: ProductListing | None = None,
    set_primary: bool = False,
    actor=None,
    request=None,
) -> ProductImage:
    photo = ProductImage(
        product=product, listing=listing, image=image, alt_text=alt_text, sort_order=sort_order
    )
    photo.full_clean(exclude=["image"])
    photo.save()
    if set_primary or product.primary_image_id is None:
        product.primary_image = photo
        product.save(update_fields=["primary_image", "updated_at"])
    record_audit(
        actor=actor,
        action="catalog.product.image.add",
        target=photo,
        after={"product": product.name, "image": photo.image.name},
        request=request,
    )
    return photo


def remove_product_image(photo: ProductImage, *, actor=None, request=None) -> None:
    product = photo.product
    if product.primary_image_id == photo.pk:
        product.primary_image = None
        product.save(update_fields=["primary_image", "updated_at"])
    record_audit(
        actor=actor,
        action="catalog.product.image.remove",
        target=photo,
        request=request,
    )
    photo.delete()


def set_primary_image(product: Product, photo: ProductImage, *, actor=None, request=None) -> None:
    if photo.product_id != product.pk:
        raise ValidationError("This image does not belong to the product.")
    product.primary_image = photo
    product.save(update_fields=["primary_image", "updated_at"])
    record_audit(
        actor=actor,
        action="catalog.product.image.primary",
        target=photo,
        request=request,
    )


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


def create_listing(
    *,
    product: Product,
    state,
    lga,
    package_size,
    package_unit,
    selling_price=0,
    compare_at_price=None,
    currency: str = "NGN",
    low_stock_threshold=None,
    origin_verification: str = "unverified",
    origin_note: str = "",
    actor=None,
    request=None,
) -> ProductListing:
    listing = ProductListing(
        product=product,
        state=state,
        lga=lga,
        package_size=package_size,
        package_unit=package_unit,
        selling_price=selling_price,
        compare_at_price=compare_at_price,
        currency=currency,
        low_stock_threshold=low_stock_threshold,
        origin_verification=origin_verification,
        origin_note=origin_note,
        status=ListingStatus.DRAFT,
    )
    listing.full_clean()
    listing.save()
    # Record the opening price row + history so the ledger is complete.
    PriceHistory.objects.create(
        listing=listing,
        old_price=0,
        new_price=selling_price,
        currency=currency,
        changed_by=_actor(actor),
        note="Opening price",
    )
    ListingPrice.objects.create(
        listing=listing,
        amount=selling_price,
        compare_at=compare_at_price,
        currency=currency,
        price_type=PriceType.SELLING,
        created_by=_actor(actor),
    )
    record_audit(
        actor=actor,
        action="catalog.listing.create",
        target=listing,
        after={"product": product.name, "state": state.name, "lga": lga.name},
        request=request,
    )
    return listing


def update_listing(
    listing: ProductListing,
    *,
    product=None,
    state=None,
    lga=None,  # noqa: PLR0913
    package_size=None,
    package_unit=None,
    compare_at_price=None,
    low_stock_threshold=None,
    origin_verification=None,
    origin_note=None,
    actor=None,
    request=None,
) -> ProductListing:
    before = {"product": listing.product.name, "state": listing.state.name}
    changed: list[str] = []
    for field in (
        "product",
        "state",
        "lga",
        "package_size",
        "package_unit",
        "compare_at_price",
        "low_stock_threshold",
        "origin_verification",
        "origin_note",
    ):
        value = locals()[field]
        if value is not None:
            setattr(listing, field, value)
            changed.append(field)
    listing.full_clean()
    # Save only the touched fields so a caller's stale copy (e.g. after
    # ``adjust_stock`` mutates stock under a row lock) cannot clobber columns
    # it did not intend to write.
    if changed:
        listing.save(update_fields=[*changed, "updated_at"])
    record_audit(
        actor=actor,
        action="catalog.listing.update",
        target=listing,
        before=before,
        after={"product": listing.product.name, "state": listing.state.name},
        request=request,
    )
    return listing


def set_listing_status(
    listing: ProductListing, *, status: str, actor=None, request=None
) -> ProductListing:
    if status not in ListingStatus.values:
        raise ValidationError(f"Unknown listing status '{status}'.")
    before = {"status": listing.status}
    listing.status = status
    listing.full_clean()
    listing.save(update_fields=["status", "updated_at"])
    record_audit(
        actor=actor,
        action="catalog.listing.status",
        target=listing,
        before=before,
        after={"status": status},
        request=request,
    )
    return listing


def archive_listing(listing: ProductListing, *, actor=None, request=None) -> ProductListing:
    """Archive a listing by moving it to the ``archived`` status.

    Listings are never deleted — price and stock history keep pointing at them —
    so archiving hides the offer from the public catalogue without losing data.
    """
    before = {"status": listing.status}
    listing.status = ListingStatus.ARCHIVED
    listing.full_clean()
    listing.save(update_fields=["status", "updated_at"])
    record_audit(
        actor=actor,
        action="catalog.listing.archive",
        target=listing,
        before=before,
        after={"status": listing.status},
        request=request,
    )
    return listing


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


def create_variant(
    listing: ProductListing,
    *,
    name: str,
    notes: str = "",  # noqa: PLR0913
    sort_order: int = 0,
    actor=None,
    request=None,
) -> ProductVariant:
    variant = ProductVariant(listing=listing, name=name, notes=notes, sort_order=sort_order)
    variant.full_clean()
    variant.save()
    record_audit(
        actor=actor,
        action="catalog.listing.variant.create",
        target=variant,
        after={"listing": str(listing.pk), "name": name},
        request=request,
    )
    return variant


# ---------------------------------------------------------------------------
# Pricing engine
# ---------------------------------------------------------------------------


def _window_conflicts(queryset, valid_from, valid_to, exclude_pk=None):
    """Rows whose window intersects [valid_from, valid_to); NULLs mean unbounded."""
    vf = valid_from or timezone.datetime.min.replace(tzinfo=timezone.utc)
    vt = valid_to or timezone.datetime.max.replace(tzinfo=timezone.utc)
    queryset = queryset.filter(
        Q(valid_from__isnull=True) | Q(valid_from__lt=vt),
        Q(valid_to__isnull=True) | Q(valid_to__gt=vf),
        ~Q(valid_from__isnull=True, valid_to__isnull=True),
    )
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset


def set_listing_price(
    listing: ProductListing,
    *,
    amount,
    compare_at=None,
    price_type: str = PriceType.SELLING,
    variant: ProductVariant | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    actor=None,
    request=None,
) -> ListingPrice:
    """Set a listing price, keeping ``ListingPrice`` + ``PriceHistory`` in sync.

    The listing's denormalised ``selling_price`` is only updated when the new
    price is effective now; scheduled (future) prices coexist and take over
    through the price selector when their window opens.
    """
    amount = _as_decimal(amount)
    compare_at = _as_decimal(compare_at)
    if amount is None or amount < 0:
        raise ValidationError("Price must be a non-negative decimal amount.")
    if compare_at is not None and compare_at < 0:
        raise ValidationError("Compare-at price must be non-negative.")
    if valid_from and valid_to and valid_from > valid_to:
        raise ValidationError("'Valid from' must be before 'Valid to'.")
    if price_type not in PriceType.values:
        raise ValidationError(f"Unknown price type '{price_type}'.")

    before = {"selling_price": str(listing.selling_price)}
    now = timezone.now()
    effective_now = (valid_from is None or valid_from <= now) and (
        valid_to is None or valid_to >= now
    )
    with transaction.atomic():
        scope = ListingPrice.objects.filter(
            listing=listing, variant=variant, price_type=price_type, is_active=True
        )
        if valid_from or valid_to:
            conflicts = _window_conflicts(scope, valid_from, valid_to)
            if conflicts.exists():
                raise ValidationError(
                    "An overlapping price window already exists for this listing."
                )
        previous = scope.order_by("-created_at").first()
        previous_amount = previous.amount if previous else listing.selling_price
        if effective_now:
            # Retire the prices this one supersedes *before* inserting, so the
            # partial unique index (one open-ended active price per scope) holds.
            # Future-scheduled windows are preserved.
            scope.filter(Q(valid_from__isnull=True) | Q(valid_from__lte=now)).update(
                is_active=False
            )
        price = ListingPrice.objects.create(
            listing=listing,
            variant=variant,
            price_type=price_type,
            amount=amount,
            compare_at=compare_at,
            currency=listing.currency,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=_actor(actor),
        )
        if effective_now:
            PriceHistory.objects.create(
                listing=listing,
                variant=variant,
                price_type=price_type,
                old_price=previous_amount,
                new_price=amount,
                currency=listing.currency,
                changed_by=_actor(actor),
                note="Price updated.",
            )
            # Only a base (no-variant) price defines the listing's headline price.
            if variant is None:
                listing.selling_price = amount
                listing.compare_at_price = compare_at
                listing.save(update_fields=["selling_price", "compare_at_price", "updated_at"])
        record_audit(
            actor=actor,
            action="catalog.listing.price.set",
            target=listing,
            before=before,
            after={"amount": str(amount), "price_type": price_type},
            request=request,
        )
        return price


def set_variant_price(
    listing: ProductListing,
    *,
    variant: ProductVariant,
    amount,  # noqa: PLR0913
    compare_at=None,
    valid_from=None,
    valid_to=None,
    actor=None,
    request=None,
):
    return set_listing_price(
        listing,
        amount=amount,
        compare_at=compare_at,
        variant=variant,
        valid_from=valid_from,
        valid_to=valid_to,
        actor=actor,
        request=request,
    )


# ---------------------------------------------------------------------------
# Wholesale tiers
# ---------------------------------------------------------------------------


def set_wholesale_tier(
    listing: ProductListing,
    *,
    min_quantity,
    price,
    variant: ProductVariant | None = None,
    actor=None,
    request=None,
) -> WholesalePriceTier:
    """Create or update a bulk price tier for a listing (FR-PRICE-9)."""
    min_quantity = _as_decimal(min_quantity)
    price = _as_decimal(price)
    if min_quantity is None or min_quantity <= 0:
        raise ValidationError("Tier minimum quantity must be positive.")
    if price is None or price < 0:
        raise ValidationError("Tier price must be a non-negative decimal amount.")

    with transaction.atomic():
        tier, created = WholesalePriceTier.objects.update_or_create(
            listing=listing,
            variant=variant,
            min_quantity=min_quantity,
            defaults={"price": price, "currency": listing.currency, "is_active": True},
        )
        record_audit(
            actor=actor,
            action="catalog.listing.tier.save",
            target=tier,
            after={
                "listing": str(listing.pk),
                "min_quantity": str(min_quantity),
                "price": str(price),
            },
            request=request,
        )
        return tier


def remove_wholesale_tier(tier: WholesalePriceTier, *, actor=None, request=None) -> None:
    record_audit(
        actor=actor,
        action="catalog.listing.tier.remove",
        target=tier,
        before={"listing": str(tier.listing_id), "min_quantity": str(tier.min_quantity)},
        request=request,
    )
    tier.delete()


# ---------------------------------------------------------------------------
# Inventory ledger
# ---------------------------------------------------------------------------


def adjust_stock(
    listing: ProductListing,
    *,
    delta,
    warehouse=None,
    variant: ProductVariant | None = None,
    kind: str = StockMovementKind.ADJUSTMENT,
    reference: str = "",
    note: str = "",
    actor=None,
    request=None,
) -> StockMovement:
    """Adjust stock through the warehouse ledger (Phase 5).

    Thin wrapper over ``inventory.adjust_stock`` so the listing roll-up and the
    per-warehouse ``StockBalance`` never drift. Defaults to the main warehouse.
    """
    return inventory.adjust_stock(
        listing,
        delta=delta,
        warehouse=warehouse,
        variant=variant,
        kind=kind,
        reference=reference,
        note=note,
        actor=actor,
        request=request,
    )


# ---------------------------------------------------------------------------
# Market reference prices
# ---------------------------------------------------------------------------


def record_market_reference(
    product: Product,
    *,
    year: int,
    price_per_unit,
    unit: UnitOfMeasure,
    state=None,
    season: str = "",
    source: str = "",
    note: str = "",
    actor=None,
    request=None,
) -> MarketReferencePrice:
    price_per_unit = _as_decimal(price_per_unit)
    if price_per_unit is None or price_per_unit < 0:
        raise ValidationError("Reference price must be non-negative.")
    reference, created = MarketReferencePrice.objects.update_or_create(
        product=product,
        state=state,
        year=year,
        season=season,
        unit=unit,
        defaults={
            "price_per_unit": price_per_unit,
            "source": source,
            "note": note,
        },
    )
    record_audit(
        actor=actor,
        action="catalog.market_reference.save",
        target=reference,
        after={"product": product.name, "year": year, "price": str(price_per_unit)},
        request=request,
    )
    return reference


# ---------------------------------------------------------------------------
# Warehouses (Phase 5 inventory)
# ---------------------------------------------------------------------------


def create_warehouse(
    *,
    name,
    code,
    address="",
    state=None,
    lga=None,
    is_active=True,
    actor=None,
    request=None,
) -> Warehouse:
    warehouse = Warehouse(
        name=name,
        code=code,
        address=address,
        state=state,
        lga=lga,
        is_active=is_active,
    )
    warehouse.full_clean()
    warehouse.save()
    record_audit(
        actor=actor,
        action="catalog.warehouse.create",
        target=warehouse,
        after={"name": warehouse.name, "code": warehouse.code},
        request=request,
    )
    return warehouse


def update_warehouse(
    warehouse: Warehouse,
    *,
    name=None,
    code=None,
    address=None,
    state=None,
    lga=None,
    is_active=None,
    actor=None,
    request=None,
) -> Warehouse:
    if name is not None:
        warehouse.name = name
    if code is not None:
        warehouse.code = code
    if address is not None:
        warehouse.address = address
    if state is not None:
        warehouse.state = state
    if lga is not None:
        warehouse.lga = lga
    if is_active is not None:
        warehouse.is_active = is_active
    warehouse.full_clean()
    warehouse.save()
    record_audit(
        actor=actor,
        action="catalog.warehouse.update",
        target=warehouse,
        after={"name": warehouse.name, "code": warehouse.code},
        request=request,
    )
    return warehouse

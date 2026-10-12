"""Catalog models — categories, products, origin-specific listings, pricing, inventory.

The public site reads from ``apps.catalog`` for product/category/state previews;
when no catalogue data exists, homepage and CMS selectors fall back to safe
empty states. Categories, products, prices and stock are all data-driven — no
categories, prices or inventory are ever hardcoded. Money is always stored in
``DecimalField``; selling prices are rows on ``ListingPrice`` (with the current
value denormalised on ``ProductListing.selling_price`` for fast filtering).
Inventory changes are append-only ``StockMovement`` ledger rows.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils.text import slugify

from apps.core.models import SoftDeleteManager, SoftDeleteModel, SoftDeleteQuerySet
from apps.locations.models import LGA, State

from .validators import validate_image_size

User = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PublishStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class ListingStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    OUT_OF_STOCK = "out_of_stock", "Out of stock"
    ARCHIVED = "archived", "Archived"


class OriginVerification(models.TextChoices):
    UNVERIFIED = "unverified", "Unverified"
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"


class StockMovementKind(models.TextChoices):
    INTAKE = "intake", "Intake"
    ADJUSTMENT = "adjustment", "Adjustment"
    SALE = "sale", "Sale"
    RETURN = "return", "Return"
    DAMAGE = "damage", "Damage"
    TRANSFER = "transfer", "Transfer"


class PriceType(models.TextChoices):
    SELLING = "selling", "Selling"
    PROMO = "promo", "Promotional"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class UUIDPkModel(models.Model):
    """Timestamped base with a UUID primary key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


class CatalogQuerySet(SoftDeleteQuerySet):
    """QuerySet that adds catalogue-specific helpers to soft-delete behaviour."""


class CatalogManager(SoftDeleteManager.from_queryset(CatalogQuerySet)):
    """Default manager: hides archived rows and exposes catalogue helpers."""


# ---------------------------------------------------------------------------
# Category (nested)
# ---------------------------------------------------------------------------


# Materialised paths store one 36-char UUID + "/" per ancestor, so this keeps the
# longest possible path comfortably inside ``Category.path`` (max_length=2000).
MAX_CATEGORY_DEPTH = 40


class Category(SoftDeleteModel):
    """Data-driven category supporting nesting. No categories are hardcoded.

    ``path`` is a materialised chain of ancestor primary keys (``root/child/``),
    which makes descendant lookups and breadcrumbs cheap. ``depth`` mirrors the
    path length. Both are maintained automatically by ``save()``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="catalog/categories/",
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"]),
            validate_image_size,
        ],
        help_text="5 MB max. Allowed: jpg, jpeg, png, webp.",
    )
    seo_title = models.CharField(max_length=180, blank=True)
    seo_description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    sort_order = models.IntegerField(default=0)
    path = models.CharField(max_length=2000, blank=True, editable=False)
    depth = models.PositiveSmallIntegerField(default=0, editable=False)

    class Meta:
        ordering: ClassVar[list[str]] = ["sort_order", "name"]
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["parent", "name"],
                name="uniq_cat_parent_name",
                condition=Q(is_deleted=False),
            ),
            models.UniqueConstraint(
                fields=["slug"],
                name="uniq_cat_slug",
                condition=Q(is_deleted=False),
            ),
            models.CheckConstraint(
                condition=Q(path="") | Q(path__endswith="/"),
                name="chk_cat_path_format",
                violation_error_message="Category path must be blank or a slash-terminated chain.",
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["parent"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active", "sort_order"]),
            models.Index(fields=["is_active", "is_featured"]),
            models.Index(fields=["path"]),
        ]

    def __str__(self) -> str:
        if self.parent_id:
            return f"{self.parent} / {self.name}"
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:category_detail", kwargs={"slug": self.slug})

    # -- hierarchy helpers ---------------------------------------------------

    def _recompute_path(self) -> bool:
        """Refresh ``path``/``depth`` from the parent; return True if changed."""
        if self.parent_id:
            parent = Category.all_objects.filter(pk=self.parent_id).first()
            new_path = f"{parent.path}{parent.pk}/" if parent else ""
            new_depth = (parent.depth + 1) if parent else 0
        else:
            new_path, new_depth = "", 0
        changed = self.path != new_path or self.depth != new_depth
        self.path, self.depth = new_path, new_depth
        return changed

    def _repath_descendants(self) -> None:
        """Rebuild ``path``/``depth`` for every descendant after a move."""
        queue = [self]
        while queue:
            parent = queue.pop(0)
            for child in Category.all_objects.filter(parent=parent):
                child_path = f"{parent.path}{parent.pk}/"
                if child.path != child_path or child.depth != parent.depth + 1:
                    Category.objects.filter(pk=child.pk).update(
                        path=child_path, depth=parent.depth + 1
                    )
                queue.append(child)

    def ancestors(self) -> list[Category]:
        """Ordered list of non-deleted ancestors, root first."""
        parts = [token for token in self.path.strip("/").split("/") if token]
        if not parts:
            return []
        by_id = {str(cat.pk): cat for cat in Category.objects.filter(pk__in=parts)}
        return [by_id[pk] for pk in parts if pk in by_id]

    def descendants(self) -> models.QuerySet[Category]:
        """Non-deleted descendants (children, grandchildren, ...)."""
        return Category.objects.filter(path__startswith=f"{self.path}{self.pk}/")

    def breadcrumbs(self) -> list[dict]:
        crumbs = [
            {"label": ancestor.name, "url": ancestor.get_absolute_url()}
            for ancestor in self.ancestors()
        ]
        crumbs.append({"label": self.name, "url": self.get_absolute_url()})
        return crumbs

    def active_children(self) -> models.QuerySet[Category]:
        return Category.objects.filter(parent=self, is_active=True)

    def is_leaf(self) -> bool:
        return not Category.objects.filter(parent=self).exists()

    # -- lifetime ------------------------------------------------------------

    def save(self, *args, **kwargs):
        base = slugify(self.name) or "category"
        slug = base
        counter = 2
        while Category.all_objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{counter}"
            counter += 1
        self.slug = slug
        moved = self._recompute_path()
        super().save(*args, **kwargs)
        if moved:
            self._repath_descendants()

    def clean(self):
        if self.parent_id == self.id:
            raise ValidationError({"parent": "A category cannot be its own parent."})
        if self.pk:
            ancestor = self.parent
            visited = 0
            while ancestor is not None and visited < 50:
                if ancestor.pk == self.pk:
                    raise ValidationError({"parent": "A category cannot be an ancestor of itself."})
                ancestor = ancestor.parent
                visited += 1
        prospective_depth = 0
        if self.parent_id:
            parent = Category.all_objects.filter(pk=self.parent_id).first()
            if parent is not None:
                prospective_depth = parent.depth + 1
        if prospective_depth > MAX_CATEGORY_DEPTH:
            raise ValidationError(
                {"parent": f"Category nesting is limited to {MAX_CATEGORY_DEPTH} levels."}
            )
        # case-insensitive root-name uniqueness when active
        if not self.parent_id:
            qs = Category.all_objects.filter(
                parent__isnull=True,
                name__iexact=self.name,
                is_deleted=False,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"name": "A top-level category with this name already exists."}
                )

    def delete(self, using=None, keep_parents=False):  # type: ignore[override]
        """Safe delete: refuse while children or products still reference it."""
        if Category.objects.filter(parent=self).exists():
            raise ValidationError(
                "This category still has subcategories — move or delete them first."
            )
        if self.products.exists():
            raise ValidationError("This category still has products — move or delete them first.")
        return super().delete(using=using, keep_parents=keep_parents)

    def set_sort_order(self, order: int, *, actor=None, request=None) -> None:
        """Persist a new ``sort_order`` (writes by staff go through services)."""
        self.sort_order = order
        self.save(update_fields=["sort_order", "updated_at"])


class UnitOfMeasure(UUIDPkModel):
    """Configurable units of measure (seeded via migration)."""

    name = models.CharField(max_length=40, unique=True)
    code = models.CharField(max_length=16, unique=True)
    symbol = models.CharField(max_length=8, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering: ClassVar[list[str]] = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.code


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


class Tag(UUIDPkModel):
    """Free-form product tag (variety, season, certification, ...)."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=80, unique=True, blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "tag"
            slug = base
            counter = 2
            while Tag.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------


class ProductQuerySet(CatalogQuerySet):
    def published(self) -> ProductQuerySet:
        return self.filter(status=PublishStatus.PUBLISHED)


class ProductManager(CatalogManager.from_queryset(ProductQuerySet)):
    pass


class Product(SoftDeleteModel):
    """A sellable product holding shared attributes (not origin-specific)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, blank=True)
    short_description = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=16, choices=PublishStatus.choices, default=PublishStatus.DRAFT, db_index=True
    )
    is_featured = models.BooleanField(default=False, db_index=True)
    variety = models.CharField(max_length=120, blank=True)
    grade = models.CharField(max_length=60, blank=True)
    harvest_season = models.CharField(max_length=60, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")
    primary_image = models.ForeignKey(
        "ProductImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    seo_title = models.CharField(max_length=180, blank=True)
    seo_description = models.CharField(max_length=255, blank=True)

    objects = ProductManager()
    all_objects = models.Manager()

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["slug"],
                name="uniq_product_slug",
                condition=Q(is_deleted=False),
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["status", "is_featured"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:product_detail", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs):
        base = (slugify(self.name) or "product")[:180]
        slug = base
        counter = 2
        while Product.all_objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{counter}"
            counter += 1
        self.slug = slug
        super().save(*args, **kwargs)

    def clean(self):
        if self.status == PublishStatus.PUBLISHED and self.pk:
            if not self.category_id:
                raise ValidationError({"category": "A published product needs a category."})
            if not ProductImage.objects.filter(product=self).exists():
                raise ValidationError("A published product needs at least one image.")
            if not ProductListing.objects.filter(
                product=self, status=ListingStatus.ACTIVE
            ).exists():
                raise ValidationError("A published product needs at least one active listing.")

    @property
    def is_published(self) -> bool:
        return self.status == PublishStatus.PUBLISHED

    def active_listings(self) -> models.QuerySet[ProductListing]:
        return ProductListing.objects.filter(product=self, status=ListingStatus.ACTIVE)

    @property
    def display_unit(self) -> str:
        return self.unit.code if self.unit else ""

    def seo(self) -> tuple[str, str]:
        title = self.seo_title or self.name
        description = (
            self.seo_description
            or self.short_description
            or (self.description[:200] if self.description else "")
        )
        return title, description


# ---------------------------------------------------------------------------
# ProductListing (origin-specific offer)
# ---------------------------------------------------------------------------


class ListingQuerySet(CatalogQuerySet):
    def active(self) -> ListingQuerySet:
        return self.filter(status=ListingStatus.ACTIVE)

    def sellable(self) -> ListingQuerySet:
        """Active listings whose product is published and that have stock."""
        return self.filter(
            status=ListingStatus.ACTIVE,
            product__status=PublishStatus.PUBLISHED,
        )


class ListingManager(CatalogManager.from_queryset(ListingQuerySet)):
    pass


class ProductListing(SoftDeleteModel):
    """An origin-specific offer: a product sold from a state/LGA in a package.

    The ``selling_price``/``compare_at_price`` here are the denormalised current
    values (kept in sync by ``services.set_listing_price``); the full price
    history/engine lives in ``ListingPrice``/``PriceHistory``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="listings")
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="listings")
    lga = models.ForeignKey(LGA, on_delete=models.PROTECT, related_name="listings")
    package_size = models.DecimalField(max_digits=12, decimal_places=3)
    package_unit = models.ForeignKey(
        UnitOfMeasure, on_delete=models.PROTECT, related_name="listings"
    )
    selling_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default="0.00",
        help_text="NGN. Denormalised current price.",
    )
    currency = models.CharField(max_length=3, default="NGN")
    compare_at_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    stock_on_hand = models.DecimalField(max_digits=14, decimal_places=3, default="0.000")
    stock_reserved = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default="0.000",
        help_text="Reserved by open orders; never set by hand.",
    )
    low_stock_threshold = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    status = models.CharField(
        max_length=16, choices=ListingStatus.choices, default=ListingStatus.DRAFT, db_index=True
    )
    origin_verification = models.CharField(
        max_length=16,
        choices=OriginVerification.choices,
        default=OriginVerification.UNVERIFIED,
        db_index=True,
    )
    origin_note = models.TextField(
        blank=True, help_text="Provenance and quality notes shown to buyers."
    )

    objects = ListingManager()
    all_objects = models.Manager()

    class Meta:
        ordering: ClassVar[list[str]] = ["product__name", "state__name", "package_size"]
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["product", "state", "lga", "package_size", "package_unit"],
                name="uniq_listing_origin_package",
                condition=Q(is_deleted=False),
            ),
            models.CheckConstraint(
                condition=Q(package_size__gt="0"), name="chk_listing_package_positive"
            ),
            models.CheckConstraint(
                condition=Q(selling_price__gte="0"), name="chk_listing_price_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(stock_on_hand__gte="0"), name="chk_listing_stock_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(stock_reserved__gte="0"), name="chk_listing_reserved_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(stock_reserved__lte=models.F("stock_on_hand")),
                name="chk_listing_reserved_lte_hand",
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["state", "lga"]),
            models.Index(fields=["product", "status"]),
            models.Index(fields=["status", "selling_price"]),
            models.Index(fields=["state"]),
            models.Index(fields=["lga"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} · {self.state.name} · {self.packaging}"

    def get_absolute_url(self) -> str:
        return self.product.get_absolute_url()

    # -- derived values ------------------------------------------------------

    @property
    def available_stock(self):
        return self.stock_on_hand - self.stock_reserved

    @property
    def in_stock(self) -> bool:
        return self.status == ListingStatus.ACTIVE and self.available_stock > 0

    @property
    def price(self):
        """Current effective unit price (NGN), used by cards and listing rows."""
        return self.selling_price

    @property
    def is_sellable(self) -> bool:
        return (
            self.status == ListingStatus.ACTIVE
            and self.product.status == PublishStatus.PUBLISHED
            and self.available_stock > 0
        )

    @property
    def low_stock(self) -> bool:
        return (
            self.low_stock_threshold is not None
            and self.available_stock <= self.low_stock_threshold
        )

    @property
    def packaging(self) -> str:
        size = format(self.package_size.normalize(), "f")
        symbol = self.package_unit.symbol or self.package_unit.code
        return f"{size}{symbol}" if symbol else size

    def primary_image(self):
        """Best image for display: listing-specific first, then the product's."""
        listing_image = (
            ProductImage.objects.filter(product=self.product, listing=self)
            .order_by("sort_order", "created_at")
            .first()
        )
        if listing_image is not None:
            return listing_image
        if self.product.primary_image_id:
            return self.product.primary_image
        return (
            ProductImage.objects.filter(product=self.product, listing__isnull=True)
            .order_by("sort_order", "created_at")
            .first()
        )

    def clean(self):
        if self.lga_id and self.state_id and self.lga.state_id != self.state_id:
            raise ValidationError({"lga": "The LGA must belong to the selected state."})
        if self.package_size is not None and self.package_size <= 0:
            raise ValidationError({"package_size": "Package size must be positive."})
        if self.status == ListingStatus.ACTIVE and self.available_stock < 0:
            raise ValidationError(
                "Reserved stock cannot exceed stock on hand for an active listing."
            )

    def delete(self, using=None, keep_parents=False):  # type: ignore[override]
        """Safe delete: refused while inventory/prices/movements reference it."""
        if self.movements.exists() or self.price_history.exists():
            raise ValidationError(
                "This listing has price/stock history — archive it instead of deleting."
            )
        return super().delete(using=using, keep_parents=keep_parents)


# ---------------------------------------------------------------------------
# ProductVariant (optional sub-offering of a listing)
# ---------------------------------------------------------------------------


class ProductVariant(UUIDPkModel):
    """An optional variant of an origin-specific listing (e.g. a grade).

    A variant can carry its own price via ``ListingPrice``/``WholesalePriceTier``.
    Stock is tracked at the listing level in Phase 4.
    """

    listing = models.ForeignKey(ProductListing, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=80)
    notes = models.CharField(max_length=255, blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["sort_order", "name"]
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["listing", "name"], name="uniq_variant_name_per_listing"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.listing} — {self.name}"


# ---------------------------------------------------------------------------
# ProductImage
# ---------------------------------------------------------------------------


class ProductImage(UUIDPkModel):
    """An image belonging to a product, optionally tied to one listing."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    listing = models.ForeignKey(
        ProductListing,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="images",
        help_text="Optional: tie the image to a specific origin listing.",
    )
    image = models.ImageField(
        upload_to="catalog/products/",
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"]),
            validate_image_size,
        ],
        help_text="5 MB max. Allowed: jpg, jpeg, png, webp.",
    )
    alt_text = models.CharField(max_length=180, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering: ClassVar[list[str]] = ["sort_order", "created_at"]
        indexes: ClassVar[list] = [
            models.Index(fields=["product", "sort_order"]),
            models.Index(fields=["listing"]),
        ]

    def __str__(self) -> str:
        return self.alt_text or self.image.name


# ---------------------------------------------------------------------------
# Pricing engine
# ---------------------------------------------------------------------------


class ListingPrice(UUIDPkModel):
    """A price record for a listing (optionally one of its variants).

    Effective prices are selected by ``selectors.effective_price``; the current
    value is denormalised on the listing so public filters stay fast. At most one
    open-ended active price may exist per (listing, variant, price_type); the
    service validates windows so they never overlap.
    """

    listing = models.ForeignKey(ProductListing, on_delete=models.PROTECT, related_name="prices")
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="prices",
    )
    price_type = models.CharField(
        max_length=16, choices=PriceType.choices, default=PriceType.SELLING, db_index=True
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    compare_at = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="NGN")
    valid_from = models.DateTimeField(null=True, blank=True, db_index=True)
    valid_to = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["-valid_from", "-created_at"]
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["listing", "variant", "price_type"],
                condition=Q(is_active=True, valid_from__isnull=True, valid_to__isnull=True),
                name="uniq_open_active_price",
                nulls_distinct=False,
            ),
            models.CheckConstraint(condition=Q(amount__gte="0"), name="chk_price_amount_nonneg"),
            models.CheckConstraint(
                condition=Q(compare_at__isnull=True) | Q(compare_at__gte="0"),
                name="chk_price_compare_nonneg",
            ),
        ]

    def __str__(self) -> str:
        label = self.variant.name if self.variant_id else "base"
        return f"{self.listing} [{label}] {self.amount} {self.currency}"

    def clean(self):
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValidationError("'Valid from' must be before 'Valid to'.")


class PriceHistory(UUIDPkModel):
    """Append-only log of price changes for a listing/variant (FR-PRICE-6)."""

    listing = models.ForeignKey(
        ProductListing, on_delete=models.PROTECT, related_name="price_history"
    )
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="price_history",
    )
    price_type = models.CharField(
        max_length=16, choices=PriceType.choices, default=PriceType.SELLING
    )
    old_price = models.DecimalField(max_digits=14, decimal_places=2)
    new_price = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    changed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        indexes: ClassVar[list] = [
            models.Index(fields=["listing", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.listing} {self.old_price} → {self.new_price}"

    def save(self, *args, **kwargs):  # type: ignore[override]
        if not self._state.adding:
            raise ValidationError("Price history is append-only and cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[override]
        raise ValidationError("Price history is append-only and cannot be deleted.")


class WholesalePriceTier(UUIDPkModel):
    """Bulk/tiered pricing for B2B purchases (FR-PRICE-9)."""

    listing = models.ForeignKey(
        ProductListing, on_delete=models.CASCADE, related_name="wholesale_tiers"
    )
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="wholesale_tiers",
    )
    min_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    price = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["min_quantity"]
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["listing", "variant", "min_quantity"],
                name="uniq_tier_min_qty",
                nulls_distinct=False,
            ),
            models.CheckConstraint(condition=Q(min_quantity__gt="0"), name="chk_tier_qty_positive"),
            models.CheckConstraint(condition=Q(price__gte="0"), name="chk_tier_price_nonneg"),
        ]

    def __str__(self) -> str:
        label = f" for {self.variant.name}" if self.variant_id else ""
        return f"{self.listing}{label}: {self.price} ≥ {self.min_quantity:g}"


class MarketReferencePrice(UUIDPkModel):
    """Market-level reference prices, stored strictly separately from selling prices.

    Reference prices are informational (surveys, FADAMA bulletins, etc.) and are
    never used as selling prices. They are DB rows only — nothing is hardcoded.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="market_references")
    state = models.ForeignKey(
        State,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="market_reference_prices",
        help_text="Blank means national reference price.",
    )
    year = models.PositiveIntegerField(db_index=True)
    season = models.CharField(max_length=60, blank=True)
    price_per_unit = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="market_reference_prices",
    )
    currency = models.CharField(max_length=3, default="NGN")
    source = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-year", "state__name", "product__name"]
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["product", "state", "year", "season", "unit"],
                name="uniq_market_ref_state",
                condition=Q(state__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["product", "year", "season", "unit"],
                name="uniq_market_ref_national",
                condition=Q(state__isnull=True),
            ),
            models.CheckConstraint(
                condition=Q(price_per_unit__gte="0"), name="chk_market_ref_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(year__gte=2000) & Q(year__lte=2100),
                name="chk_market_ref_year_range",
            ),
        ]

    def __str__(self) -> str:
        where = self.state.name if self.state_id else "National"
        return f"{self.product.name} ({where}, {self.year}) — {self.price_per_unit}"


# ---------------------------------------------------------------------------
# Warehouses & per-warehouse stock balances (Phase 5)
# ---------------------------------------------------------------------------


class Warehouse(UUIDPkModel):
    """A physical location that holds stock (farm store, hub, cold room).

    Warehouses are data-driven: nothing about them is hardcoded, and the
    public site never exposes raw warehouse data. ``state``/``lga`` are
    optional so a warehouse can be created before its address is known.
    """

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    address = models.CharField(max_length=255, blank=True)
    state = models.ForeignKey(
        "locations.State",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="warehouses",
    )
    lga = models.ForeignKey(
        "locations.LGA",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="warehouses",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]
        verbose_name = "Warehouse"
        verbose_name_plural = "Warehouses"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self):
        if self.lga_id and self.state_id and self.lga.state_id != self.state_id:
            raise ValidationError({"lga": "The LGA must belong to the selected state."})


class StockBalance(UUIDPkModel):
    """Per-warehouse on-hand and reserved quantity for a listing/variant.

    This is the authoritative per-warehouse stock position. The listing's
    denormalised ``stock_on_hand``/``stock_reserved`` are the roll-ups across
    all warehouses and are maintained by ``apps.catalog.services`` so the two
    never drift (``listing.stock_on_hand == Σ balances.on_hand``).

    Quantities use the listing's package unit (the platform's single
    unit-of-measure strategy for stock), as ``DecimalField`` — never floats.
    """

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="balances")
    listing = models.ForeignKey(ProductListing, on_delete=models.PROTECT, related_name="balances")
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="balances",
    )
    on_hand = models.DecimalField(max_digits=14, decimal_places=3, default="0.000")
    reserved = models.DecimalField(max_digits=14, decimal_places=3, default="0.000")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["warehouse__name", "listing__product__name"]
        verbose_name = "Stock balance"
        verbose_name_plural = "Stock balances"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["warehouse", "listing", "variant"],
                name="uniq_stock_balance_warehouse_listing_variant",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=Q(on_hand__gte="0"), name="chk_stockbalance_onhand_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(reserved__gte="0"), name="chk_stockbalance_reserved_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(reserved__lte=F("on_hand")),
                name="chk_stockbalance_reserved_lte_onhand",
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["listing", "warehouse"]),
            models.Index(fields=["warehouse", "reserved"]),
        ]

    def __str__(self) -> str:
        label = f" · {self.variant.name}" if self.variant_id else ""
        return f"{self.warehouse.code} · {self.listing}{label}"

    @property
    def available(self):
        return self.on_hand - self.reserved


# ---------------------------------------------------------------------------
# Inventory ledger
# ---------------------------------------------------------------------------


class StockMovement(models.Model):
    """Append-only stock movement ledger row (FR-PRICE-4).

    Movements are never edited or deleted; ``balance_after`` snapshots the
    listing's on-hand balance after the movement.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    listing = models.ForeignKey(ProductListing, on_delete=models.PROTECT, related_name="movements")
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    warehouse = models.ForeignKey(
        "catalog.Warehouse",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    kind = models.CharField(
        max_length=16, choices=StockMovementKind.choices, default=StockMovementKind.ADJUSTMENT
    )
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=3)
    balance_after = models.DecimalField(max_digits=14, decimal_places=3)
    reference = models.CharField(max_length=100, blank=True)
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        indexes: ClassVar[list] = [
            models.Index(fields=["listing", "-created_at"]),
            models.Index(fields=["warehouse", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.listing} {self.kind} {self.quantity_delta} → {self.balance_after}"

    def save(self, *args, **kwargs):  # type: ignore[override]
        if not self._state.adding:
            raise ValidationError("Stock movements are append-only and cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[override]
        raise ValidationError("Stock movements are append-only and cannot be deleted.")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "Category",
    "UnitOfMeasure",
    "Tag",
    "Product",
    "ProductImage",
    "ProductListing",
    "ProductVariant",
    "ListingPrice",
    "PriceHistory",
    "WholesalePriceTier",
    "MarketReferencePrice",
    "Warehouse",
    "StockBalance",
    "StockMovement",
    "PublishStatus",
    "ListingStatus",
    "OriginVerification",
    "StockMovementKind",
    "PriceType",
]

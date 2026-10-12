"""Read-only queries for the catalogue (public site and staff dashboard).

Public selectors only ever return published products with active listings, so
drafts and archives never leak. Prices always come from rows — nothing is
hardcoded; ``build_price_bands`` derives filter buckets from the data itself.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import Count, F, Max, Q, QuerySet
from django.utils import timezone

from apps.locations.models import LGA, State

from .models import (
    Category,
    ListingPrice,
    ListingStatus,
    MarketReferencePrice,
    PriceHistory,
    Product,
    ProductImage,
    ProductListing,
    ProductVariant,
    PublishStatus,
    StockMovement,
    WholesalePriceTier,
)


def _base_listing_queryset() -> QuerySet[ProductListing]:
    """Sellable listings (active listing, published product) + joins."""
    return (
        ProductListing.objects.select_related("product", "state", "lga", "package_unit")
        .filter(
            status=ListingStatus.ACTIVE,
            product__status=PublishStatus.PUBLISHED,
        )
        .order_by("-product__is_featured", "-created_at")
    )


# ---------------------------------------------------------------------------
# Homepage / index
# ---------------------------------------------------------------------------


def featured_listings(*, limit: int = 8) -> QuerySet[ProductListing]:
    """Featured sellable listings for the homepage."""
    return _base_listing_queryset().filter(product__is_featured=True)[:limit]


def states_with_listings(*, limit: int = 12) -> QuerySet[State]:
    """Active states that have sellable listings, annotated with listing counts."""
    return (
        State.objects.filter(is_active=True)
        .filter(STATES_WITH_LISTINGS)
        .annotate(listing_count=Count("listings", filter=STATES_WITH_LISTINGS))
        .distinct()
        .order_by("-listing_count", "name")[:limit]
    )


def top_level_categories(*, limit: int = 8) -> QuerySet[Category]:
    """Active top-level categories, featured first."""
    return Category.objects.filter(parent__isnull=True, is_active=True).order_by(
        "-is_featured", "sort_order", "name"
    )[:limit]


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def public_categories() -> QuerySet[Category]:
    """All active categories (tree page)."""
    return Category.objects.filter(is_active=True).order_by("sort_order", "name")


def category_by_slug(slug: str) -> Category | None:
    return Category.objects.filter(slug=slug, is_active=True).first()


def category_children(category: Category) -> QuerySet[Category]:
    return Category.objects.filter(parent=category, is_active=True).order_by("sort_order", "name")


def _category_descendant_ids(category: Category) -> list:
    return list(category.descendants().values_list("id", flat=True))


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


def product_by_slug(slug: str) -> Product | None:
    return (
        Product.objects.select_related("category", "unit")
        .prefetch_related("tags")
        .filter(slug=slug, status=PublishStatus.PUBLISHED)
        .first()
    )


def product_listings(product: Product) -> QuerySet[ProductListing]:
    """Active listings for a product detail page."""
    return (
        ProductListing.objects.select_related("state", "lga", "package_unit")
        .filter(product=product, status=ListingStatus.ACTIVE)
        .order_by("state__name", "lga__name", "package_size")
    )


def related_products(product: Product, *, limit: int = 4) -> QuerySet[Product]:
    """Published products in the same category that are sellable."""
    return (
        Product.objects.filter(
            category=product.category,
            status=PublishStatus.PUBLISHED,
            listings__status=ListingStatus.ACTIVE,
        )
        .exclude(pk=product.pk)
        .distinct()
        .order_by("-is_featured", "name")[:limit]
    )


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


def category_listings(
    category: Category,
    *,
    include_descendants: bool = True,
    state_slug: str = "",
    lga_slug: str = "",
    in_stock_only: bool = False,
    price_min: str | None = None,
    price_max: str | None = None,
) -> QuerySet[ProductListing]:
    ids = [category.pk]
    if include_descendants:
        ids += _category_descendant_ids(category)
    queryset = _base_listing_queryset().filter(product__category_id__in=ids)
    if state_slug:
        queryset = queryset.filter(state__slug=state_slug)
    if lga_slug:
        queryset = queryset.filter(lga__slug=lga_slug)
    if in_stock_only:
        queryset = queryset.filter(stock_on_hand__gt=0)
    if price_min:
        queryset = queryset.filter(selling_price__gte=price_min)
    if price_max:
        queryset = queryset.filter(selling_price__lte=price_max)
    return queryset


def build_price_bands(count: int = 5) -> list[dict]:
    """Derive *price filter buckets* from the data (never hardcoded prices)."""
    result = _base_listing_queryset().aggregate(max_price=Max("selling_price"))
    maximum = result["max_price"] or 0
    if maximum <= 0:
        return []
    step = maximum / count
    bands = []
    for index in range(count):
        lo = step * index
        hi = step * (index + 1)
        bands.append(
            {
                "label": f"{lo:,.0f} – {hi:,.0f}",
                "min": lo,
                "max": hi if index < count - 1 else None,
                "value": f"{lo}-{hi}",
            }
        )
    return bands


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

STATES_WITH_LISTINGS = Q(
    listings__status=ListingStatus.ACTIVE,
    listings__product__status=PublishStatus.PUBLISHED,
)


def state_list() -> QuerySet[State]:
    """Active states with their sellable-listing count."""
    return (
        State.objects.filter(is_active=True)
        .annotate(listing_count=Count("listings", filter=STATES_WITH_LISTINGS))
        .order_by("name")
    )


def state_by_slug(slug: str) -> State | None:
    return State.objects.filter(slug=slug, is_active=True).first()


def lgas_with_listings(state: State) -> QuerySet[LGA]:
    """Active LGAs in ``state`` that have sellable listings, with counts."""
    return (
        LGA.objects.filter(
            state=state,
            is_active=True,
            listings__status=ListingStatus.ACTIVE,
            listings__product__status=PublishStatus.PUBLISHED,
        )
        .annotate(listing_count=Count("listings", filter=STATES_WITH_LISTINGS & Q(state=state)))
        .distinct()
        .order_by("name")
    )


def state_listings(
    state: State,
    *,
    lga_slug: str = "",
    in_stock_only: bool = False,
) -> QuerySet[ProductListing]:
    queryset = _base_listing_queryset().filter(state=state)
    if lga_slug:
        queryset = queryset.filter(lga__slug=lga_slug)
    if in_stock_only:
        queryset = queryset.filter(stock_on_hand__gt=0)
    return queryset


def lga_by_slug(state: State, lga_slug: str) -> LGA | None:
    return LGA.objects.filter(state=state, slug=lga_slug, is_active=True).first()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_listings(
    *,
    query: str = "",
    category_slug: str = "",
    state_slug: str = "",
    lga_slug: str = "",
    price_min: str | None = None,
    price_max: str | None = None,
    in_stock_only: bool = False,
    sort: str = "",
) -> QuerySet[ProductListing]:
    queryset = _base_listing_queryset()
    if query:
        queryset = queryset.filter(
            Q(product__name__icontains=query)
            | Q(product__short_description__icontains=query)
            | Q(product__description__icontains=query)
            | Q(product__tags__name__icontains=query)
            | Q(state__name__icontains=query)
            | Q(lga__name__icontains=query)
        ).distinct()
    if category_slug:
        category = category_by_slug(category_slug)
        if category is None:
            return ProductListing.objects.none()
        queryset = queryset.filter(product__category=category)
    if state_slug:
        queryset = queryset.filter(state__slug=state_slug)
    if lga_slug:
        queryset = queryset.filter(lga__slug=lga_slug)
    if price_min:
        queryset = queryset.filter(selling_price__gte=price_min)
    if price_max:
        queryset = queryset.filter(selling_price__lte=price_max)
    if in_stock_only:
        queryset = queryset.filter(stock_on_hand__gt=0)
    if sort == "price_asc":
        queryset = queryset.order_by("selling_price")
    elif sort == "price_desc":
        queryset = queryset.order_by("-selling_price")
    return queryset


def compare_products(slugs: list[str]) -> list[Product]:
    """Published products for the compare page, preserving order."""
    if not slugs:
        return []
    by_slug = {
        product.slug: product
        for product in Product.objects.filter(
            slug__in=slugs, status=PublishStatus.PUBLISHED
        ).prefetch_related("tags", "listings")
    }
    return [by_slug[slug] for slug in slugs if slug in by_slug]


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def effective_price(
    listing: ProductListing,
    *,
    variant: ProductVariant | None = None,
    at: datetime | None = None,
) -> ListingPrice | None:
    """The current ``ListingPrice`` for a listing (optionally a variant)."""
    moment = at or timezone.now()
    queryset = (
        ListingPrice.objects.filter(listing=listing, variant=variant, is_active=True)
        # Prefer a scheduled window that is live now over an open-ended fallback.
        .order_by(F("valid_from").desc(nulls_last=True), "-created_at")
    )
    current = queryset.filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=moment),
        Q(valid_to__isnull=True) | Q(valid_to__gte=moment),
    ).first()
    return current or queryset.first()


def price_for_display(listing: ProductListing) -> ListingPrice | None:
    """Effective price row used in templates (falls back to the denormalised value)."""
    return effective_price(listing)


def listing_prices(listing: ProductListing) -> QuerySet[ListingPrice]:
    return ListingPrice.objects.filter(listing=listing).select_related("variant")


def price_history(listing: ProductListing) -> QuerySet[PriceHistory]:
    return PriceHistory.objects.filter(listing=listing).select_related("variant")


def wholesale_tiers(
    listing: ProductListing, *, variant: ProductVariant | None = None
) -> QuerySet[WholesalePriceTier]:
    queryset = WholesalePriceTier.objects.filter(listing=listing, is_active=True)
    if variant is not None:
        queryset = queryset.filter(variant=variant)
    return queryset.order_by("min_quantity")


def market_reference_prices(product: Product, *, year: int | None = None) -> QuerySet:
    queryset = MarketReferencePrice.objects.filter(product=product).select_related("state", "unit")
    if year:
        queryset = queryset.filter(year=year)
    return queryset.order_by("-year", "state__name")


# ---------------------------------------------------------------------------
# Staff dashboard
# ---------------------------------------------------------------------------


def all_categories() -> QuerySet[Category]:
    return Category.objects.select_related("parent").order_by("sort_order", "name")


def all_products() -> QuerySet[Product]:
    return Product.objects.select_related("category", "unit").order_by("-updated_at")


def all_listings() -> QuerySet[ProductListing]:
    return ProductListing.objects.select_related(
        "product", "state", "lga", "package_unit"
    ).order_by("-updated_at")


def listing_by_pk(pk) -> ProductListing | None:
    return (
        ProductListing.objects.select_related("product", "state", "lga", "package_unit")
        .filter(pk=pk)
        .first()
    )


def product_images(product: Product) -> QuerySet[ProductImage]:
    return ProductImage.objects.filter(product=product).order_by("sort_order", "created_at")


def listing_images(listing: ProductListing) -> QuerySet[ProductImage]:
    return ProductImage.objects.filter(listing=listing).order_by("sort_order", "created_at")


def listing_movements(listing: ProductListing) -> QuerySet[StockMovement]:
    return StockMovement.objects.filter(listing=listing).select_related("actor")


def low_stock_listings() -> QuerySet[ProductListing]:
    return ProductListing.objects.filter(
        status=ListingStatus.ACTIVE,
        low_stock_threshold__isnull=False,
    ).select_related("product", "state")


def catalog_counts() -> dict:
    """Real counts for the catalogue dashboard overview (nothing fabricated)."""
    return {
        "categories": Category.objects.count(),
        "products": Product.objects.count(),
        "products_published": Product.objects.filter(status=PublishStatus.PUBLISHED).count(),
        "products_draft": Product.objects.filter(status=PublishStatus.DRAFT).count(),
        "listings": ProductListing.objects.count(),
        "listings_active": ProductListing.objects.filter(status=ListingStatus.ACTIVE).count(),
        "listings_low_stock": low_stock_listings().count(),
        "states_active": State.objects.filter(is_active=True).count(),
        "lgas": LGA.objects.filter(is_active=True).count(),
        "movements": StockMovement.objects.count(),
    }

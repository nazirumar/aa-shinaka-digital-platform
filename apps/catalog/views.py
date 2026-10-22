"""Public catalogue views (``/shop/...`` and legacy aliases).

Thin, read-only views: queries live in ``selectors``; a handful of HTMX
partials power the dependent state → LGA dropdown and filter re-rendering. No
prices, categories or stock are hardcoded — everything comes from the database.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from apps.locations.models import LGA
from apps.seo import canonical_from_request, seo_context

from . import selectors

PAGE_SIZE = 12
COMPARE_LIMIT = 4


def _seo(
    *,
    title: str = "",
    description: str = "",
    canonical: str = "",
    noindex: bool = False,
    og_image=None,
    og_type: str = "website",
) -> dict:
    """SEO context for this app. Signature kept for existing call sites."""
    return seo_context(
        title=title,
        description=description,
        canonical=canonical,
        og_image=og_image,
        noindex=noindex,
        og_type=og_type,
    )


def _has_filters(request: HttpRequest) -> bool:
    """Whether the request narrows a listing with a query parameter.

    Filtered and paginated listing URLs are not distinct pages worth indexing;
    they consolidate their signals onto the base URL instead of competing with
    it (and with each other).
    """
    return bool(
        set(request.GET) & {"page", "state", "lga", "in_stock", "min_price", "max_price", "sort"}
    )


#: Legacy URL prefixes that still serve 200 (shared links in
#: ``docs/UI_UX_SPEC.md`` §5.2) mapped to their canonical ``/shop/...``
#: equivalents. These views are reachable by two URLs each; emitting the
#: canonical one from whichever alias served the request consolidates the
#: duplicate without redirecting away a working link.
#:
#: Note the segment differs between the index and the detail pages: the state
#: *index* is ``/shop/states/`` (plural) but a state *detail* is
#: ``/shop/state/<slug>/`` (singular), so the mapping cannot be a plain prefix
#: substitution. ``(legacy_prefix, canonical_prefix, keep_suffix)``.
_LEGACY_CANONICAL_PREFIXES = (
    # Detail pages first: ``/states/<slug>/`` → ``/shop/state/<slug>/``.
    ("/states/", "/shop/state/", True),
    ("/products/", "/shop/product/", True),
)


def _canonical(request: HttpRequest) -> str:
    """Canonical URL for a catalogue page, collapsing legacy aliases.

    ``/states/<slug>/`` canonicalises to ``/shop/state/<slug>/``,
    ``/states/`` to ``/shop/states/`` and ``/products/<slug>/`` to
    ``/shop/product/<slug>/``; every other catalogue path (and all query
    strings) falls through to :func:`canonical_from_request`.
    """
    path = request.path or ""
    if path == "/states/":
        return request.build_absolute_uri("/shop/states/")
    for legacy, canonical_prefix, keep_suffix in _LEGACY_CANONICAL_PREFIXES:
        if path.startswith(legacy):
            suffix = path[len(legacy) :].strip("/") if keep_suffix else ""
            target = canonical_prefix if not suffix else f"{canonical_prefix}{suffix}/"
            return request.build_absolute_uri(target)
    return canonical_from_request(request)


def _clean_decimal(value):
    """Return a ``Decimal`` for a well-formed query value, otherwise ``None``."""
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _page(request: HttpRequest, queryset):
    return Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))


def _filter_context(request: HttpRequest) -> dict:
    return {
        "selected_min_price": request.GET.get("min_price", ""),
        "selected_max_price": request.GET.get("max_price", ""),
        "in_stock_only": request.GET.get("in_stock") == "1",
    }


# ---------------------------------------------------------------------------
# Index & categories
# ---------------------------------------------------------------------------


def shop_index(request: HttpRequest) -> HttpResponse:
    context = {
        **_seo(
            title="Shop agricultural products",
            description=(
                "Browse agricultural products by category and Nigerian state of origin. "
                "Every listing shows its origin, package and current price."
            ),
        ),
        "categories": selectors.top_level_categories(limit=12),
        "featured_listings": selectors.featured_listings(limit=8),
        "states": selectors.state_list()[:8],
        "price_bands": selectors.build_price_bands(),
        "breadcrumbs": [{"label": "Home", "url": "core:home"}, {"label": "Shop"}],
    }
    return render(request, "catalog/shop_index.html", context)


def category_list(request: HttpRequest) -> HttpResponse:
    roots = list(selectors.public_categories().filter(parent__isnull=True))
    children = {}
    for category in roots:
        children[category.pk] = list(selectors.category_children(category))
    context = {
        **_seo(
            title="Product categories",
            description="All agricultural product categories available on AA Shinaka.",
        ),
        "roots": roots,
        "children": children,
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "Shop", "url": "catalog:shop_index"},
            {"label": "Categories"},
        ],
    }
    return render(request, "catalog/category_list.html", context)


def category_detail(request: HttpRequest, slug: str) -> HttpResponse:
    category = selectors.category_by_slug(slug)
    if category is None:
        return render(request, "catalog/not_found.html", status=404)

    state_slug = request.GET.get("state", "")
    lga_slug = request.GET.get("lga", "")
    listings = selectors.category_listings(
        category,
        state_slug=state_slug,
        lga_slug=lga_slug,
        in_stock_only=request.GET.get("in_stock") == "1",
        price_min=_clean_decimal(request.GET.get("min_price")),
        price_max=_clean_decimal(request.GET.get("max_price")),
    )
    page_obj = _page(request, listings)
    context = {
        **_seo(
            title=category.seo_title or category.name,
            description=category.seo_description or category.description[:200],
            # Canonical is the clean category URL, even when filtered/paginated
            # and even when the legacy ``/shop/<slug>/`` alias served this page.
            canonical=request.build_absolute_uri(
                reverse("catalog:category_detail", kwargs={"slug": category.slug})
            ),
            noindex=_has_filters(request),
        ),
        "category": category,
        "children": selectors.category_children(category),
        "listings": page_obj,
        "page_obj": page_obj,
        "states": selectors.state_list(),
        "lgas": (
            LGA.objects.filter(state__slug=state_slug, is_active=True).order_by("name")
            if state_slug
            else []
        ),
        "selected_state": state_slug,
        "selected_lga": lga_slug,
        "price_bands": selectors.build_price_bands(),
        **_filter_context(request),
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "Shop", "url": "catalog:shop_index"},
            *[
                {"label": ancestor.name, "href": ancestor.get_absolute_url()}
                for ancestor in category.ancestors()
            ],
            {"label": category.name},
        ],
    }
    if request.headers.get("HX-Request"):
        return render(request, "catalog/partials/_listing_results.html", context)
    return render(request, "catalog/category_detail.html", context)


# ---------------------------------------------------------------------------
# Product detail & compare
# ---------------------------------------------------------------------------


def product_detail(request: HttpRequest, slug: str) -> HttpResponse:
    product = selectors.product_by_slug(slug)
    if product is None:
        return render(request, "catalog/not_found.html", status=404)
    listings = selectors.product_listings(product)
    title, description = product.seo()
    context = {
        **_seo(
            title=title,
            description=description,
            canonical=_canonical(request),
            og_type="product",
        ),
        "product": product,
        "listings": listings,
        "images": selectors.product_images(product),
        "related": selectors.related_products(product),
        "market_references": selectors.market_reference_prices(product),
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "Shop", "url": "catalog:shop_index"},
            *[
                {"label": ancestor.name, "href": ancestor.get_absolute_url()}
                for ancestor in product.category.ancestors()
            ],
            {"label": product.category.name, "href": product.category.get_absolute_url()},
            {"label": product.name},
        ],
    }
    return render(request, "catalog/product_detail.html", context)


def compare(request: HttpRequest) -> HttpResponse:
    slugs = [slug for slug in request.GET.get("slugs", "").split(",") if slug][:COMPARE_LIMIT]
    products = selectors.compare_products(slugs)
    context = {
        **_seo(
            title="Compare products",
            description="Compare agricultural products side by side by category, origin and price.",
            noindex=True,
        ),
        "products": products,
        "requested_slugs": ",".join(slugs),
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "Shop", "url": "catalog:shop_index"},
            {"label": "Compare"},
        ],
    }
    return render(request, "catalog/compare.html", context)


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def state_list(request: HttpRequest) -> HttpResponse:
    context = {
        **_seo(
            title="Shop by state",
            description="Browse agricultural products by their Nigerian state of origin.",
            canonical=_canonical(request),
        ),
        "states": selectors.state_list(),
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "Shop", "url": "catalog:shop_index"},
            {"label": "States"},
        ],
    }
    return render(request, "catalog/state_list.html", context)


def state_detail(request: HttpRequest, slug: str) -> HttpResponse:
    state = selectors.state_by_slug(slug)
    if state is None:
        return render(request, "catalog/not_found.html", status=404)
    listings = selectors.state_listings(state, in_stock_only=request.GET.get("in_stock") == "1")
    page_obj = _page(request, listings)
    context = {
        **_seo(
            title=f"Agricultural products from {state.name}",
            description=(
                f"Browse agricultural product listings originating in {state.name}, Nigeria."
            ),
            canonical=_canonical(request),
            noindex=_has_filters(request),
        ),
        "location_state": state,
        "lgas": selectors.lgas_with_listings(state),
        "listings": page_obj,
        "page_obj": page_obj,
        **_filter_context(request),
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "Shop", "url": "catalog:shop_index"},
            {"label": "States", "url": "catalog:state_list"},
            {"label": state.name},
        ],
    }
    return render(request, "catalog/state_detail.html", context)


def lga_detail(request: HttpRequest, state: str, lga: str) -> HttpResponse:
    state_obj = selectors.state_by_slug(state)
    if state_obj is None:
        return render(request, "catalog/not_found.html", status=404)
    lga_obj = selectors.lga_by_slug(state_obj, lga)
    if lga_obj is None:
        return render(request, "catalog/not_found.html", status=404)
    listings = selectors.state_listings(
        state_obj, lga_slug=lga, in_stock_only=request.GET.get("in_stock") == "1"
    )
    page_obj = _page(request, listings)
    context = {
        **_seo(
            title=f"Agricultural products from {lga_obj.name}",
            description=f"Browse product listings originating in {lga_obj.name}, {state_obj.name}.",
            canonical=_canonical(request),
            noindex=_has_filters(request),
        ),
        "location_state": state_obj,
        "location_lga": lga_obj,
        "listings": page_obj,
        "page_obj": page_obj,
        **_filter_context(request),
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "Shop", "url": "catalog:shop_index"},
            {"label": "States", "url": "catalog:state_list"},
            {"label": state_obj.name, "href": state_obj.get_absolute_url()},
            {"label": lga_obj.name},
        ],
    }
    return render(request, "catalog/lga_detail.html", context)


def lga_options(request: HttpRequest) -> HttpResponse:
    """HTMX partial: ``<option>`` list for a state's LGAs (dependent dropdown).

    ``?value=slug`` returns slug option values (public filters); the default
    returns primary keys (staff forms).
    """
    state_value = request.GET.get("state", "")
    use_slug = request.GET.get("value") == "slug"
    lgas: list[LGA] = []
    if state_value:
        lookup = {"state__slug": state_value} if use_slug else {"state_id": state_value}
        lgas = list(LGA.objects.filter(is_active=True, **lookup).order_by("name"))
    return render(
        request,
        "catalog/partials/_lga_options.html",
        {"lgas": lgas, "use_slug": use_slug},
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    state_slug = request.GET.get("state", "")
    lga_slug = request.GET.get("lga", "")
    listings = selectors.search_listings(
        query=query,
        category_slug=request.GET.get("category", ""),
        state_slug=state_slug,
        lga_slug=lga_slug,
        price_min=_clean_decimal(request.GET.get("min_price")),
        price_max=_clean_decimal(request.GET.get("max_price")),
        in_stock_only=request.GET.get("in_stock") == "1",
        sort=request.GET.get("sort", ""),
    )
    page_obj = _page(request, listings)
    context = {
        **_seo(
            title=f"Search: {query}" if query else "Search products",
            description="Search agricultural products by name, category, origin or price.",
            # Noindex, so the canonical should point at the clean search path
            # rather than echoing the visitor's query string.
            canonical=canonical_from_request(request),
            noindex=True,
        ),
        "query": query,
        "listings": page_obj,
        "page_obj": page_obj,
        "categories": selectors.public_categories(),
        "states": selectors.state_list(),
        "lgas": (
            LGA.objects.filter(state__slug=state_slug, is_active=True).order_by("name")
            if state_slug
            else []
        ),
        "selected_category": request.GET.get("category", ""),
        "selected_state": state_slug,
        "selected_lga": lga_slug,
        "selected_sort": request.GET.get("sort", ""),
        **_filter_context(request),
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "Shop", "url": "catalog:shop_index"},
            {"label": "Search"},
        ],
    }
    if request.headers.get("HX-Request"):
        return render(request, "catalog/partials/_listing_results.html", context)
    return render(request, "catalog/search.html", context)

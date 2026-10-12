"""Read-only queries for the public website and the CMS dashboard.

Public selectors always use ``.published()`` so drafts and archives never leak.
Catalogue lookups are written defensively: the catalogue app ships in a later
phase, so these helpers return an empty result instead of raising when its
models do not exist yet (see ``featured_products`` / ``shop_by_state``).
"""

from __future__ import annotations

from django.db.models import QuerySet

from .models import (
    FAQ,
    BlogCategory,
    BlogPost,
    BusinessDivision,
    ContactEnquiry,
    HeroBanner,
    MediaAsset,
    NavigationItem,
    Page,
    Placement,
    PublishStatus,
    ServicePage,
    SiteSetting,
    TeamMember,
    Testimonial,
)

# ---------------------------------------------------------------------------
# Site chrome
# ---------------------------------------------------------------------------


def site_settings() -> SiteSetting:
    return SiteSetting.load()


def navigation_items(*, placement: str = Placement.HEADER) -> QuerySet[NavigationItem]:
    return (
        NavigationItem.objects.filter(is_active=True, placement=placement, parent__isnull=True)
        .select_related("page")
        .prefetch_related("children__page")
        .order_by("sort_order", "id")
    )


def header_navigation() -> QuerySet[NavigationItem]:
    return navigation_items(placement=Placement.HEADER)


def footer_navigation() -> QuerySet[NavigationItem]:
    return navigation_items(placement=Placement.FOOTER)


# ---------------------------------------------------------------------------
# Homepage
# ---------------------------------------------------------------------------


def hero_banners() -> QuerySet[HeroBanner]:
    return HeroBanner.objects.published().select_related("image")[:5]


def business_divisions() -> QuerySet[BusinessDivision]:
    return BusinessDivision.objects.published().select_related("image")


def featured_testimonials(*, limit: int = 6) -> QuerySet[Testimonial]:
    return (
        Testimonial.objects.filter(is_approved=True)
        .select_related("image")
        .order_by("-is_featured", "sort_order", "-created_at")[:limit]
    )


def latest_blog_posts(*, limit: int = 3) -> QuerySet[BlogPost]:
    return BlogPost.objects.published().select_related("category", "featured_image")[:limit]


def team_members() -> QuerySet[TeamMember]:
    return TeamMember.objects.filter(is_active=True).select_related("photo")


# ---------------------------------------------------------------------------
# Catalogue previews (defensive — catalogue ships later)
# ---------------------------------------------------------------------------


def catalog_is_available() -> bool:
    """Whether the catalogue app has concrete product models yet."""
    try:
        from apps.catalog.models import ProductListing  # noqa: F401
    except (ImportError, AttributeError):
        return False
    return True


def featured_products(*, limit: int = 8) -> list:
    """Published product listings for the homepage, or ``[]`` if none yet."""
    if not catalog_is_available():
        return []
    from apps.catalog import selectors as catalog_selectors  # noqa: PLC0415

    return list(catalog_selectors.featured_listings(limit=limit))


def shop_by_state(*, limit: int = 8) -> list:
    """States that currently have published listings, or ``[]`` if none yet."""
    if not catalog_is_available():
        return []
    from apps.catalog import selectors as catalog_selectors  # noqa: PLC0415

    return list(catalog_selectors.states_with_listings(limit=limit))


def product_categories(*, limit: int = 8) -> list:
    """Active top-level product categories for the homepage, or ``[]``."""
    if not catalog_is_available():
        return []
    from apps.catalog import selectors as catalog_selectors  # noqa: PLC0415

    return list(catalog_selectors.top_level_categories(limit=limit))


# ---------------------------------------------------------------------------
# Service pages & pages
# ---------------------------------------------------------------------------


def service_pages() -> QuerySet[ServicePage]:
    return ServicePage.objects.published().select_related("division", "hero_image")


def service_page(slug: str) -> ServicePage | None:
    return (
        ServicePage.objects.published()
        .select_related("division", "hero_image")
        .prefetch_related("categories", "faqs")
        .filter(slug=slug)
        .first()
    )


def published_pages() -> QuerySet[Page]:
    return Page.objects.published()


def page(slug: str) -> Page | None:
    return Page.objects.published().filter(slug=slug).first()


def page_of_type(page_type: str) -> Page | None:
    return Page.objects.published().filter(page_type=page_type).first()


# ---------------------------------------------------------------------------
# FAQs, blog
# ---------------------------------------------------------------------------


def general_faqs() -> QuerySet[FAQ]:
    return FAQ.objects.filter(is_published=True, service_page__isnull=True)


def faqs_for(service_page_obj: ServicePage) -> QuerySet[FAQ]:
    return FAQ.objects.filter(is_published=True, service_page=service_page_obj)


def blog_categories() -> QuerySet[BlogCategory]:
    return BlogCategory.objects.all()


def published_blog_posts(*, category: str = "") -> QuerySet[BlogPost]:
    queryset = BlogPost.objects.published().select_related("category", "author", "featured_image")
    if category:
        queryset = queryset.filter(category__slug=category)
    return queryset


def blog_post(slug: str) -> BlogPost | None:
    return (
        BlogPost.objects.published()
        .select_related("category", "author", "featured_image")
        .filter(slug=slug)
        .first()
    )


# ---------------------------------------------------------------------------
# CMS dashboard (all rows, including drafts)
# ---------------------------------------------------------------------------


def media_assets() -> QuerySet[MediaAsset]:
    return MediaAsset.objects.select_related("uploaded_by")


def all_blog_posts() -> QuerySet[BlogPost]:
    return BlogPost.objects.select_related("category", "author").order_by("-created_at")


def all_pages() -> QuerySet[Page]:
    return Page.objects.order_by("-updated_at")


def all_hero_banners() -> QuerySet[HeroBanner]:
    return HeroBanner.objects.order_by("sort_order", "-created_at")


def all_divisions() -> QuerySet[BusinessDivision]:
    return BusinessDivision.objects.order_by("sort_order", "name")


def all_service_pages() -> QuerySet[ServicePage]:
    return ServicePage.objects.select_related("division").order_by("sort_order", "title")


def all_testimonials() -> QuerySet[Testimonial]:
    return Testimonial.objects.select_related("approved_by").order_by(
        "-is_featured", "sort_order", "-created_at"
    )


def all_faqs() -> QuerySet[FAQ]:
    return FAQ.objects.select_related("service_page").order_by("sort_order", "id")


def all_navigation_items() -> QuerySet[NavigationItem]:
    return NavigationItem.objects.select_related("page", "parent").order_by(
        "placement", "sort_order", "id"
    )


def all_team_members() -> QuerySet[TeamMember]:
    return TeamMember.objects.order_by("sort_order", "name")


def open_enquiries() -> QuerySet[ContactEnquiry]:
    return ContactEnquiry.objects.filter(is_handled=False)


def all_enquiries() -> QuerySet[ContactEnquiry]:
    return ContactEnquiry.objects.select_related("handled_by")


def cms_counts() -> dict[str, int]:
    """Real, non-fabricated counts for the CMS dashboard overview."""
    return {
        "banners_published": HeroBanner.objects.published().count(),
        "banners_draft": HeroBanner.objects.filter(status=PublishStatus.DRAFT).count(),
        "services_published": ServicePage.objects.published().count(),
        "services_draft": ServicePage.objects.filter(status=PublishStatus.DRAFT).count(),
        "posts_published": BlogPost.objects.published().count(),
        "posts_draft": BlogPost.objects.filter(status=PublishStatus.DRAFT).count(),
        "pages_published": Page.objects.published().count(),
        "pages_draft": Page.objects.filter(status=PublishStatus.DRAFT).count(),
        "testimonials_pending": Testimonial.objects.filter(is_approved=False).count(),
        "enquiries_open": ContactEnquiry.objects.filter(is_handled=False).count(),
        "media_total": MediaAsset.objects.count(),
        "faqs_total": FAQ.objects.count(),
    }

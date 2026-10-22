"""XML sitemap definitions for the public site.

The catalogue and training sections were previously absent entirely, so the two
largest public content areas could not be discovered through the sitemap. They
are added here. State pages are included only when they actually carry
listings, so an empty state page does not become a thin-content entry.
"""

from __future__ import annotations

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from . import selectors


class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = "weekly"

    def items(self):
        return [
            "core:home",
            "cms:service_list",
            "cms:about",
            "cms:contact",
            "cms:blog_list",
            "cms:faq_list",
        ]

    def location(self, item):
        return reverse(item)


class ServiceSitemap(Sitemap):
    priority = 0.7
    changefreq = "monthly"

    def items(self):
        return selectors.service_pages()

    def lastmod(self, obj):
        return obj.updated_at


class PageSitemap(Sitemap):
    priority = 0.6
    changefreq = "monthly"

    def items(self):
        return selectors.published_pages()

    def lastmod(self, obj):
        return obj.updated_at


class BlogSitemap(Sitemap):
    priority = 0.6
    changefreq = "weekly"

    def items(self):
        return selectors.published_blog_posts()

    def lastmod(self, obj):
        return obj.updated_at


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
# Imported lazily inside ``items()`` so the CMS app never hard-depends on the
# catalogue at import time (the catalogue shipped in a later phase and the
# selectors are written defensively for the same reason).


class CategorySitemap(Sitemap):
    priority = 0.7
    changefreq = "weekly"

    def items(self):
        from apps.catalog import selectors as catalog_selectors

        return catalog_selectors.public_categories()

    def location(self, obj):
        return obj.get_absolute_url()

    def lastmod(self, obj):
        return obj.updated_at


class ProductSitemap(Sitemap):
    priority = 0.6
    changefreq = "weekly"

    def items(self):
        from apps.catalog import selectors as catalog_selectors

        # Only published products that actually have a sellable listing, so a
        # product with no stock never advertises itself as available.
        return catalog_selectors.all_products().filter(
            status="published", listings__status="active"
        ).distinct()

    def location(self, obj):
        return obj.get_absolute_url()

    def lastmod(self, obj):
        return obj.updated_at


class StateSitemap(Sitemap):
    priority = 0.5
    changefreq = "weekly"

    def items(self):
        from apps.catalog import selectors as catalog_selectors

        # States that currently have published listings only. ``limit=None``
        # relies on ``[:None]`` being an open-ended slice in the selector, i.e.
        # "no limit" — spelled out here because it looks like a bug.
        return catalog_selectors.states_with_listings(limit=None)

    def location(self, obj):
        return reverse("catalog:state_detail", kwargs={"slug": obj.slug})


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


class TrainingCourseSitemap(Sitemap):
    priority = 0.6
    changefreq = "weekly"

    def items(self):
        from apps.training import selectors as training_selectors

        return training_selectors.published_courses()

    def location(self, obj):
        return reverse("training:course_detail", kwargs={"slug": obj.slug})


class TrainingCategorySitemap(Sitemap):
    priority = 0.5
    changefreq = "weekly"

    def items(self):
        from apps.training import selectors as training_selectors

        return training_selectors.active_categories()

    def location(self, obj):
        return reverse("training:category_detail", kwargs={"slug": obj.slug})


#: Every sitemap section, keyed by the ``<sitemapindex>`` child name.
SITEMAPS = {
    "static": StaticViewSitemap,
    "services": ServiceSitemap,
    "pages": PageSitemap,
    "blog": BlogSitemap,
    "categories": CategorySitemap,
    "products": ProductSitemap,
    "states": StateSitemap,
    "training-courses": TrainingCourseSitemap,
    "training-categories": TrainingCategorySitemap,
}

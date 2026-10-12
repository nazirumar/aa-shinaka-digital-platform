"""XML sitemap definitions for the public site."""

from __future__ import annotations

from django.contrib.sitemaps import Sitemap

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
        from django.urls import reverse

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


SITEMAPS = {
    "static": StaticViewSitemap,
    "services": ServiceSitemap,
    "pages": PageSitemap,
    "blog": BlogSitemap,
}

"""Template helpers for website content.

These tags let the homepage pull CMS data without the ``core`` app having to
import the ``cms`` app. The site configuration and navigation are already
provided globally by ``apps.cms.context_processors.site_context``.
"""

from __future__ import annotations

from django import template

from apps.core.constants import BusinessDivision as BusinessDivisionChoice

from .. import selectors

register = template.Library()


@register.simple_tag
def hero_banners():
    return selectors.hero_banners()


@register.simple_tag
def business_divisions():
    return selectors.business_divisions()


@register.simple_tag
def canonical_divisions():
    """The fixed company divisions, used as a fallback when CMS rows are absent."""
    return [
        {"value": value, "label": label, "name": label}
        for value, label in BusinessDivisionChoice.choices
    ]


@register.simple_tag
def product_categories(limit=8):
    """Product categories from the catalogue, or ``[]`` before it ships."""
    return selectors.product_categories(limit=limit)


@register.simple_tag
def featured_products(limit=8):
    return selectors.featured_products(limit=limit)


@register.simple_tag
def shop_by_state(limit=8):
    return selectors.shop_by_state(limit=limit)


@register.simple_tag
def featured_testimonials(limit=6):
    return selectors.featured_testimonials(limit=limit)


@register.simple_tag
def latest_posts(limit=3):
    return selectors.latest_blog_posts(limit=limit)


@register.simple_tag
def general_faqs():
    return selectors.general_faqs()


@register.filter
def attr(obj, name):
    """Return ``getattr(obj, name)`` for building generic CMS tables."""
    value = getattr(obj, name, "")
    if callable(value):
        try:
            return value()
        except TypeError:
            return value
    return value

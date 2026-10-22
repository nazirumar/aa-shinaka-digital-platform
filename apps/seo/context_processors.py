"""SEO defaults for templates rendered through ``base.html``.

Pages in the private areas (customer portal, cart, authentication, staff
dashboard) historically rendered with no robots directive at all, so they
inherited the public homepage's indexable default. This processor closes that
gap without touching each view.

Ordering matters and is easy to get wrong: Django applies context processors
*after* the view's own context, so a processor that unconditionally returns a
key would clobber whatever the view decided. The processor therefore only
*adds* the flag when it is genuinely absent, using a request attribute as the
communication channel rather than the template context.
"""

from __future__ import annotations

#: URL prefixes that must never appear in a search index. Matched against the
#: resolved request path, so a private area added later under one of these
#: prefixes is covered automatically.
PRIVATE_PREFIXES = (
    "/dashboard/",
    "/account/",
    "/accounts/",
    "/admin/",
    "/internal/",
    "/healthz/",
    "/cart/",
    "/checkout/",
    "/orders/",
    "/payments/",
    "/invoices/",
    "/receipts/",
    "/quotations/",
    "/i18n/",
)


def is_private_path(path: str) -> bool:
    """Whether ``path`` belongs to a non-indexable area of the site."""
    return bool(path) and path.startswith(PRIVATE_PREFIXES)


def seo_defaults(request) -> dict:
    """Return ``{"seo_noindex": True}`` only for private, undeclared pages.

    ``request._seo_noindex_declared`` is set by
    :func:`apps.seo.templatetags.seo_tags` consumers — in practice the marker is
    set by the view layer through :func:`mark_declared`. When nothing declared a
    value, private paths default to noindex; public paths are left alone so the
    template's indexable default applies.
    """
    if getattr(request, "_seo_noindex_declared", False):
        return {}
    path = getattr(request, "path", "") or ""
    if is_private_path(path):
        return {"seo_noindex": True}
    return {}


def mark_declared(request) -> None:
    """Record that the view supplied its own indexing decision."""
    request._seo_noindex_declared = True

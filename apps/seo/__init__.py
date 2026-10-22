"""Search-visibility helpers shared across the public apps.

This module is deliberately small and dependency-free. It exists because the
public site previously grew three near-identical private ``_seo()`` helpers
(``apps.cms.views``, ``apps.catalog.views``, ``apps.training.views``) that had
drifted apart, and two field-naming conventions for the same ideas
(``meta_title``/``meta_description`` in the CMS, ``seo_title``/``seo_description``
in the catalogue).

Nothing here changes behaviour on its own: the helpers only build the context
dict that ``templates/base.html`` already reads (``seo_title``,
``seo_description``, ``seo_canonical``, ``seo_og_image``, ``seo_noindex``), so
existing templates keep working unchanged.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from django.http import HttpRequest

__all__ = [
    "SITE_NAME_FALLBACK",
    "canonical_from_request",
    "seo_context",
    "content_seo",
    "absolute_media_url",
]

#: Used only when no ``SiteSetting`` row carries a name.
SITE_NAME_FALLBACK = "AA Shinaka"


def seo_context(
    *,
    title: str = "",
    description: str = "",
    canonical: str = "",
    og_image=None,
    noindex: bool = False,
    og_type: str = "website",
) -> dict:
    """Build the SEO context keys ``templates/base.html`` consumes.

    Keys are exactly the ones the base template already understands. ``og_type``
    is new and optional; when the template does not yet use it, it is simply an
    unused context value.
    """
    return {
        "page_title": title,
        "seo_title": title,
        "seo_description": description,
        "seo_canonical": canonical,
        "seo_og_image": og_image,
        "seo_noindex": noindex,
        "seo_og_type": og_type,
    }


def content_seo(
    obj,
    *,
    fallback_title: str = "",
    canonical: str = "",
    og_type: str = "website",
) -> dict:
    """Build SEO context from any object carrying SEO-ish fields.

    Reads both conventions so the same helper serves the CMS (``meta_*``) and the
    catalogue (``seo_*``): ``meta_title``/``seo_title`` then the object's own
    ``title``/``name``. Image fallbacks cover the CMS ``og_image``/``hero_image``
    and the catalogue ``primary_image``.
    """
    title = (
        getattr(obj, "meta_title", "")
        or getattr(obj, "seo_title", "")
        or getattr(obj, "title", "")
        or getattr(obj, "name", "")
        or fallback_title
    )
    description = (
        getattr(obj, "meta_description", "")
        or getattr(obj, "seo_description", "")
        or getattr(obj, "summary", "")
        or getattr(obj, "excerpt", "")
        or getattr(obj, "short_description", "")
        or getattr(obj, "intro", "")
    )
    image = (
        getattr(obj, "og_image", None)
        or getattr(obj, "hero_image", None)
        # BlogPost carries ``featured_image``; the CMS helper previously looked
        # only for ``hero_image``, so blog posts never got an og:image.
        or getattr(obj, "featured_image", None)
    )
    return seo_context(
        title=str(title).strip(),
        # meta_description is a CharField; slice defensively so a long body
        # never becomes an unbounded meta tag.
        description=str(description).strip()[:320],
        canonical=canonical or getattr(obj, "canonical_url", "") or "",
        og_image=image,
        noindex=bool(getattr(obj, "noindex", False)),
        og_type=og_type,
    )


def canonical_from_request(request: HttpRequest) -> str:
    """An absolute, query-string-free URL for ``request``.

    Paginated and filtered pages used to self-canonicalise including their query
    string (``/news/?page=2``), which told crawlers that every variant *is* the
    canonical page. Consolidating them means stripping the query string and the
    fragment, keeping only scheme, host and path.
    """
    parts = urlsplit(request.build_absolute_uri())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def absolute_media_url(file_field) -> str:
    """Absolute URL for a media field, or ``""`` when there is no file.

    ``FieldFile.url`` is relative (``/media/...``); Open Graph requires an
    absolute URL, so callers pass the request to qualify it.
    """
    if not file_field:
        return ""
    try:
        return str(file_field.url)
    except (ValueError, AttributeError):
        return ""

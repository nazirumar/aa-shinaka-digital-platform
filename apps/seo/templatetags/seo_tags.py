"""Template tags that emit JSON-LD structured data.

Structured data is what answer engines (and rich results) read to understand
*what* a page is about. Three graphs are emitted from data already present in
the template context — nothing is invented:

* ``Organization`` — once per page, from the CMS ``SiteSetting``.
* ``WebSite`` with a ``SearchAction`` — once per page, pointing at the real
  catalogue search endpoint.
* ``BreadcrumbList`` — on pages that supplied ``breadcrumbs``, matching exactly
  the visible breadcrumb trail.

If a value is missing the corresponding field is simply omitted; the tag never
fabricates names, prices, ratings or achievements, and never crashes rendering.
"""

from __future__ import annotations

import json

from django import template
from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe

register = template.Library()


def _absolute(request, url: str) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return request.build_absolute_uri(url)


def _resolve(request, url) -> str:
    """Turn a breadcrumb value that may be a URL name into an absolute URL."""
    if not url:
        return ""
    if isinstance(url, str) and ":" in url and not url.startswith(("http", "/")):
        try:
            url = reverse(url)
        except NoReverseMatch:
            # Some breadcrumbs pass a raw label as ``url`` — treat as no link.
            return ""
    return _absolute(request, str(url))


def _organisation(request, site) -> dict:
    data = {
        "@type": "Organization",
        "@id": _absolute(request, "/") + "#organization",
        "name": (getattr(site, "site_name", "") or "AA Shinaka"),
        "url": _absolute(request, "/"),
    }
    description = (
        getattr(site, "description", "") or getattr(site, "default_meta_description", "") or ""
    )
    if description:
        data["description"] = description
    logo = getattr(site, "logo", None)
    if logo:
        try:
            data["logo"] = _absolute(request, logo.file.url)
        except (ValueError, AttributeError):
            pass

    # Only emit contact details that staff have actually filled in.
    email = getattr(site, "email", "") or ""
    phone = getattr(site, "phone", "") or ""
    if email or phone:
        contact = {"@type": "ContactPoint", "contactType": "customer service"}
        if email:
            contact["email"] = email
        if phone:
            contact["telephone"] = phone
        contact["areaServed"] = getattr(site, "country", "") or "NG"
        data["contactPoint"] = contact

    locality = getattr(site, "city", "") or ""
    region = getattr(getattr(site, "state", None), "name", "") or ""
    country = getattr(site, "country", "") or ""
    street = getattr(site, "address_line", "") or ""
    if any((street, locality, region, country)):
        address = {"@type": "PostalAddress"}
        if street:
            address["streetAddress"] = street
        if locality:
            address["addressLocality"] = locality
        if region:
            address["addressRegion"] = region
        if country:
            address["addressCountry"] = country
        data["address"] = address

    # Social profiles become ``sameAs``, the signal search engines use to
    # disambiguate the entity. Blank fields are skipped, never guessed.
    same_as = [
        url
        for url in (
            getattr(site, "facebook_url", ""),
            getattr(site, "instagram_url", ""),
            getattr(site, "twitter_url", ""),
            getattr(site, "linkedin_url", ""),
            getattr(site, "youtube_url", ""),
        )
        if url
    ]
    if same_as:
        data["sameAs"] = same_as
    return data


def _website(request, site) -> dict:
    data = {
        "@type": "WebSite",
        "@id": _absolute(request, "/") + "#website",
        "name": (getattr(site, "site_name", "") or "AA Shinaka"),
        "url": _absolute(request, "/"),
    }
    # The search box target must be a real route; if it moves, drop the action
    # rather than emit a broken SearchAction.
    try:
        search_url = reverse("catalog:search")
    except NoReverseMatch:
        return data
    data["potentialAction"] = {
        "@type": "SearchAction",
        "target": {
            "@type": "EntryPoint",
            "urlTemplate": _absolute(request, search_url) + "?q={search_term_string}",
        },
        "query-input": "required name=search_term_string",
    }
    return data


def _breadcrumbs(request, crumbs) -> dict | None:
    items = []
    for position, crumb in enumerate(crumbs, start=1):
        if not isinstance(crumb, dict):
            continue
        label = crumb.get("label") or crumb.get("name") or ""
        if not label:
            continue
        entry = {"@type": "ListItem", "position": position, "name": str(label)}
        url = _resolve(request, crumb.get("href") or crumb.get("url"))
        if url:
            entry["item"] = url
        items.append(entry)
    if not items:
        return None
    return {"@type": "BreadcrumbList", "itemListElement": items}


@register.simple_tag(takes_context=True)
def json_ld(context) -> str:
    """Emit one ``<script type="application/ld+json">`` for the page.

    Returns an empty string rather than raising: structured data must never be
    the reason a page fails to render.
    """
    try:
        request = context.get("request")
        if request is None:
            return ""
        site = context.get("site")
        graph = [_organisation(request, site), _website(request, site)]
        crumbs = context.get("breadcrumbs")
        if crumbs:
            crumb_graph = _breadcrumbs(request, crumbs)
            if crumb_graph:
                graph.append(crumb_graph)
        payload = {"@context": "https://schema.org", "@graph": graph}
        # ``</script>`` inside a JSON string would close the tag early; the
        # standard guard is to escape the forward slash.
        rendered = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        return mark_safe('<script type="application/ld+json">' + rendered + "</script>")
    except Exception:  # noqa: BLE001 - never break rendering for structured data
        return ""

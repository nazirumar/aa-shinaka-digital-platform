"""Template context processors for the public site.

Exposes the site configuration and navigation to every template so the header,
footer, announcement bar and SEO tags can render without each view passing
them. Queries are defensive: if the CMS tables are unavailable, the variables
fall back to empty values rather than breaking rendering.
"""

from __future__ import annotations


def site_context(request) -> dict:
    try:
        from .selectors import footer_navigation, header_navigation, site_settings

        return {
            "site": site_settings(),
            "header_nav": header_navigation(),
            "footer_nav": footer_navigation(),
        }
    except Exception:  # noqa: BLE001 - never break page rendering
        return {}

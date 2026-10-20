"""Dashboard sidebar: collapsible category groups and active-page handling."""

from pathlib import Path

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

GROUPS = (
    "overview",
    "website",
    "catalogue",
    "orders",
    "finance",
    "services",
    "export",
    "training",
    "support",
    "customers",
    "analytics",
)


def test_sidebar_renders_collapsible_category_groups(client, owner):
    client.force_login(owner)

    response = client.get(reverse("dashboard:home"))

    assert response.status_code == 200
    content = response.content
    # An Alpine component owns the open/closed state and remembers it across
    # page loads so a collapsed category stays collapsed while navigating.
    assert b'x-data="sidebarNav"' in content
    assert b"Alpine.data('sidebarNav'" in content
    assert b"activeGroup" in content
    assert b"sidebar.groups" in content  # localStorage key
    # Every section is rendered as a labelled, collapsible category.
    for group in GROUPS:
        assert f'data-nav-group="{group}"'.encode() in content
        assert f'id="nav-group-{group}"'.encode() in content
    assert content.count(b'class="sidebar-group-header"') == len(GROUPS)


def test_sidebar_active_link_is_marked_and_scrolled_to(client, owner):
    client.force_login(owner)

    response = client.get(reverse("dashboard:home"))

    content = response.content
    # The current page is flagged active server-side; the component opens its
    # category, marks aria-current and scrolls the link into view.
    assert b"is-active" in content
    assert b"aria-current" in content
    assert b"scrollIntoView" in content


def test_sidebar_group_css_is_always_emitted():
    css = Path("assets/css/app.css").read_text(encoding="utf-8")

    assert ".sidebar-group-header" in css
    assert ".sidebar-group-body" in css

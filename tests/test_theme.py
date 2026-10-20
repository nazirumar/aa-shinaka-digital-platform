"""Light/dark theme system: shared bootstrap, switcher and dark utilities."""

from pathlib import Path

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

THEME_INIT_MARKER = b"localStorage.getItem('theme')"
THEME_STORE_MARKER = b"Alpine.store('theme'"


def test_public_page_bootstraps_theme_before_paint(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    content = response.content
    # No-flash bootstrap + Alpine store, both present in <head>.
    assert THEME_INIT_MARKER in content
    assert THEME_STORE_MARKER in content
    # The switcher offers all three preferences.
    assert b"menuitemradio" in content
    for label in (b"Light", b"Dark", b"System"):
        assert label in content
    # Dark styling hooks are emitted so the dark utilities are generated.
    assert b"dark:bg-stone-950" in content


def test_dashboard_includes_theme_switcher(client, owner):
    client.force_login(owner)

    response = client.get(reverse("dashboard:home"))

    assert response.status_code == 200
    content = response.content
    assert THEME_INIT_MARKER in content
    assert THEME_STORE_MARKER in content
    assert b"menuitemradio" in content
    assert b"dark:bg-stone-900/95" in content


def test_theme_css_defines_class_based_dark_variant():
    css = Path("assets/css/app.css").read_text(encoding="utf-8")

    assert "@custom-variant dark (&:where(.dark, .dark *))" in css
    assert "color-scheme: dark" in css
    # Form controls and CMS rich text adapt in dark mode.
    assert ".dark input" in css
    assert ".dark .rich-text" in css

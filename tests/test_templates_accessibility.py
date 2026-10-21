"""Template rendering and accessibility basics (checklist item 20)."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PUBLIC_URLS = [
    "accounts:register",
    "accounts:login",
    "accounts:password_reset",
    "accounts:password_reset_done",
    "accounts:password_reset_complete",
]


@pytest.mark.parametrize("url_name", PUBLIC_URLS)
def test_public_pages_render_with_basics(client, url_name):
    response = client.get(reverse(url_name))

    assert response.status_code == 200
    content = response.content
    assert b'lang="en"' in content
    assert b'<meta name="viewport"' in content
    assert b"Skip to content" in content


def test_register_form_has_labels_and_csrf(client):
    response = client.get(reverse("accounts:register"))
    content = response.content

    assert b'for="id_email"' in content
    assert b'for="id_password1"' in content
    assert b"csrfmiddlewaretoken" in content


def test_login_form_has_labels(client):
    response = client.get(reverse("accounts:login"))
    content = response.content

    assert b'for="id_username"' in content
    assert b'for="id_password"' in content


def test_login_form_shows_generic_error(client, customer):
    response = client.post(
        reverse("accounts:login"),
        {"username": "customer@example.com", "password": "nope"},
    )

    assert b'role="alert"' in response.content


def test_admin_dashboard_renders_for_owner_with_navigation(client, owner):
    client.force_login(owner)

    response = client.get(reverse("dashboard:home"))

    assert response.status_code == 200
    content = response.content
    assert b"Skip to content" in content
    assert b'aria-label="Admin navigation"' in content
    assert b"Staff" in content


def test_admin_dashboard_hides_staff_link_for_finance_officer(client, state):
    from django.contrib.auth import get_user_model

    from apps.accounts.models import UserRole
    from apps.accounts.roles import sync_user_groups

    User = get_user_model()
    finance = User.objects.create_user(
        email="finance@example.com",
        password="test-pass-12345",
        role=UserRole.FINANCE_OFFICER,
        is_staff=True,
    )
    sync_user_groups(finance)
    client.force_login(finance)

    # Finance officers can see the audit log (capability) but not staff management.
    response = client.get(reverse("dashboard:audit_log"))
    assert response.status_code == 200
    assert client.get(reverse("dashboard:staff_list")).status_code == 403


def test_customer_account_base_renders_nav(client, customer):
    client.force_login(customer)

    response = client.get(reverse("account:dashboard"))

    assert response.status_code == 200
    assert b'aria-label="Account sections"' in response.content


# ---------------------------------------------------------------------------
# Site header (navbar) — responsive + no-JS mobile menu
# ---------------------------------------------------------------------------


def test_navbar_mobile_toggle_works_without_javascript(client):
    """The hamburger must be a plain checkbox/label pair so it opens even when
    the Alpine CDN is unreachable — and the CSS rule must be able to reach the
    panel, which requires the checkbox and the panel to share a parent."""
    content = client.get(reverse("core:home")).content.decode()

    checkbox = content.index('id="nav-toggle"')
    label = content.index('for="nav-toggle"')
    panel = content.index('id="mobile-nav"')

    # The checkbox must precede both its label and the panel, so the general
    # sibling selector `#nav-toggle:checked ~ #mobile-nav` can match.
    assert checkbox < label < panel
    assert 'type="checkbox"' in content[checkbox - 60 : checkbox + 40]
    assert "#nav-toggle:checked ~ #mobile-nav" in content


def test_navbar_mobile_panel_is_hidden_by_default(client):
    """The panel starts hidden and is never shown on desktop."""
    content = client.get(reverse("core:home")).content.decode()

    panel_tag = content[content.index('<nav id="mobile-nav"') :][:400]

    assert "hidden" in panel_tag
    assert "lg:hidden" in panel_tag


def test_navbar_avoids_ios_breaking_sticky_blur(client):
    """`backdrop-blur` on the sticky header breaks tap hit-testing in iOS Safari."""
    content = client.get(reverse("core:home")).content.decode()
    header_tag = content[content.index("<header") : content.index(">", content.index("<header"))]

    assert "backdrop-blur" not in header_tag


def test_navbar_brand_text_is_bounded(client):
    """A long CMS site name/tagline must not be able to break the header layout."""
    content = client.get(reverse("core:home")).content.decode()

    assert "truncate" in content
    assert "min-w-0" in content


def test_navbar_leaves_no_template_comment_in_output(client):
    """Django's `{# ... #}` is single-line only; a multi-line one renders as
    literal text. Guard against that regressing."""
    content = client.get(reverse("core:home")).content.decode()

    assert "{#" not in content

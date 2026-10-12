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

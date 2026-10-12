"""Smoke tests for public routing and the health probe."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_home_page_renders(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    assert b"AA Shinaka" in response.content
    assert b"Agricultural Consultancy" in response.content
    # Oil and gas must never appear in platform scope.
    assert b"Oil and Gas" not in response.content


def test_healthcheck_reports_database_ok(client):
    response = client.get(reverse("core:healthcheck"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] is True


def test_register_page_renders(client):
    response = client.get(reverse("accounts:register"))

    assert response.status_code == 200
    assert b"Create your account" in response.content


def test_signup_alias_redirects_to_register(client):
    response = client.get(reverse("accounts:signup"))

    assert response.status_code == 301
    assert response.url == reverse("accounts:register")


def test_login_page_renders(client):
    response = client.get(reverse("accounts:login"))

    assert response.status_code == 200


def test_public_registration_never_grants_staff_role(client):
    response = client.post(
        reverse("accounts:register"),
        {
            "email": "new@example.com",
            "first_name": "New",
            "last_name": "User",
            "phone": "08000000000",
            "password1": "very-secret-pass-42",
            "password2": "very-secret-pass-42",
            "accept_terms": "on",
            "role": "admin",  # ignored: not a form field
        },
    )

    assert response.status_code == 302
    from apps.accounts.models import User, UserRole

    user = User.objects.get(email="new@example.com")
    assert user.role == UserRole.CUSTOMER
    assert user.is_staff is False
    assert user.is_superuser is False

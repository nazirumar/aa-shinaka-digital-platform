"""Security tests: CSRF, cookies/headers and rate limiting (checklist item 17)."""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_csrf_protection_on_login():
    csrf_client = Client(enforce_csrf_checks=True)

    response = csrf_client.post(
        reverse("accounts:login"),
        {"username": "a@example.com", "password": "x"},
    )

    assert response.status_code == 403


def test_csrf_protection_on_registration():
    csrf_client = Client(enforce_csrf_checks=True)

    response = csrf_client.post(
        reverse("accounts:register"),
        {
            "first_name": "A",
            "last_name": "B",
            "email": "c@example.com",
            "phone": "08000000000",
            "password1": "RockSolidPass!2026",
            "password2": "RockSolidPass!2026",
            "accept_terms": "on",
        },
    )

    assert response.status_code == 403


def test_security_settings_are_sane():
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"
    assert settings.X_FRAME_OPTIONS == "DENY"
    assert settings.SECURE_REFERRER_POLICY == "same-origin"


def test_login_is_rate_limited(client, customer):
    limit = settings.LOGIN_RATE_LIMIT_ATTEMPTS
    url = reverse("accounts:login")
    payload = {"username": "customer@example.com", "password": "wrong-password"}

    statuses = [client.post(url, payload).status_code for _ in range(limit + 1)]

    assert statuses[-1] == 429


def test_password_reset_is_rate_limited(client):
    limit = settings.FORM_RATE_LIMIT_ATTEMPTS
    url = reverse("accounts:password_reset")

    statuses = [
        client.post(url, {"email": "customer@example.com"}).status_code for _ in range(limit + 1)
    ]

    assert statuses[-1] == 429

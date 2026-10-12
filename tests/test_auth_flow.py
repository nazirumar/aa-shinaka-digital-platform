"""Login/logout tests (checklist items 5-7)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()
pytestmark = pytest.mark.django_db

LOGIN_URL = reverse("accounts:login")
LOGOUT_URL = reverse("accounts:logout")


def test_login_success(client, customer):
    response = client.post(
        LOGIN_URL, {"username": "customer@example.com", "password": "test-pass-12345"}
    )

    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(customer.pk)


def test_login_is_case_insensitive_on_email(client, customer):
    response = client.post(
        LOGIN_URL, {"username": "CUSTOMER@example.com", "password": "test-pass-12345"}
    )

    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(customer.pk)


def test_login_with_wrong_password_fails_generically(client, customer):
    response = client.post(
        LOGIN_URL, {"username": "customer@example.com", "password": "wrong-pass"}
    )

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    content = response.content.lower()
    assert b"correct email and password" in content
    # Must not reveal whether the account exists.
    assert b"no account" not in content
    assert b"not found" not in content


def test_login_with_unknown_email_fails_generically(client):
    response = client.post(LOGIN_URL, {"username": "nobody@example.com", "password": "wrong-pass"})

    assert response.status_code == 200
    assert b"correct email and password" in response.content.lower()


def test_logout_requires_post(client, customer):
    client.force_login(customer)

    assert client.get(LOGOUT_URL).status_code == 405


def test_logout_clears_session(client, customer):
    client.force_login(customer)

    response = client.post(LOGOUT_URL)

    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


def test_session_key_rotates_on_login(client, customer):
    client.get(LOGIN_URL)
    before = client.session.session_key

    client.post(LOGIN_URL, {"username": "customer@example.com", "password": "test-pass-12345"})
    after = client.session.session_key

    assert before is not None and after is not None
    assert before != after


def test_safe_redirect_is_honoured(client, customer):
    target = reverse("account:profile")

    response = client.post(
        LOGIN_URL,
        {"username": "customer@example.com", "password": "test-pass-12345", "next": target},
    )

    assert response.status_code == 302
    assert response.url == target


def test_external_redirect_is_rejected(client, customer):
    response = client.post(
        LOGIN_URL,
        {
            "username": "customer@example.com",
            "password": "test-pass-12345",
            "next": "https://evil.example.com/steal",
        },
    )

    assert response.status_code == 302
    assert "evil.example.com" not in response.url


def test_inactive_user_cannot_log_in(client, customer):
    customer.is_active = False
    customer.save(update_fields=["is_active"])

    response = client.post(
        LOGIN_URL, {"username": "customer@example.com", "password": "test-pass-12345"}
    )

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session

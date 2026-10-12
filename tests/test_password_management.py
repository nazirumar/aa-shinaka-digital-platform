"""Password reset and change tests (checklist item 10)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.dashboard.models import AuditLog

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_password_reset_sends_email(client, customer, mailoutbox):
    response = client.post(reverse("accounts:password_reset"), {"email": "customer@example.com"})

    assert response.status_code == 302
    assert len(mailoutbox) == 1


def test_password_reset_does_not_reveal_unknown_email(client, mailoutbox):
    response = client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})

    # Same response whether or not the account exists.
    assert response.status_code == 302
    assert mailoutbox == []


def test_password_reset_full_flow(client, customer):
    uid = urlsafe_base64_encode(force_bytes(customer.pk))
    token = default_token_generator.make_token(customer)
    url = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token})

    # First GET stores the token in the session and redirects to a "set-password" URL.
    response = client.get(url)
    assert response.status_code == 302
    post_url = response.url
    assert "set-password" in post_url

    response = client.post(
        post_url,
        {"new_password1": "BrandNewPass!2026", "new_password2": "BrandNewPass!2026"},
    )

    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.check_password("BrandNewPass!2026")


def test_password_change_via_account(client, customer):
    client.force_login(customer)

    response = client.post(
        reverse("account:security"),
        {
            "old_password": "test-pass-12345",
            "new_password1": "AnotherGoodPass!2026",
            "new_password2": "AnotherGoodPass!2026",
        },
    )

    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.check_password("AnotherGoodPass!2026")
    assert AuditLog.objects.filter(action="account.password_changed", actor=customer).exists()


def test_password_change_keeps_current_session(client, customer):
    client.force_login(customer)

    client.post(
        reverse("account:security"),
        {
            "old_password": "test-pass-12345",
            "new_password1": "AnotherGoodPass!2026",
            "new_password2": "AnotherGoodPass!2026",
        },
    )

    assert client.get(reverse("account:dashboard")).status_code == 200


def test_password_change_invalidates_other_sessions(client, customer):
    from django.test import Client

    other = Client()
    other.force_login(customer)
    assert other.get(reverse("account:dashboard")).status_code == 200

    client.force_login(customer)
    client.post(
        reverse("account:security"),
        {
            "old_password": "test-pass-12345",
            "new_password1": "AnotherGoodPass!2026",
            "new_password2": "AnotherGoodPass!2026",
        },
    )

    # The other session's stored hash no longer matches -> sent to login.
    response = other.get(reverse("account:dashboard"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url

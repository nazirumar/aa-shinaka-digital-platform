"""Email verification tests (checklist items 8-9 plus replay/resend)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.tokens import make_email_token
from apps.dashboard.models import AuditLog

User = get_user_model()
pytestmark = pytest.mark.django_db


def _verify_url(user):
    return reverse("accounts:verify_email", kwargs={"token": make_email_token(user)})


def test_verification_success_marks_user_verified(client, customer):
    assert customer.is_email_verified is False

    response = client.get(_verify_url(customer))

    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.is_email_verified is True
    assert customer.email_verified_at is not None


def test_verification_writes_audit_event(client, customer):
    client.get(_verify_url(customer))

    assert AuditLog.objects.filter(action="email.verified", target_id=str(customer.pk)).exists()


def test_expired_token_is_rejected(client, customer, settings):
    url = _verify_url(customer)
    settings.EMAIL_VERIFICATION_TIMEOUT = -1

    response = client.get(url)

    assert response.status_code == 400
    customer.refresh_from_db()
    assert customer.is_email_verified is False


def test_token_cannot_be_replayed(client, customer):
    url = _verify_url(customer)
    client.get(url)
    customer.refresh_from_db()
    assert customer.is_email_verified is True

    # Re-using the same link must fail because the nonce rotated.
    response = client.get(url)

    assert response.status_code == 400


def test_tampered_token_is_rejected(client, customer):
    response = client.get(
        reverse("accounts:verify_email", kwargs={"token": "not-a-real-token"}),
    )

    assert response.status_code == 400
    customer.refresh_from_db()
    assert customer.is_email_verified is False


def test_resend_verification_sends_email(client, customer, mailoutbox):
    client.force_login(customer)

    response = client.post(reverse("accounts:resend_verification"))

    assert response.status_code == 302
    assert len(mailoutbox) == 1


def test_resend_requires_authentication(client):
    response = client.post(reverse("accounts:resend_verification"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url

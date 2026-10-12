"""Registration tests (checklist items 1-4)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import UserRole

User = get_user_model()
pytestmark = pytest.mark.django_db

REGISTER_URL = reverse("accounts:register")
VALID = {
    "first_name": "Ngozi",
    "last_name": "Eze",
    "email": "ngozi@example.com",
    "phone": "08030000000",
    "password1": "RockSolidPass!2026",
    "password2": "RockSolidPass!2026",
    "accept_terms": "on",
}


def test_registration_success_creates_customer_and_verification_email(client, mailoutbox):
    response = client.post(REGISTER_URL, VALID)

    assert response.status_code == 302
    user = User.objects.get(email="ngozi@example.com")
    assert user.role == UserRole.CUSTOMER
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.is_email_verified is False
    assert user.check_password("RockSolidPass!2026")
    assert len(mailoutbox) == 1
    assert "verify" in mailoutbox[0].subject.lower()


def test_registration_normalises_email_case(client):
    data = {**VALID, "email": "NgOzi@Example.COM"}

    client.post(REGISTER_URL, data)

    assert User.objects.filter(email="ngozi@example.com").exists()


def test_duplicate_email_rejected(client, customer):
    data = {**VALID, "email": "customer@example.com"}

    response = client.post(REGISTER_URL, data)

    assert response.status_code == 200
    assert User.objects.filter(email="customer@example.com").count() == 1


def test_duplicate_email_is_case_insensitive(client, customer):
    data = {**VALID, "email": "CUSTOMER@example.com"}

    response = client.post(REGISTER_URL, data)

    assert response.status_code == 200
    assert User.objects.count() == 1


def test_weak_password_rejected(client):
    data = {**VALID, "password1": "123", "password2": "123"}

    response = client.post(REGISTER_URL, data)

    assert response.status_code == 200
    assert not User.objects.filter(email="ngozi@example.com").exists()


def test_terms_must_be_accepted(client):
    data = {k: v for k, v in VALID.items() if k != "accept_terms"}

    response = client.post(REGISTER_URL, data)

    assert response.status_code == 200
    assert not User.objects.filter(email="ngozi@example.com").exists()


def test_public_registration_cannot_assign_staff_or_superuser(client):
    data = {**VALID, "role": "owner", "is_staff": "on", "is_superuser": "on"}

    client.post(REGISTER_URL, data)

    user = User.objects.get(email="ngozi@example.com")
    assert user.role == UserRole.CUSTOMER
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.groups.count() == 0 or not user.groups.exclude(name="role:customer").exists()

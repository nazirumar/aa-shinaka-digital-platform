"""Tests for the custom email-based user model."""

import pytest
from django.contrib.auth import authenticate, get_user_model

from apps.accounts.models import STAFF_ROLES, UserRole

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_create_user_uses_email_and_defaults_to_customer():
    user = User.objects.create_user(email="Ada@Example.com", password="secret-pass-1")

    assert user.email == "ada@example.com"  # case-normalised
    assert user.role == UserRole.CUSTOMER
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.check_password("secret-pass-1")
    assert user.pk is not None


def test_email_is_required():
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="secret-pass-1")


def test_create_superuser_sets_owner_flags():
    admin = User.objects.create_superuser(email="boss@example.com", password="secret-pass-1")

    assert admin.is_staff is True
    assert admin.is_superuser is True
    assert admin.role == UserRole.OWNER
    assert admin.is_owner is True


def test_create_superuser_rejects_non_staff_flags():
    with pytest.raises(ValueError):
        User.objects.create_superuser(
            email="boss@example.com", password="secret-pass-1", is_staff=False
        )


def test_login_with_email(customer):
    assert authenticate(username="customer@example.com", password="test-pass-12345") == customer


def test_login_email_is_case_insensitive(customer):
    assert authenticate(username="CUSTOMER@example.com", password="test-pass-12345") == customer


def test_full_name_falls_back_to_email():
    user = User.objects.create_user(email="noname@example.com", password="secret-pass-1")
    assert user.full_name == "noname@example.com"


def test_is_staff_role_reflects_role(customer, staff_user):
    assert customer.is_staff_role is False
    assert staff_user.is_staff_role is True
    assert staff_user.role in STAFF_ROLES


def test_role_set_is_the_ten_canonical_roles():
    assert set(UserRole.values) == {
        "customer",
        "sales_officer",
        "inventory_officer",
        "consultant",
        "training_manager",
        "export_officer",
        "finance_officer",
        "content_editor",
        "administrator",
        "owner",
    }
    assert UserRole.CUSTOMER not in STAFF_ROLES


def test_email_must_be_unique():
    from django.db import IntegrityError, transaction

    User.objects.create_user(email="dupe@example.com", password="secret-pass-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(email="DupE@example.com", password="secret-pass-2")

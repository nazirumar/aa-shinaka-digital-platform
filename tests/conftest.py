"""Shared pytest fixtures for the AA Shinaka platform."""

import pytest
from django.core.cache import cache

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups


@pytest.fixture(autouse=True)
def _clear_cache():
    """Keep rate-limit counters from leaking between tests."""
    cache.clear()
    yield
    cache.clear()


def _make_user(**kwargs) -> User:
    role = kwargs.pop("role", UserRole.CUSTOMER)
    is_staff = kwargs.pop("is_staff", role in UserRole.values and role != UserRole.CUSTOMER)
    user = User.objects.create_user(role=role, is_staff=is_staff, **kwargs)
    sync_user_groups(user)
    return user


@pytest.fixture
def customer(db) -> User:
    return _make_user(
        email="customer@example.com",
        password="test-pass-12345",
        first_name="Chioma",
        last_name="Okafor",
        role=UserRole.CUSTOMER,
    )


@pytest.fixture
def staff_user(db) -> User:
    """A non-privileged staff member (cannot manage staff)."""
    return _make_user(
        email="staff@example.com",
        password="test-pass-12345",
        first_name="Bala",
        last_name="Yusuf",
        role=UserRole.SALES_OFFICER,
    )


@pytest.fixture
def administrator(db) -> User:
    return _make_user(
        email="admin@example.com",
        password="test-pass-12345",
        first_name="Amina",
        last_name="Bello",
        role=UserRole.ADMINISTRATOR,
    )


@pytest.fixture
def owner(db) -> User:
    user = User.objects.create_superuser(
        email="owner@example.com",
        password="test-pass-12345",
        first_name="Owner",
        last_name="Shinaka",
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def media_root(tmp_path, settings):
    """Redirect MEDIA_ROOT to a per-test temp directory (no repo pollution)."""
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def state(db):
    from apps.locations.models import Country, State

    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria"})
    return State.objects.create(name="Kaduna", code="KD", zone="NW", country=ng)


@pytest.fixture
def lga(db, state):
    from apps.locations.models import LGA

    return LGA.objects.create(name="Zaria", code="ZAR", state=state)

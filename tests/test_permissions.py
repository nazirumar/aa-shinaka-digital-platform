"""Permission matrix and escalation-guard tests (items 14, 16, 19)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.accounts.permissions import (
    assignable_roles,
    can_assign_role,
    can_manage_target,
    user_capabilities,
)
from apps.accounts.roles import Capability

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_capabilities_come_from_role_groups(staff_user, administrator, customer):
    own = user_capabilities(staff_user)
    assert Capability.CATALOG_MANAGE in own
    assert Capability.STAFF_MANAGE not in own

    assert Capability.STAFF_MANAGE in user_capabilities(administrator)
    assert user_capabilities(customer) == frozenset()


def test_superuser_has_all_capabilities(owner):
    assert user_capabilities(owner) >= {Capability.STAFF_MANAGE, Capability.AUDIT_VIEW}


def test_can_assign_role_rules(administrator, owner):
    # Administrators may assign ordinary staff roles...
    assert can_assign_role(administrator, UserRole.CONSULTANT) is True
    # ...but not peers, owners or customers.
    assert can_assign_role(administrator, UserRole.ADMINISTRATOR) is False
    assert can_assign_role(administrator, UserRole.OWNER) is False
    assert can_assign_role(administrator, UserRole.CUSTOMER) is False
    # Owners may assign anything staff-related.
    assert can_assign_role(owner, UserRole.OWNER) is True
    assert can_assign_role(owner, UserRole.ADMINISTRATOR) is True


def test_assignable_roles_excludes_privileged_for_admin(administrator):
    values = {value for value, _ in assignable_roles(administrator)}
    assert UserRole.OWNER not in values
    assert UserRole.ADMINISTRATOR not in values
    assert UserRole.CONSULTANT in values


def test_can_manage_target_guards(administrator, owner, customer):
    assert can_manage_target(owner, administrator) is True
    assert can_manage_target(administrator, owner) is False
    assert can_manage_target(administrator, customer) is False
    # Never yourself.
    assert can_manage_target(owner, owner) is False


def test_customer_cannot_reach_dashboard(client, customer):
    client.force_login(customer)

    assert client.get(reverse("dashboard:home")).status_code == 403
    assert client.get(reverse("dashboard:staff_list")).status_code == 403


def test_non_privileged_staff_cannot_reach_staff_directory(client, staff_user):
    client.force_login(staff_user)

    assert client.get(reverse("dashboard:staff_list")).status_code == 403


def test_administrator_can_reach_dashboard(client, administrator):
    client.force_login(administrator)

    assert client.get(reverse("dashboard:home")).status_code == 200
    assert client.get(reverse("dashboard:staff_list")).status_code == 200


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("dashboard:home"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url

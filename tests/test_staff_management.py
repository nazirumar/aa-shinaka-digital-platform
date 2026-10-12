"""Staff management dashboard tests (checklist items 13, 15)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.dashboard.models import AuditLog

User = get_user_model()
pytestmark = pytest.mark.django_db

CREATE_URL = reverse("dashboard:staff_create")


def _staff_payload(**overrides):
    payload = {
        "first_name": "New",
        "last_name": "Officer",
        "email": "newofficer@example.com",
        "phone": "08050000000",
        "role": UserRole.CONSULTANT,
        "password1": "StaffPass!2026x",
        "password2": "StaffPass!2026x",
    }
    payload.update(overrides)
    return payload


def test_owner_creates_staff(client, owner):
    client.force_login(owner)

    response = client.post(CREATE_URL, _staff_payload())

    assert response.status_code == 302
    staff = User.objects.get(email="newofficer@example.com")
    assert staff.role == UserRole.CONSULTANT
    assert staff.is_staff is True
    assert staff.is_superuser is False
    assert staff.groups.filter(name="role:consultant").exists()
    assert AuditLog.objects.filter(action="staff.created", target_id=str(staff.pk)).exists()


def test_administrator_creates_staff(client, administrator):
    client.force_login(administrator)

    response = client.post(CREATE_URL, _staff_payload(email="adminmade@example.com"))

    assert response.status_code == 302
    assert User.objects.filter(email="adminmade@example.com", is_staff=True).exists()


def test_administrator_cannot_create_owner(client, administrator):
    client.force_login(administrator)

    response = client.post(CREATE_URL, _staff_payload(role=UserRole.OWNER))

    assert response.status_code == 200
    assert not User.objects.filter(email="newofficer@example.com").exists()


def test_customer_and_staff_cannot_create_staff(client, customer, staff_user):
    client.force_login(customer)
    assert client.post(CREATE_URL, _staff_payload()).status_code == 403

    client.force_login(staff_user)
    assert client.post(CREATE_URL, _staff_payload()).status_code == 403


def test_role_assignment(client, owner, staff_user):
    client.force_login(owner)

    response = client.post(
        reverse("dashboard:staff_edit", args=[staff_user.pk]),
        {"form_name": "role", "role": UserRole.INVENTORY_OFFICER},
    )

    assert response.status_code == 302
    staff_user.refresh_from_db()
    assert staff_user.role == UserRole.INVENTORY_OFFICER
    assert staff_user.groups.filter(name="role:inventory_officer").exists()
    assert AuditLog.objects.filter(
        action="staff.role_assigned", target_id=str(staff_user.pk)
    ).exists()


def test_administrator_cannot_escalate_to_owner(client, administrator, staff_user):
    client.force_login(administrator)

    response = client.post(
        reverse("dashboard:staff_edit", args=[staff_user.pk]),
        {"form_name": "role", "role": UserRole.OWNER},
    )

    assert response.status_code == 200
    staff_user.refresh_from_db()
    assert staff_user.role == UserRole.SALES_OFFICER


def test_administrator_cannot_edit_owner(client, administrator, owner):
    client.force_login(administrator)

    response = client.post(
        reverse("dashboard:staff_edit", args=[owner.pk]),
        {"form_name": "role", "role": UserRole.CONSULTANT},
    )

    assert response.status_code == 403


def test_staff_deactivation(client, owner, staff_user):
    client.force_login(owner)

    response = client.post(
        reverse("dashboard:staff_toggle_active", args=[staff_user.pk]),
        {"active": "false"},
    )

    assert response.status_code == 302
    staff_user.refresh_from_db()
    assert staff_user.is_active is False
    assert AuditLog.objects.filter(
        action="staff.deactivated", target_id=str(staff_user.pk)
    ).exists()


def test_staff_reactivation(client, owner, staff_user):
    staff_user.is_active = False
    staff_user.save(update_fields=["is_active"])
    client.force_login(owner)

    client.post(reverse("dashboard:staff_toggle_active", args=[staff_user.pk]), {"active": "true"})

    staff_user.refresh_from_db()
    assert staff_user.is_active is True


def test_owner_cannot_deactivate_self(client, owner):
    client.force_login(owner)

    client.post(
        reverse("dashboard:staff_toggle_active", args=[owner.pk]),
        {"active": "false"},
        follow=True,
    )

    owner.refresh_from_db()
    assert owner.is_active is True


def test_staff_search_filters_results(client, administrator, staff_user):
    client.force_login(administrator)

    response = client.get(reverse("dashboard:staff_list"), {"q": "Bala"})

    assert response.status_code == 200
    assert b"Bala" in response.content


def test_staff_list_htmx_returns_partial(client, administrator):
    client.force_login(administrator)

    response = client.get(reverse("dashboard:staff_list"), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b"<html" not in response.content.lower()

"""Audit logging tests (checklist item 18)."""

import pytest

from apps.accounts.models import User
from apps.core.audit import REDACTED, record_audit
from apps.dashboard.models import AuditLog

pytestmark = pytest.mark.django_db


def test_record_audit_basic_fields(owner):
    entry = record_audit(actor=owner, action="test.action", target=owner, after={"role": "owner"})

    assert entry.actor == owner
    assert entry.action == "test.action"
    assert entry.target_type == "accounts.User"
    assert entry.target_id == str(owner.pk)
    assert entry.after == {"role": "owner"}


def test_record_audit_redacts_sensitive_keys(owner):
    entry = record_audit(
        actor=owner,
        action="test.secret",
        after={"password": "hunter2", "token": "abc", "safe": "ok"},
    )

    assert entry.after["password"] == REDACTED
    assert entry.after["token"] == REDACTED
    assert entry.after["safe"] == "ok"


def test_record_audit_captures_request_metadata(owner, rf):
    request = rf.post("/x/", HTTP_USER_AGENT="pytest-agent", REMOTE_ADDR="203.0.113.9")

    entry = record_audit(actor=owner, action="test.meta", request=request)

    assert entry.ip_address == "203.0.113.9"
    assert entry.user_agent == "pytest-agent"


def test_record_audit_ignores_anonymous_actor(rf):
    from django.contrib.auth.models import AnonymousUser

    entry = record_audit(actor=AnonymousUser(), action="test.anon")
    assert entry.actor is None


def test_audit_entries_are_append_only(owner):
    entry = record_audit(actor=owner, action="test.immutable")

    entry.action = "changed"
    with pytest.raises(ValueError):
        entry.save()

    with pytest.raises(ValueError):
        entry.delete()


def test_audit_admin_is_read_only():
    from apps.dashboard.admin import AuditLogAdmin

    admin_instance = AuditLogAdmin(AuditLog, None)
    assert admin_instance.has_add_permission(None) is False
    assert admin_instance.has_change_permission(None) is False
    assert admin_instance.has_delete_permission(None) is False


def test_profile_update_creates_audit_entry(client, customer, state):
    client.force_login(customer)

    client.post(
        "/account/profile/",
        {"first_name": "Chioma", "last_name": "Updated", "phone": "08011111111", "state": state.pk},
    )

    assert AuditLog.objects.filter(action="account.profile_updated", actor=customer).exists()


def test_staff_creation_audit_has_actor(client, owner):
    client.force_login(owner)

    client.post(
        "/dashboard/staff/create/",
        {
            "first_name": "Aud",
            "last_name": "Ited",
            "email": "audited@example.com",
            "role": "consultant",
            "password1": "StaffPass!2026x",
            "password2": "StaffPass!2026x",
        },
    )

    target = User.objects.get(email="audited@example.com")
    entry = AuditLog.objects.get(action="staff.created", target_id=str(target.pk))
    assert entry.actor == owner

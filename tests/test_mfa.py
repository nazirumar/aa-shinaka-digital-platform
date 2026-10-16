"""Phase 13 — TOTP MFA tests for privileged accounts (Step 2).

Covers: enrollment security, TOTP correctness, verification, recovery codes,
rate limiting, session/challenge flow, disable/reset authorisation, and audit
records.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.accounts.mfa.models import MFADevice, MFARecoveryCode
from apps.accounts.mfa.services import (
    confirm_enrollment,
    disable_mfa,
    reset_mfa,
    start_enrollment,
    verify_challenge,
)
from apps.accounts.mfa.utils import generate_secret_base32, totp_code, verify_totp
from apps.dashboard.models import AuditLog

User = get_user_model()
pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# TOTP primitives
# ---------------------------------------------------------------------------
def test_totp_matches_current_window():
    secret = generate_secret_base32()
    code = totp_code(secret)
    assert verify_totp(secret, code)
    assert len(code) == 6


def test_totp_rejects_wrong_code():
    secret = generate_secret_base32()
    wrong = "000000" if totp_code(secret) != "000000" else "111111"
    assert not verify_totp(secret, wrong)


def test_totp_accepts_adjacent_step():
    secret = generate_secret_base32()
    future = totp_code(secret, offset=30)
    past = totp_code(secret, offset=-30)
    assert verify_totp(secret, future)
    assert verify_totp(secret, past)


def test_totp_does_not_accept_far_future_code():
    secret = generate_secret_base32()
    far = totp_code(secret, offset=30 * 5)
    assert not verify_totp(secret, far, window=1)


def test_secret_is_stable_format():
    s1, s2 = generate_secret_base32(), generate_secret_base32()
    assert s1 != s2
    assert len(s1) >= 32
    assert set(s1) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
def _start(user, actor=None):
    return start_enrollment(actor or user, target=None if actor is None else user)


def test_enrollment_creates_unconfirmed_device_and_recovery_codes(administrator):
    device, secret, codes = start_enrollment(administrator)
    device.refresh_from_db()
    assert device.is_confirmed is False
    assert secret
    assert len(codes) == 10
    assert MFARecoveryCode.objects.filter(user=administrator).count() == 10
    # Codes are stored hashed, never in clear.
    assert not MFARecoveryCode.objects.filter(code_hash__in=codes).exists()


def test_enrollment_secret_is_encrypted_at_rest(administrator):
    device, secret, _codes = start_enrollment(administrator)
    device.refresh_from_db()
    assert device.secret_encrypted != secret
    assert secret not in device.secret_encrypted
    # But round-trips back to the original.
    assert device.get_secret() == secret


def test_enrollment_writes_audit_entry(administrator):
    start_enrollment(administrator)
    assert AuditLog.objects.filter(action="mfa.enrolled", actor=administrator).exists()


def test_confirm_requires_valid_code(administrator):
    device, _secret, _codes = start_enrollment(administrator)
    bad = "000000" if totp_code(device.get_secret()) != "000000" else "111111"
    with pytest.raises(ValidationError):
        confirm_enrollment(administrator, bad)
    device.refresh_from_db()
    assert device.is_confirmed is False


def test_confirm_accepts_valid_code(administrator):
    device, secret, _codes = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    device.refresh_from_db()
    assert device.is_confirmed is True
    assert AuditLog.objects.filter(action="mfa.confirmed", actor=administrator).exists()


def test_confirm_without_enrollment_raises(administrator):
    with pytest.raises(ValidationError):
        confirm_enrollment(administrator, "123456")


# ---------------------------------------------------------------------------
# Verification & recovery codes
# ---------------------------------------------------------------------------
def test_verify_with_totp(administrator):
    device, secret, _codes = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    assert verify_challenge(administrator, {"code": totp_code(secret)}) is True
    device.refresh_from_db()
    assert device.last_used_at is not None


def test_verify_with_recovery_code_is_single_use(administrator):
    _device, secret, codes = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    first = codes[0]
    assert verify_challenge(administrator, {"recovery_code": first}) is True
    # Second use of the same code must fail.
    with pytest.raises(ValidationError):
        verify_challenge(administrator, {"recovery_code": first})
    assert AuditLog.objects.filter(action="mfa.recovery_used").count() == 1


def test_verify_rejects_invalid_recovery_code(administrator):
    _device, secret, _codes = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    with pytest.raises(ValidationError):
        verify_challenge(administrator, {"recovery_code": "DEADBEEFDEADBEEF"})


def test_verify_requires_either_code_or_recovery(administrator):
    _device, secret, _codes = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    with pytest.raises(ValidationError):
        verify_challenge(administrator, {})


# ---------------------------------------------------------------------------
# Login flow integration
# ---------------------------------------------------------------------------
def test_privileged_login_with_mfa_redirects_to_challenge(client, administrator):
    # Enrol + confirm MFA
    _d, secret, _c = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))

    resp = client.post(
        reverse("accounts:login"),
        {"username": administrator.email, "password": "test-pass-12345"},
    )
    assert resp.status_code == 302
    assert resp.url == reverse("mfa:challenge")
    # NOT authenticated yet.
    assert "_auth_user_id" not in client.session


def test_challenge_completes_login(client, administrator):
    _d, secret, _c = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))

    client.post(
        reverse("accounts:login"),
        {"username": administrator.email, "password": "test-pass-12345"},
    )
    resp = client.post(reverse("mfa:challenge"), {"code": totp_code(secret)})
    assert resp.status_code == 302
    assert client.session["_auth_user_id"] == str(administrator.pk)


def test_challenge_rejects_bad_code(client, administrator):
    _d, secret, _c = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    client.post(
        reverse("accounts:login"),
        {"username": administrator.email, "password": "test-pass-12345"},
    )
    bad = "000000" if totp_code(secret) != "000000" else "111111"
    resp = client.post(reverse("mfa:challenge"), {"code": bad})
    assert resp.status_code == 200  # stays on the challenge page with an error
    assert "_auth_user_id" not in client.session


def test_customer_without_mfa_logs_in_normally(client, customer):
    resp = client.post(
        reverse("accounts:login"),
        {"username": customer.email, "password": "test-pass-12345"},
    )
    assert resp.status_code == 302
    assert client.session["_auth_user_id"] == str(customer.pk)


def test_enrolled_user_keeps_challenge_even_after_role_downgrade(client, administrator):
    """MFA is not silently dropped when privileged access is lost."""
    _d, secret, _c = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    # Downgrade to customer (simulating access revocation).
    administrator.role = "customer"
    administrator.save(update_fields=["role"])

    resp = client.post(
        reverse("accounts:login"),
        {"username": administrator.email, "password": "test-pass-12345"},
    )
    assert resp.url == reverse("mfa:challenge")
    assert "_auth_user_id" not in client.session


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
def test_challenge_rate_limiting(client, administrator):
    _d, secret, _c = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    client.post(
        reverse("accounts:login"),
        {"username": administrator.email, "password": "test-pass-12345"},
    )
    bad = "000000" if totp_code(secret) != "000000" else "111111"
    for _ in range(5):
        client.post(reverse("mfa:challenge"), {"code": bad})
    # 6th attempt is over the limit.
    resp = client.post(reverse("mfa:challenge"), {"code": bad})
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Disable / reset authorization
# ---------------------------------------------------------------------------
def test_disable_requires_valid_code(administrator):
    _d, secret, _c = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    bad = "000000" if totp_code(secret) != "000000" else "111111"
    with pytest.raises(ValidationError):
        disable_mfa(administrator, form_data={"code": bad})
    assert MFADevice.objects.filter(user=administrator, is_confirmed=True).exists()


def test_disable_with_valid_code(administrator):
    _d, secret, _c = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    disable_mfa(administrator, form_data={"code": totp_code(secret)})
    assert not MFADevice.objects.filter(user=administrator).exists()
    assert AuditLog.objects.filter(action="mfa.disabled").exists()


def test_non_privileged_cannot_reset_others_mfa(owner, staff_user):
    with pytest.raises(PermissionDenied):
        reset_mfa(staff_user, target=owner)


def test_owner_can_reset_staff_mfa(owner, staff_user):
    device, secret, codes = reset_mfa(owner, target=staff_user)
    device.refresh_from_db()
    assert device.is_confirmed is False
    assert len(codes) == 10


def test_reset_preserves_mfa_enforcement_until_reconfirmed(owner, administrator):
    _d, secret, _c = start_enrollment(administrator)
    confirm_enrollment(administrator, totp_code(secret))
    reset_mfa(owner, target=administrator)
    administrator.refresh_from_db()
    device = MFADevice.objects.get(user=administrator)
    # Reset puts it back to unconfirmed; no silent auto-disable to "off".
    assert device.is_confirmed is False

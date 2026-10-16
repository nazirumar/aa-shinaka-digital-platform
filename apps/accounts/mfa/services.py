"""MFA services (transactional, audited).

Every state-changing operation lives here, mirrors the ``accounts.services``
convention: authorization on the server, audit entry via ``record_audit``,
transactions around multi-row writes. Views stay thin.
"""

from __future__ import annotations

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import PRIVILEGED_ROLES, User
from apps.core.audit import record_audit

from .forms import VerifyTOTPForm
from .models import MFADevice, MFARecoveryCode
from .utils import generate_secret_base32, verify_totp

RECOVERY_CODE_COUNT = 10


def is_mfa_required(user: User) -> bool:
    """MFA is mandatory *once enrolled* for privileged accounts.

    Privileged staff (administrator, owner, finance officer, superusers) are
    prompted to enrol; existing customers never see an MFA challenge.
    """
    return bool(
        user and user.is_authenticated and (user.role in PRIVILEGED_ROLES or user.is_superuser)
    )


def mfa_enforced(user: User) -> bool:
    """Whether a password-verified login must still pass an MFA challenge.

    Keyed on the **device**, not the role: once an account has enrolled, the
    factor stays enforced even if the user later loses privileged access — MFA
    is never silently dropped (per Phase 13 policy). Only an explicit,
    code-verified disable removes it.
    """
    if not user or not user.is_authenticated:
        return False
    return MFADevice.objects.filter(user=user, is_confirmed=True).exists()


def _check_actor_may_manage(actor: User | None, target: User) -> None:
    if actor is None or actor == target:
        return
    if actor.is_superuser or (actor.role in PRIVILEGED_ROLES and target.role in PRIVILEGED_ROLES):
        return
    raise PermissionDenied("Insufficient privileges to manage MFA for this account.")


def _audit(*, actor, request, action: str, target: User, after: dict | None = None) -> None:
    record_audit(actor=actor, action=action, target=target, after=after, request=request)


@transaction.atomic
def start_enrollment(
    actor: User, *, target: User | None = None, request=None
) -> tuple[MFADevice, str, list[str]]:
    """Begin MFA enrolment: mint a fresh TOTP secret and one-time recovery codes."""
    subject = target or actor
    _check_actor_may_manage(actor, subject)

    device, _created = MFADevice.objects.get_or_create(user=subject)
    secret = generate_secret_base32()
    device.secret_encrypted = ""
    device.is_confirmed = False
    device.set_secret(secret)
    device.save(update_fields=["secret_encrypted", "is_confirmed"])

    MFARecoveryCode.objects.filter(user=subject, used_at__isnull=True).delete()
    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        code = MFARecoveryCode.generate_code()
        MFARecoveryCode.objects.create(user=subject, code_hash=make_password(code))
        codes.append(code)

    _audit(
        actor=actor,
        request=request,
        action="mfa.enrolled",
        target=subject,
        after={"confirmed": False},
    )
    return device, secret, codes


@transaction.atomic
def confirm_enrollment(
    actor: User, code: str, *, target: User | None = None, request=None
) -> MFADevice:
    """Verify the first TOTP code and switch MFA on."""
    subject = target or actor
    _check_actor_may_manage(actor, subject)
    try:
        device = MFADevice.objects.get(user=subject)
    except MFADevice.DoesNotExist as exc:
        raise ValidationError("MFA enrolment has not been started.") from exc

    secret = device.get_secret()
    if not secret or not verify_totp(secret, code.strip()):
        raise ValidationError("Invalid verification code. Check your authenticator app.")

    device.is_confirmed = True
    device.save(update_fields=["is_confirmed"])
    _audit(
        actor=actor,
        request=request,
        action="mfa.confirmed",
        target=subject,
        after={"confirmed": True},
    )
    return device


@transaction.atomic
def verify_challenge(
    actor: User, form_data: dict, *, target: User | None = None, request=None
) -> bool:
    """Verify a TOTP code or a single-use recovery code."""
    subject = target or actor
    try:
        device = MFADevice.objects.get(user=subject, is_confirmed=True)
    except MFADevice.DoesNotExist as exc:
        raise ValidationError("MFA is not configured for this account.") from exc

    form = VerifyTOTPForm(form_data)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())

    cleaned = form.cleaned_data
    if cleaned.get("code"):
        if not verify_totp(device.get_secret(), cleaned["code"]):
            raise ValidationError("Invalid verification code.")
        device.last_used_at = timezone.now()
        device.save(update_fields=["last_used_at"])
        _audit(actor=actor, request=request, action="mfa.verified", target=subject)
        return True

    candidate = cleaned["recovery_code"]
    # Check every unused code (hash comparison is per-row; the list is small)
    # inside the transaction so a code cannot be redeemed twice concurrently.
    for rc in MFARecoveryCode.objects.select_for_update().filter(
        user=subject, used_at__isnull=True
    ):
        if check_password(candidate, rc.code_hash):
            rc.mark_used()
            _audit(actor=actor, request=request, action="mfa.recovery_used", target=subject)
            return True
    raise ValidationError("Invalid recovery code.")


@transaction.atomic
def disable_mfa(
    actor: User, *, target: User | None = None, request=None, form_data: dict | None = None
) -> None:
    """Turn MFA off. Requires a fresh TOTP code (or recovery code) from the
    account's own device — a stolen session alone can never drop the factor."""
    subject = target or actor
    _check_actor_may_manage(actor, subject)
    if form_data:
        verify_challenge(actor, form_data, target=subject, request=request)
    MFADevice.objects.filter(user=subject).delete()
    MFARecoveryCode.objects.filter(user=subject).delete()
    _audit(actor=actor, request=request, action="mfa.disabled", target=subject)


@transaction.atomic
def reset_mfa(
    actor: User, *, target: User | None = None, request=None
) -> tuple[MFADevice, str, list[str]]:
    """Authorised MFA reset (lost device): re-enrol the target account.

    Only a superuser or a fellow privileged admin may reset someone else's MFA;
    the action is audited and does **not** silently drop MFA — enrolment must be
    re-confirmed before the challenge disappears.
    """
    subject = target or actor
    _check_actor_may_manage(actor, subject)
    return start_enrollment(actor, target=subject, request=request)

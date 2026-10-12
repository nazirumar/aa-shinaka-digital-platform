"""Write operations for accounts, staff and email verification.

Every state-changing operation lives here, is wrapped in a transaction where it
touches multiple rows, enforces authorisation on the server, and writes an audit
entry. Views stay thin.
"""

from __future__ import annotations

import secrets
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit

from .models import STAFF_ROLES, Address, User, UserRole
from .permissions import can_assign_role, can_manage_target
from .roles import sync_user_groups
from .tokens import (
    EmailTokenError,
    EmailTokenExpired,
    EmailTokenInvalid,
    read_email_token,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
@transaction.atomic
def register_customer(
    *,
    email: str,
    first_name: str,
    last_name: str,
    phone: str,
    password: str,
    marketing_opt_in: bool = False,
) -> User:
    """Create a customer account. Never grants staff or superuser privileges."""
    if User.objects.filter(email__iexact=email.strip()).exists():
        raise ValidationError("An account with this email already exists.")
    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone=phone.strip(),
        role=UserRole.CUSTOMER,
        is_staff=False,
        is_superuser=False,
        marketing_opt_in=marketing_opt_in,
    )
    sync_user_groups(user)
    return user


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------
def verify_email_token(token: str) -> tuple[User | None, str]:
    """Resolve a verification token to a user.

    Returns ``(user, status)`` where status is one of
    ``ok``, ``already``, ``expired`` or ``invalid``.
    """
    try:
        data = read_email_token(token)
    except EmailTokenExpired:
        return None, "expired"
    except (EmailTokenInvalid, EmailTokenError):
        return None, "invalid"

    user = User.objects.filter(pk=data.get("uid")).first()
    if user is None:
        return None, "invalid"
    if str(user.email_verification_nonce) != str(data.get("nonce")):
        # Nonce rotated => token already used or superseded.
        return None, "invalid"
    if user.is_email_verified:
        return user, "already"
    return user, "ok"


@transaction.atomic
def mark_email_verified(*, user: User, request=None) -> User:
    """Mark a user's email as verified and rotate the verification nonce."""
    if user.is_email_verified:
        return user
    user.is_email_verified = True
    user.email_verified_at = timezone.now()
    user.email_verification_nonce = uuid.uuid4()
    user.save(
        update_fields=[
            "is_email_verified",
            "email_verified_at",
            "email_verification_nonce",
            "updated_at",
        ]
    )
    record_audit(
        actor=user,
        action="email.verified",
        target=user,
        after={"email": user.email},
        request=request,
    )
    return user


def confirm_email_token(*, token: str, request=None) -> tuple[User | None, str]:
    """Validate a token and, when valid, mark the email verified."""
    user, status = verify_email_token(token)
    if status == "ok" and user is not None:
        user = mark_email_verified(user=user, request=request)
    return user, status


def resend_verification_email(user: User) -> None:
    """Send a fresh verification email (rotates nothing; old links stay valid)."""
    from .emails import send_email_verification

    send_email_verification(user)


# ---------------------------------------------------------------------------
# Staff management
# ---------------------------------------------------------------------------
def _generate_password() -> str:
    return secrets.token_urlsafe(16)


@transaction.atomic
def create_staff(
    *,
    actor: User,
    email: str,
    first_name: str,
    last_name: str,
    phone: str = "",
    role: str,
    password: str | None = None,
    request=None,
) -> User:
    """Create a staff account. Only authorised actors may assign ``role``."""
    if role not in STAFF_ROLES:
        raise PermissionDenied("A staff account must be given a staff role.")
    if not can_assign_role(actor, role):
        raise PermissionDenied("You are not allowed to assign this role.")
    if User.objects.filter(email__iexact=email.strip()).exists():
        raise ValidationError("An account with this email already exists.")

    temporary_password = password or _generate_password()
    user = User.objects.create_user(
        email=email,
        password=temporary_password,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone=phone.strip(),
        role=role,
        is_staff=True,
        is_superuser=False,
    )
    sync_user_groups(user)
    record_audit(
        actor=actor,
        action="staff.created",
        target=user,
        after={"email": user.email, "role": user.role},
        request=request,
    )
    return user


@transaction.atomic
def update_staff(
    *,
    actor: User,
    target: User,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    request=None,
) -> User:
    """Update permitted profile fields of a staff account."""
    if not can_manage_target(actor, target):
        raise PermissionDenied("You are not allowed to edit this account.")

    before = {
        "first_name": target.first_name,
        "last_name": target.last_name,
        "phone": target.phone,
    }
    changed: list[str] = []
    if first_name is not None:
        target.first_name = first_name.strip()
        changed.append("first_name")
    if last_name is not None:
        target.last_name = last_name.strip()
        changed.append("last_name")
    if phone is not None:
        target.phone = phone.strip()
        changed.append("phone")
    if changed:
        target.save(update_fields=[*changed, "updated_at"])
        record_audit(
            actor=actor,
            action="staff.updated",
            target=target,
            before=before,
            after={
                "first_name": target.first_name,
                "last_name": target.last_name,
                "phone": target.phone,
            },
            request=request,
        )
    return target


@transaction.atomic
def assign_role(*, actor: User, target: User, role: str, request=None) -> User:
    """Assign a role to a staff account, enforcing privilege-escalation rules."""
    if not can_manage_target(actor, target):
        raise PermissionDenied("You are not allowed to change this account.")
    if not can_assign_role(actor, role):
        raise PermissionDenied("You are not allowed to assign this role.")
    previous = target.role
    if previous == role:
        return target
    target.role = role
    target.is_staff = True
    target.save(update_fields=["role", "is_staff", "updated_at"])
    sync_user_groups(target)
    record_audit(
        actor=actor,
        action="staff.role_assigned",
        target=target,
        before={"role": previous},
        after={"role": role},
        request=request,
    )
    return target


@transaction.atomic
def set_staff_active(*, actor: User, target: User, active: bool, request=None) -> User:
    """Activate or deactivate a staff account (never the actor themselves)."""
    if not can_manage_target(actor, target):
        raise PermissionDenied("You are not allowed to change this account.")
    if target.pk == actor.pk:
        raise PermissionDenied("You cannot change your own account status.")

    target.is_active = active
    target.save(update_fields=["is_active", "updated_at"])
    record_audit(
        actor=actor,
        action="staff.activated" if active else "staff.deactivated",
        target=target,
        after={"is_active": active},
        request=request,
    )
    return target


# ---------------------------------------------------------------------------
# Customer profile & addresses
# ---------------------------------------------------------------------------
@transaction.atomic
def update_customer_profile(
    *,
    user: User,
    first_name: str,
    last_name: str,
    phone: str,
    marketing_opt_in: bool = False,
    state=None,
    request=None,
) -> User:
    before = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "marketing_opt_in": user.marketing_opt_in,
    }
    user.first_name = first_name.strip()
    user.last_name = last_name.strip()
    user.phone = phone.strip()
    user.marketing_opt_in = marketing_opt_in
    if state is not None:
        user.state = state
    user.save(
        update_fields=[
            "first_name",
            "last_name",
            "phone",
            "marketing_opt_in",
            "state",
            "updated_at",
        ]
    )
    record_audit(
        actor=user,
        action="account.profile_updated",
        target=user,
        before=before,
        after={"first_name": user.first_name, "last_name": user.last_name, "phone": user.phone},
        request=request,
    )
    return user


@transaction.atomic
def save_address(
    *,
    user: User,
    address: Address | None = None,
    make_default: bool = False,
    request=None,
    **fields,
) -> Address:
    """Create or update one of ``user``'s addresses."""
    if address is not None and address.user_id != user.id:
        raise PermissionDenied("You cannot edit another customer's address.")

    is_new = address is None
    if is_new:
        address = Address(user=user)
    for key, value in fields.items():
        setattr(address, key, value)
    # Validate with is_default unset, then assign the default afterwards so the
    # "one default per user" constraint is never tripped mid-save.
    address.is_default = False
    address.full_clean()
    address.save()

    if make_default or not user.addresses.exclude(pk=address.pk).exists():
        _set_default_address(user=user, address=address)

    record_audit(
        actor=user,
        action="account.address_created" if is_new else "account.address_saved",
        target=address,
        after={"label": address.label, "city": address.city, "is_default": address.is_default},
        request=request,
    )
    return address


@transaction.atomic
def _set_default_address(*, user: User, address: Address) -> Address:
    user.addresses.exclude(pk=address.pk).update(is_default=False)
    if not address.is_default:
        address.is_default = True
        address.save(update_fields=["is_default", "updated_at"])
    return address


@transaction.atomic
def set_default_address(*, user: User, address: Address, request=None) -> Address:
    if address.user_id != user.id:
        raise PermissionDenied("You cannot edit another customer's address.")
    _set_default_address(user=user, address=address)
    record_audit(
        actor=user,
        action="account.address_default_set",
        target=address,
        request=request,
    )
    return address


@transaction.atomic
def delete_address(*, user: User, address: Address, request=None) -> None:
    if address.user_id != user.id:
        raise PermissionDenied("You cannot delete another customer's address.")
    was_default = address.is_default
    label = address.label
    address.delete()
    record_audit(
        actor=user,
        action="account.address_deleted",
        target=user,
        after={"label": label},
        request=request,
    )
    if was_default:
        replacement = user.addresses.first()
        if replacement is not None:
            _set_default_address(user=user, address=replacement)

"""Server-side authorisation helpers.

All checks are enforced on the server. Templates may use ``user_capabilities``
only for *hiding* navigation; every view that performs an action re-checks here.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import PRIVILEGED_ROLES, STAFF_ROLES, UserRole
from .roles import ALL_CAPABILITIES, ROLE_CAPABILITIES


def user_capabilities(user) -> frozenset[str]:
    """Return the capabilities granted to ``user`` via their Django groups."""
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    if user.is_superuser:
        return ALL_CAPABILITIES
    capabilities: set[str] = set()
    for name in user.groups.values_list("name", flat=True):
        if not name.startswith("role:"):
            continue
        role = name.split(":", 1)[1]
        capabilities |= ROLE_CAPABILITIES.get(role, frozenset())
    return frozenset(capabilities)


def has_capability(user, *capabilities: str, any_of: bool = False) -> bool:
    """Check one or more capabilities; ``any_of`` switches from AND to OR."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    owned = user_capabilities(user)
    if any_of:
        return bool(owned & set(capabilities))
    return set(capabilities) <= owned


def is_staff_member(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and user.is_staff)


def can_manage_staff(actor) -> bool:
    """Whether ``actor`` may use the staff management dashboard at all."""
    return actor.is_superuser or actor.role in {UserRole.ADMINISTRATOR, UserRole.OWNER}


def can_assign_role(actor, role: str) -> bool:
    """Privilege-escalation guard for granting ``role`` to someone."""
    if role not in STAFF_ROLES:
        return False
    if not getattr(actor, "is_authenticated", False) or not actor.is_staff:
        return False
    if actor.is_superuser or actor.role == UserRole.OWNER:
        return True
    if actor.role == UserRole.ADMINISTRATOR:
        # Administrators cannot create owners or peer administrators.
        return role not in PRIVILEGED_ROLES
    return False


def assignable_roles(actor) -> list[tuple[str, str]]:
    """Roles ``actor`` is allowed to grant, as (value, label) pairs."""
    return [(role.value, role.label) for role in UserRole if can_assign_role(actor, role.value)]


def can_manage_target(actor, target) -> bool:
    """Whether ``actor`` may edit/deactivate ``target`` (never themselves)."""
    if not can_manage_staff(actor):
        return False
    if not getattr(target, "is_staff", False):
        # Staff management only governs staff accounts, never customers.
        return False
    if actor.pk == target.pk:
        return False
    if target.is_superuser or target.role == UserRole.OWNER:
        return actor.is_superuser or actor.role == UserRole.OWNER
    if target.role == UserRole.ADMINISTRATOR and not (
        actor.is_superuser or actor.role == UserRole.OWNER
    ):
        return False
    return True


def capability_required(*capabilities: str, any_of: bool = False):
    """Decorator requiring the given capability/capabilities."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not getattr(user, "is_authenticated", False):
                return redirect_to_login(request.get_full_path())
            if user.is_superuser or has_capability(user, *capabilities, any_of=any_of):
                return view(request, *args, **kwargs)
            raise PermissionDenied("You do not have permission to perform this action.")

        return wrapper

    return decorator


def staff_required(view):
    """Decorator requiring an authenticated staff user."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not request.user.is_staff:
            raise PermissionDenied("Staff access required.")
        return view(request, *args, **kwargs)

    return wrapper


def role_required(*roles: str):
    """Decorator requiring the user's role to be one of ``roles``."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not getattr(request.user, "is_authenticated", False):
                return redirect_to_login(request.get_full_path())
            if request.user.is_superuser or request.user.role in roles:
                return view(request, *args, **kwargs)
            raise PermissionDenied("You do not have permission to perform this action.")

        return wrapper

    return decorator


def roles_for_capability(capability: str) -> list[tuple[str, str]]:
    """Return (value, label) role pairs that grant ``capability``."""
    return [
        (role.value, role.label)
        for role in UserRole
        if capability in ROLE_CAPABILITIES.get(role.value, frozenset())
    ]


__all__ = [
    "assignable_roles",
    "can_assign_role",
    "can_manage_staff",
    "can_manage_target",
    "capability_required",
    "has_capability",
    "is_staff_member",
    "role_required",
    "roles_for_capability",
    "staff_required",
    "user_capabilities",
]

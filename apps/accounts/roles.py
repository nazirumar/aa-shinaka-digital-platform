"""Role definitions, capability matrix and Django group synchronisation.

Roles are represented two ways:

* ``User.role`` — the canonical, indexed role value used for display and quick
  filtering.
* A Django **Group** named ``role:<code>`` — the authority for capabilities and
  model permissions, so authorisation runs through Django's group/permission
  framework rather than frontend checks.

``sync_user_groups()`` keeps the two in step.
"""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission

from .models import UserRole

ROLE_GROUP_PREFIX = "role:"


class Capability:
    """Named capabilities used by role-based navigation and view decorators."""

    STAFF_VIEW = "staff.view"
    STAFF_MANAGE = "staff.manage"
    ROLES_ASSIGN = "roles.assign"
    AUDIT_VIEW = "audit.view"
    CATALOG_MANAGE = "catalog.manage"
    INVENTORY_MANAGE = "inventory.manage"
    ORDERS_MANAGE = "orders.manage"
    FINANCE_MANAGE = "finance.manage"
    CONTENT_VIEW = "content.view"
    CONTENT_MANAGE = "content.manage"
    CONTENT_PUBLISH = "content.publish"
    MEDIA_MANAGE = "media.manage"
    TESTIMONIALS_APPROVE = "testimonials.approve"
    CONTACT_MANAGE = "contact.manage"
    NAV_MANAGE = "nav.manage"
    SITE_CONFIG = "site.config"
    REQUESTS_CONSULTANCY = "requests.consultancy"
    REQUESTS_FARMING = "requests.farming"
    REQUESTS_MARKETING = "requests.marketing"
    REQUESTS_STORAGE = "requests.storage"
    REQUESTS_EXPORT = "requests.export"
    REQUESTS_TRAINING = "requests.training"
    SERVICES_MANAGE = "services.manage"
    QUOTATIONS_MANAGE = "quotations.manage"
    EXPORT_MANAGE = "export.manage"
    EXPORT_APPROVE = "export.approve"
    TRAINING_MANAGE = "training.manage"
    TRAINING_APPROVE = "training.approve"
    TRAINING_INSTRUCT = "training.instruct"
    SUPPORT_MANAGE = "support.manage"
    SUPPORT_APPROVE = "support.approve"
    CUSTOMERS_VIEW = "customers.view"
    # Phase 11 — analytics, business intelligence and reporting.
    ANALYTICS_VIEW = "analytics.view"
    ANALYTICS_FINANCE = "analytics.finance"
    REPORTS_BUILD = "reports.build"
    REPORTS_SCHEDULE = "reports.schedule"
    REPORTS_MANAGE = "reports.manage"


ALL_CAPABILITIES: frozenset[str] = frozenset(
    value for name, value in vars(Capability).items() if not name.startswith("_")
)

# Role -> capabilities. This is the authoritative permission matrix for
# role-based menus and server-side capability checks.
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    UserRole.CUSTOMER: frozenset(),
    UserRole.SALES_OFFICER: frozenset(
        {
            Capability.CATALOG_MANAGE,
            Capability.ORDERS_MANAGE,
            Capability.REQUESTS_MARKETING,
            Capability.CONTACT_MANAGE,
            Capability.SERVICES_MANAGE,
            Capability.QUOTATIONS_MANAGE,
            Capability.SUPPORT_MANAGE,
            Capability.CUSTOMERS_VIEW,
            Capability.ANALYTICS_VIEW,
            Capability.REPORTS_BUILD,
        }
    ),
    UserRole.INVENTORY_OFFICER: frozenset(
        {
            Capability.CATALOG_MANAGE,
            Capability.INVENTORY_MANAGE,
            Capability.ORDERS_MANAGE,
            Capability.REQUESTS_FARMING,
            Capability.REQUESTS_STORAGE,
            Capability.SERVICES_MANAGE,
            Capability.ANALYTICS_VIEW,
            Capability.REPORTS_BUILD,
        }
    ),
    UserRole.CONSULTANT: frozenset(
        {Capability.REQUESTS_CONSULTANCY, Capability.SERVICES_MANAGE, Capability.ANALYTICS_VIEW}
    ),
    UserRole.TRAINING_MANAGER: frozenset(
        {
            Capability.REQUESTS_TRAINING,
            Capability.CONTENT_MANAGE,
            Capability.SERVICES_MANAGE,
            Capability.TRAINING_MANAGE,
            Capability.TRAINING_INSTRUCT,
            Capability.ANALYTICS_VIEW,
            Capability.REPORTS_BUILD,
        }
    ),
    UserRole.EXPORT_OFFICER: frozenset(
        {
            Capability.REQUESTS_EXPORT,
            Capability.SERVICES_MANAGE,
            Capability.EXPORT_MANAGE,
            Capability.ANALYTICS_VIEW,
            Capability.REPORTS_BUILD,
        }
    ),
    UserRole.FINANCE_OFFICER: frozenset(
        {
            Capability.FINANCE_MANAGE,
            Capability.ORDERS_MANAGE,
            Capability.AUDIT_VIEW,
            Capability.SERVICES_MANAGE,
            Capability.QUOTATIONS_MANAGE,
            Capability.CUSTOMERS_VIEW,
            Capability.ANALYTICS_VIEW,
            Capability.ANALYTICS_FINANCE,
            Capability.REPORTS_BUILD,
            Capability.REPORTS_SCHEDULE,
            Capability.REPORTS_MANAGE,
        }
    ),
    UserRole.CONTENT_EDITOR: frozenset(
        {
            Capability.CONTENT_VIEW,
            Capability.CONTENT_MANAGE,
            Capability.CONTENT_PUBLISH,
            Capability.MEDIA_MANAGE,
            Capability.TESTIMONIALS_APPROVE,
            Capability.CONTACT_MANAGE,
            Capability.NAV_MANAGE,
        }
    ),
    UserRole.ADMINISTRATOR: ALL_CAPABILITIES,
    UserRole.OWNER: ALL_CAPABILITIES,
}

# Django model permissions granted to each role's group. Custom permissions are
# declared on ``User.Meta.permissions``; ``view_auditlog`` is auto-generated by
# the AuditLog model.
ROLE_DJANGO_PERMISSIONS: dict[str, tuple[str, ...]] = {
    UserRole.FINANCE_OFFICER: ("dashboard.view_auditlog",),
    UserRole.ADMINISTRATOR: (
        "accounts.view_staff",
        "accounts.add_staff",
        "accounts.change_staff",
        "accounts.deactivate_staff",
        "accounts.assign_roles",
        "dashboard.view_auditlog",
    ),
    UserRole.OWNER: (
        "accounts.view_staff",
        "accounts.add_staff",
        "accounts.change_staff",
        "accounts.deactivate_staff",
        "accounts.assign_roles",
        "dashboard.view_auditlog",
    ),
}


def role_group_name(role: str) -> str:
    return f"{ROLE_GROUP_PREFIX}{role}"


def sync_role_groups() -> dict[str, Group]:
    """Create/refresh a Django group per role and assign its permissions.

    Idempotent; safe to run on every deploy.
    """
    groups: dict[str, Group] = {}
    for role in UserRole.values:
        group, _ = Group.objects.get_or_create(name=role_group_name(role))
        wanted = ROLE_DJANGO_PERMISSIONS.get(role, ())
        permissions = []
        for label in wanted:
            app_label, codename = label.split(".", 1)
            try:
                permissions.append(
                    Permission.objects.get(content_type__app_label=app_label, codename=codename)
                )
            except Permission.DoesNotExist:
                # Permission not migrated yet (e.g. during initial migration).
                continue
        group.permissions.set(permissions)
        groups[role] = group
    return groups


def sync_user_groups(user) -> None:
    """Make the user's groups exactly match their ``role`` (plus nothing else)."""
    group = Group.objects.filter(name=role_group_name(user.role)).first()
    if group is None:
        group = sync_role_groups().get(user.role)
    if group is not None:
        user.groups.set([group])

"""Read-only queries for accounts and staff (thin ``selectors`` layer)."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from .models import User, UserRole


def staff_directory(*, query: str = "", role: str = "", status: str = "") -> QuerySet[User]:
    """Return staff accounts, optionally filtered by search text, role or status."""
    queryset = User.objects.filter(is_staff=True).select_related("state").order_by("-date_joined")
    query = (query or "").strip()
    if query:
        queryset = queryset.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone__icontains=query)
        )
    if role:
        queryset = queryset.filter(role=role)
    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "inactive":
        queryset = queryset.filter(is_active=False)
    return queryset


def customers() -> QuerySet[User]:
    return User.objects.filter(role=UserRole.CUSTOMER).order_by("-date_joined")


def account_counts() -> dict[str, int]:
    """Real, non-fabricated counts for the dashboard metric cards."""
    return {
        "customers_total": User.objects.filter(role=UserRole.CUSTOMER).count(),
        "customers_verified": User.objects.filter(
            role=UserRole.CUSTOMER, is_email_verified=True
        ).count(),
        "staff_total": User.objects.filter(is_staff=True).count(),
        "staff_active": User.objects.filter(is_staff=True, is_active=True).count(),
    }

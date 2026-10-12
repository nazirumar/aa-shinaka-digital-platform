"""Read-only queries for the staff dashboard."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from .models import AuditLog


def recent_activity(*, limit: int = 10) -> QuerySet[AuditLog]:
    return AuditLog.objects.select_related("actor")[:limit]


def activity_for(user, *, limit: int = 20) -> QuerySet[AuditLog]:
    """Audit entries where ``user`` was the actor or the target."""
    return (
        AuditLog.objects.filter(
            Q(actor=user) | Q(target_type="accounts.User", target_id=str(user.pk))
        )
        .select_related("actor")
        .order_by("-created_at")[:limit]
    )


def audit_search(*, query: str = "", action: str = "") -> QuerySet[AuditLog]:
    queryset = AuditLog.objects.select_related("actor")
    query = (query or "").strip()
    if query:
        queryset = queryset.filter(
            Q(action__icontains=query)
            | Q(target_id__icontains=query)
            | Q(note__icontains=query)
            | Q(actor__email__icontains=query)
        )
    if action:
        queryset = queryset.filter(action=action)
    return queryset

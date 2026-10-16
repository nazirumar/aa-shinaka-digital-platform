"""Read-only support querysets (ownership-scoped for customers, filtered for staff)."""

from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from .models import (
    SupportCategory,
    SupportMessage,
    SupportPriority,
    SupportStatus,
    SupportTicket,
)

OPEN_STATUSES = (
    SupportStatus.OPEN,
    SupportStatus.ASSIGNED,
    SupportStatus.IN_PROGRESS,
    SupportStatus.WAITING_FOR_CUSTOMER,
    SupportStatus.REOPENED,
)


# ---------------------------------------------------------------------------
# Customer scope
# ---------------------------------------------------------------------------
def tickets_for(user) -> QuerySet:
    return (
        SupportTicket.objects.filter(customer=user)
        .select_related("assigned_to")
        .order_by("-last_activity_at")
    )


def ticket_for(user, reference: str) -> SupportTicket | None:
    return (
        SupportTicket.objects.filter(customer=user, reference=reference)
        .select_related("assigned_to", "customer")
        .first()
    )


def messages_for(ticket, *, include_internal: bool = False) -> QuerySet:
    queryset = (
        SupportMessage.objects.filter(ticket=ticket)
        .select_related("sender")
        .prefetch_related("attachments")
    )
    if not include_internal:
        queryset = queryset.filter(is_internal=False)
    return queryset.order_by("created_at")


def customer_open_count(user) -> int:
    return SupportTicket.objects.filter(customer=user, status__in=OPEN_STATUSES).count()


# ---------------------------------------------------------------------------
# Staff scope
# ---------------------------------------------------------------------------
def staff_tickets(
    *,
    status: str = "",
    priority: str = "",
    category: str = "",
    assignee: str = "",
    query: str = "",
) -> QuerySet:
    queryset = SupportTicket.objects.select_related("customer", "assigned_to")
    if status:
        queryset = queryset.filter(status=status)
    if priority:
        queryset = queryset.filter(priority=priority)
    if category:
        queryset = queryset.filter(category=category)
    if assignee == "unassigned":
        queryset = queryset.filter(assigned_to__isnull=True)
    elif assignee:
        queryset = queryset.filter(assigned_to_id=assignee)
    if query:
        queryset = queryset.filter(
            Q(reference__icontains=query)
            | Q(subject__icontains=query)
            | Q(customer__email__icontains=query)
        )
    return queryset.order_by("-last_activity_at")


def ticket_by_reference(reference: str) -> SupportTicket | None:
    return (
        SupportTicket.objects.filter(reference=reference)
        .select_related("customer", "assigned_to")
        .first()
    )


def ticket_counts() -> dict:
    counts = dict(SupportTicket.objects.values_list("status").annotate(total=Count("id")))
    return {status.value: counts.get(status.value, 0) for status in SupportStatus}


def support_metrics() -> dict:
    status_counts = ticket_counts()
    category_counts = {
        row["category"]: row["total"]
        for row in SupportTicket.objects.values("category").annotate(total=Count("id"))
    }
    priority_counts = {
        row["priority"]: row["total"]
        for row in SupportTicket.objects.values("priority").annotate(total=Count("id"))
    }
    open_total = sum(status_counts.get(status.value, 0) for status in OPEN_STATUSES)
    return {
        "by_status": [
            {"value": s.value, "label": s.label, "count": status_counts.get(s.value, 0)}
            for s in SupportStatus
        ],
        "by_priority": [
            {"value": p.value, "label": p.label, "count": priority_counts.get(p.value, 0)}
            for p in SupportPriority
        ],
        "by_category": [
            {"value": c.value, "label": c.label, "count": category_counts.get(c.value, 0)}
            for c in SupportCategory
        ],
        "resolved_total": status_counts.get(SupportStatus.RESOLVED.value, 0),
        "closed_total": status_counts.get(SupportStatus.CLOSED.value, 0),
        "open_total": open_total,
        "unassigned_total": SupportTicket.objects.filter(
            assigned_to__isnull=True, status__in=OPEN_STATUSES
        ).count(),
        "total": SupportTicket.objects.count(),
        "categories": SupportCategory.choices,
        "priorities": SupportPriority.choices,
        "statuses": SupportStatus.choices,
    }


__all__ = [
    "OPEN_STATUSES",
    "customer_open_count",
    "messages_for",
    "staff_tickets",
    "support_metrics",
    "ticket_by_reference",
    "ticket_counts",
    "ticket_for",
    "tickets_for",
]

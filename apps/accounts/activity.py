"""Customer activity timeline (Phase 10, Task 14).

Merges the customer's most recent events across every domain into one
reverse-chronological feed. Only records owned by the authenticated customer
are ever included — there is no cross-customer leakage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.urls import reverse


@dataclass
class ActivityEntry:
    timestamp: datetime
    category: str
    title: str
    description: str
    url: str | None


def _display(obj, field: str) -> str:
    getter = getattr(obj, f"get_{field}_display", None)
    return getter() if getter else ""


def activity_feed(customer, limit: int = 30) -> list[ActivityEntry]:
    entries: list[ActivityEntry] = []
    entries.extend(_order_entries(customer, limit))
    entries.extend(_payment_entries(customer, limit))
    entries.extend(_service_entries(customer, limit))
    entries.extend(_export_entries(customer, limit))
    entries.extend(_training_entries(customer, limit))
    entries.extend(_support_entries(customer, limit))
    entries.extend(_notification_entries(customer, limit))
    entries.sort(key=lambda entry: entry.timestamp, reverse=True)
    return entries[:limit]


def _order_entries(customer, limit: int) -> list[ActivityEntry]:
    from apps.orders.models import Order

    return [
        ActivityEntry(
            timestamp=order.created_at,
            category="Orders",
            title=f"Order {order.number}",
            description=_display(order, "status"),
            url=reverse("orders:order_detail", args=[order.number]),
        )
        for order in Order.objects.filter(user=customer).order_by("-created_at")[:limit]
    ]


def _payment_entries(customer, limit: int) -> list[ActivityEntry]:
    from apps.orders.payment_models import Payment

    return [
        ActivityEntry(
            timestamp=payment.created_at,
            category="Payments",
            title=f"Payment {payment.reference}",
            description=_display(payment, "state") or _display(payment, "status"),
            url=reverse("orders:payment_detail", args=[payment.pk]),
        )
        for payment in Payment.objects.filter(customer=customer).order_by("-created_at")[:limit]
    ]


def _service_entries(customer, limit: int) -> list[ActivityEntry]:
    from apps.services.models import ServiceRequest

    return [
        ActivityEntry(
            timestamp=request.created_at,
            category="Services",
            title=request.title,
            description=f"{request.reference} · {request.get_service_type_display()}",
            url=reverse("services:request_detail", args=[request.reference]),
        )
        for request in ServiceRequest.objects.filter(customer=customer).order_by("-created_at")[
            :limit
        ]
    ]


def _export_entries(customer, limit: int) -> list[ActivityEntry]:
    from apps.export.models import ExportEnquiry

    return [
        ActivityEntry(
            timestamp=enquiry.created_at,
            category="Export",
            title=f"Export enquiry {enquiry.reference}",
            description=_display(enquiry, "status"),
            url=reverse("export:enquiry_detail", args=[enquiry.reference]),
        )
        for enquiry in ExportEnquiry.objects.filter(customer=customer).order_by("-created_at")[
            :limit
        ]
    ]


def _training_entries(customer, limit: int) -> list[ActivityEntry]:
    from apps.training.models import Enrollment

    return [
        ActivityEntry(
            timestamp=enrollment.created_at,
            category="Training",
            title=f"Enrolment {enrollment.reference}",
            description=_display(enrollment, "status"),
            url=reverse("training_account:enrollment_detail", args=[enrollment.reference]),
        )
        for enrollment in Enrollment.objects.filter(student=customer).order_by("-created_at")[
            :limit
        ]
    ]


def _support_entries(customer, limit: int) -> list[ActivityEntry]:
    from apps.support.models import SupportTicket

    return [
        ActivityEntry(
            timestamp=ticket.last_activity_at or ticket.created_at,
            category="Support",
            title=f"Support ticket {ticket.reference}",
            description=ticket.subject,
            url=reverse("support:ticket_detail", args=[ticket.reference]),
        )
        for ticket in SupportTicket.objects.filter(customer=customer).order_by("-last_activity_at")[
            :limit
        ]
    ]


def _notification_entries(customer, limit: int) -> list[ActivityEntry]:
    from apps.notifications.models import Notification

    return [
        ActivityEntry(
            timestamp=notification.created_at,
            category="Notifications",
            title=notification.title,
            description=notification.message,
            url=reverse("notifications:open", args=[notification.pk]),
        )
        for notification in Notification.objects.filter(recipient=customer).order_by("-created_at")[
            :limit
        ]
    ]

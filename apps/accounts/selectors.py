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


def customer_directory(*, query: str = "", status: str = "") -> QuerySet[User]:
    """Customer accounts for the staff customer-overview list (Phase 10)."""
    queryset = (
        User.objects.filter(role=UserRole.CUSTOMER).select_related("state").order_by("-date_joined")
    )
    query = (query or "").strip()
    if query:
        queryset = queryset.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone__icontains=query)
        )
    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "inactive":
        queryset = queryset.filter(is_active=False)
    return queryset


def customer_overview(customer) -> dict:
    """Real aggregates about one customer, across every domain (Phase 10)."""
    from apps.export.models import ExportEnquiry, ExportOrder
    from apps.notifications.models import Notification
    from apps.orders.models import Order
    from apps.orders.payment_models import Payment, PaymentState
    from apps.services.models import ServiceRequest
    from apps.support.models import SupportStatus, SupportTicket
    from apps.training.models import Enrollment

    from .documents import document_count

    return {
        "orders_total": Order.objects.filter(user=customer).count(),
        "orders_recent": list(Order.objects.filter(user=customer).order_by("-created_at")[:5]),
        "service_requests_total": ServiceRequest.objects.filter(customer=customer).count(),
        "service_requests_recent": list(
            ServiceRequest.objects.filter(customer=customer).order_by("-created_at")[:5]
        ),
        "export_enquiries_total": ExportEnquiry.objects.filter(customer=customer).count(),
        "export_orders_total": ExportOrder.objects.filter(customer=customer).count(),
        "enrollments_total": Enrollment.objects.filter(student=customer).count(),
        "documents_total": document_count(customer),
        "tickets_open": SupportTicket.objects.filter(customer=customer)
        .exclude(status__in=[SupportStatus.RESOLVED, SupportStatus.CLOSED])
        .count(),
        "tickets_recent": list(
            SupportTicket.objects.filter(customer=customer).order_by("-last_activity_at")[:5]
        ),
        "notifications_unread": Notification.objects.filter(
            recipient=customer, is_read=False
        ).count(),
        # Financial section — only rendered for staff who may see finance data.
        "payments_total": Payment.objects.filter(customer=customer).count(),
        "payments_verified_total": Payment.objects.filter(
            customer=customer, status=PaymentState.PAID
        ).count(),
        "payments_recent": list(
            Payment.objects.filter(customer=customer).order_by("-created_at")[:5]
        ),
    }

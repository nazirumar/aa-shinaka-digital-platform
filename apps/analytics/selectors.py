"""Read-only analytics aggregations (Phase 11).

Everything here is derived from the authoritative domain models; nothing is
fabricated and analytics never writes to a business table. Money is always
returned as ``Decimal`` and is **never** summed across currencies — callers get
per-currency rows and decide how to present them.

Database aggregates do the heavy lifting; Python loops are used only where the
business rule (e.g. first-response time) cannot be expressed cleanly in the ORM.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.catalog.models import (
    ListingStatus,
    ProductListing,
    StockBalance,
    StockMovement,
    Warehouse,
)
from apps.export.models import (
    ExportEnquiry,
    ExportEnquiryStatus,
    ExportOrder,
    ExportOrderItem,
    ExportOrderStatus,
    ExportQuotation,
    ExportQuotationStatus,
    ExportShipment,
    ShipmentStatus,
)
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.orders.payment_models import (
    Invoice,
    InvoiceState,
    Payment,
    PaymentState,
    Refund,
    RefundState,
)
from apps.services.models import (
    AppointmentStatus,
    ConsultationAppointment,
    FarmProject,
    MarketingEnquiry,
    MarketingProposal,
    MarketingProposalStatus,
    ServiceQuotation,
    ServiceRequest,
    ServiceRequestStatus,
    ServiceType,
    StorageBooking,
    StorageBookingStatus,
    StorageCapacityAllocation,
    StorageFacility,
)
from apps.services.models import (
    QuotationStatus as ServiceQuotationStatus,
)
from apps.support.models import SupportMessage, SupportStatus, SupportTicket
from apps.training.models import (
    CONFIRMED_ENROLLMENT_STATUSES,
    AttendanceRecord,
    AttendanceStatus,
    Enrollment,
    EnrollmentStatus,
)

ZERO = Decimal("0.00")

#: Payment states that represent captured (verified) money.
SETTLED_PAYMENT_STATES = (
    PaymentState.PAID,
    PaymentState.REFUNDED,
    PaymentState.PARTIALLY_REFUNDED,
)

#: Order states that are not counted as placed sales.
NON_SALES_ORDER_STATES = (OrderStatus.CANCELLED, OrderStatus.EXPIRED)

OPEN_SUPPORT_STATUSES = (
    SupportStatus.OPEN,
    SupportStatus.ASSIGNED,
    SupportStatus.IN_PROGRESS,
    SupportStatus.WAITING_FOR_CUSTOMER,
    SupportStatus.REOPENED,
)

OPEN_EXPORT_ENQUIRY_STATES = (
    ExportEnquiryStatus.SUBMITTED,
    ExportEnquiryStatus.UNDER_REVIEW,
    ExportEnquiryStatus.REQUIREMENTS_REQUESTED,
    ExportEnquiryStatus.QUOTED,
)

EXPORT_ACTIVE_ORDER_STATES = tuple(
    s
    for s in ExportOrderStatus.values
    if s not in (ExportOrderStatus.COMPLETED, ExportOrderStatus.CANCELLED)
)

EXPORT_SHIPPED_STATES = (
    ShipmentStatus.DISPATCHED,
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.CUSTOMS_PROCESSING,
    ShipmentStatus.DELIVERED,
)

FULFILLED_ORDER_STATES = (OrderStatus.DELIVERED, OrderStatus.COMPLETED)


def base_currency() -> str:
    return getattr(settings, "ANALYTICS_BASE_CURRENCY", "NGN")


def _money(value) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(value).quantize(Decimal("0.01"))


def _percent(numerator, denominator) -> Decimal:
    numerator = Decimal(numerator or 0)
    denominator = Decimal(denominator or 0)
    if not denominator:
        return Decimal("0.00")
    return (numerator / denominator * Decimal("100")).quantize(Decimal("0.01"))


def format_duration(seconds) -> str:
    """Human-readable duration from seconds (never invents precision)."""
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, _sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else f"{seconds}s"


# ---------------------------------------------------------------------------
# Financial — verified receipts, refunds, invoices
# ---------------------------------------------------------------------------


def settled_payments(filters=None):
    queryset = Payment.objects.filter(status__in=SETTLED_PAYMENT_STATES)
    if filters is not None:
        queryset = filters.contains("verified_at", queryset)
    return queryset


def verified_receipts(*, filters=None, currency: str | None = None) -> Decimal:
    """Gross verified receipts in a single currency (base currency by default)."""
    currency = currency or base_currency()
    total = (
        settled_payments(filters).filter(currency=currency).aggregate(t=Sum("verified_amount"))["t"]
    )
    return _money(total)


def receipts_by_currency(*, filters=None) -> list[dict]:
    rows = (
        settled_payments(filters)
        .values("currency")
        .annotate(total=Sum("verified_amount"))
        .order_by("currency")
    )
    return [{"currency": row["currency"], "total": _money(row["total"])} for row in rows]


def receipts_by_division(*, filters=None, currency: str | None = None) -> dict:
    """Verified receipts split by the single business record each payment settles."""
    currency = currency or base_currency()
    qs = settled_payments(filters).filter(currency=currency)

    def _total(**target):
        return _money(qs.filter(**target).aggregate(t=Sum("verified_amount"))["t"])

    return {
        "currency": currency,
        "products": _total(order__isnull=False),
        "services": _total(service_quotation__isnull=False),
        "export": _total(export_order__isnull=False),
        "training": _total(training_enrollment__isnull=False),
    }


def receipts_by_method(*, filters=None) -> list[dict]:
    rows = (
        settled_payments(filters)
        .values("method")
        .annotate(total=Sum("verified_amount"), count=Count("id"))
        .order_by("-total")
    )
    return [
        {
            "method": row["method"] or "unspecified",
            "total": _money(row["total"]),
            "count": row["count"],
        }
        for row in rows
    ]


def receipts_by_day(*, filters=None, currency: str | None = None) -> list[dict]:
    currency = currency or base_currency()
    queryset = settled_payments(filters).filter(currency=currency, verified_at__isnull=False)
    rows = (
        queryset.annotate(day=TruncDate("verified_at"))
        .values("day")
        .annotate(total=Sum("verified_amount"))
        .order_by("day")
    )
    return [{"day": row["day"], "total": _money(row["total"])} for row in rows if row["day"]]


def confirmed_refunds(*, filters=None, currency: str | None = None) -> Decimal:
    queryset = Refund.objects.filter(status=RefundState.COMPLETED)
    if currency:
        queryset = queryset.filter(payment__currency=currency)
    if filters is not None:
        if filters.start():
            queryset = queryset.filter(processed_at__gte=filters.start())
        if filters.end():
            queryset = queryset.filter(processed_at__lt=filters.end())
    return _money(queryset.aggregate(t=Sum("amount"))["t"])


def refunds_by_status() -> list[dict]:
    rows = Refund.objects.values("status").annotate(count=Count("id")).order_by("status")
    return [{"status": row["status"], "count": row["count"]} for row in rows]


def pending_payments_count() -> int:
    return Payment.objects.filter(
        status__in=[PaymentState.PENDING, PaymentState.PROCESSING]
    ).count()


def outstanding_invoice_balance(*, filters=None) -> list[dict]:
    queryset = Invoice.objects.filter(status__in=[InvoiceState.UNPAID, InvoiceState.PARTIALLY_PAID])
    if filters is not None:
        queryset = filters.contains("created_at", queryset)
    rows = (
        queryset.values("currency")
        .annotate(total=Sum("total"), count=Count("id"))
        .order_by("currency")
    )
    return [
        {"currency": row["currency"], "total": _money(row["total"]), "count": row["count"]}
        for row in rows
    ]


def total_outstanding_invoice_balance() -> Decimal:
    return _money(
        Invoice.objects.filter(
            status__in=[InvoiceState.UNPAID, InvoiceState.PARTIALLY_PAID]
        ).aggregate(t=Sum("total"))["t"]
    )


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


def counted_orders(filters=None):
    """Placed orders that count as sales (excludes cancelled/expired)."""
    queryset = Order.objects.exclude(status__in=NON_SALES_ORDER_STATES)
    if filters is not None:
        queryset = filters.contains("created_at", queryset)
        if filters.status:
            queryset = queryset.filter(status=filters.status)
        if filters.currency:
            queryset = queryset.filter(currency=filters.currency)
        if filters.state_id:
            queryset = queryset.filter(delivery_state_id=filters.state_id)
        if filters.lga_id:
            queryset = queryset.filter(delivery_lga_id=filters.lga_id)
    return queryset


def count_filtered(queryset, filters, field="created_at"):
    return filters.contains(field, queryset) if filters is not None else queryset


def sales_overview(*, filters=None) -> dict:
    base = counted_orders(filters)
    by_currency = []
    for row in (
        base.values("currency")
        .annotate(total=Sum("grand_total"), count=Count("id"))
        .order_by("currency")
    ):
        count = row["count"]
        by_currency.append(
            {
                "currency": row["currency"],
                "total": _money(row["total"]),
                "count": count,
                "average": _money(Decimal(row["total"] or 0) / count) if count else ZERO,
            }
        )
    repeat = base.values("user_id").annotate(c=Count("id")).filter(c__gt=1).count()
    return {
        "order_count": base.count(),
        "fulfilled_count": base.filter(status__in=FULFILLED_ORDER_STATES).count(),
        "open_count": base.exclude(
            status__in=(*NON_SALES_ORDER_STATES, *FULFILLED_ORDER_STATES)
        ).count(),
        "by_currency": by_currency,
        "repeat_customers": repeat,
        "status_distribution": [
            {"status": row["status"], "count": row["count"]}
            for row in base.values("status").annotate(count=Count("id")).order_by("status")
        ],
    }


def sales_trend(*, filters=None, currency: str | None = None) -> list[dict]:
    currency = currency or base_currency()
    queryset = counted_orders(filters).filter(currency=currency)
    rows = (
        queryset.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(orders=Count("id"), value=Sum("grand_total"))
        .order_by("day")
    )
    return [
        {"day": row["day"], "orders": row["orders"], "value": _money(row["value"])}
        for row in rows
        if row["day"]
    ]


def _order_items(filters):
    return OrderItem.objects.filter(order__in=counted_orders(filters))


def top_products(*, filters=None, limit: int = 10) -> list[dict]:
    rows = (
        _order_items(filters)
        .values("product_name")
        .annotate(
            quantity=Sum("quantity"), value=Sum("line_total"), orders=Count("order", distinct=True)
        )
        .order_by("-value")[:limit]
    )
    return [
        {
            "product_name": row["product_name"],
            "quantity": row["quantity"],
            "value": _money(row["value"]),
            "orders": row["orders"],
        }
        for row in rows
    ]


def top_categories(*, filters=None, limit: int = 10) -> list[dict]:
    rows = (
        _order_items(filters)
        .values("listing__product__category__name")
        .annotate(quantity=Sum("quantity"), value=Sum("line_total"))
        .order_by("-value")[:limit]
    )
    return [
        {
            "category": row["listing__product__category__name"] or "Uncategorised",
            "quantity": row["quantity"],
            "value": _money(row["value"]),
        }
        for row in rows
    ]


def sales_by_origin_state(*, filters=None, limit: int = 20) -> list[dict]:
    rows = (
        _order_items(filters)
        .exclude(origin_state="")
        .values("origin_state")
        .annotate(value=Sum("line_total"), quantity=Sum("quantity"))
        .order_by("-value")[:limit]
    )
    return [
        {"state": row["origin_state"], "value": _money(row["value"]), "quantity": row["quantity"]}
        for row in rows
    ]


def sales_by_origin_lga(*, filters=None, limit: int = 20) -> list[dict]:
    rows = (
        _order_items(filters)
        .exclude(origin_lga="")
        .values("origin_lga")
        .annotate(value=Sum("line_total"), quantity=Sum("quantity"))
        .order_by("-value")[:limit]
    )
    return [
        {"lga": row["origin_lga"], "value": _money(row["value"]), "quantity": row["quantity"]}
        for row in rows
    ]


def sales_by_delivery_state(*, filters=None, limit: int = 20) -> list[dict]:
    rows = (
        counted_orders(filters)
        .values("delivery_state__name")
        .annotate(orders=Count("id"), value=Sum("grand_total"))
        .order_by("-orders")[:limit]
    )
    return [
        {
            "state": row["delivery_state__name"] or "Unspecified",
            "orders": row["orders"],
            "value": _money(row["value"]),
        }
        for row in rows
    ]


def order_status_distribution(*, filters=None) -> list[dict]:
    return [
        {"status": row["status"], "count": row["count"]}
        for row in count_filtered(Order.objects.all(), filters)
        .values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    ]


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def stock_summary() -> dict:
    row = StockBalance.objects.aggregate(
        on_hand=Sum("on_hand"), reserved=Sum("reserved"), count=Count("id")
    )
    on_hand = row["on_hand"] or Decimal("0.000")
    reserved = row["reserved"] or Decimal("0.000")
    return {
        "on_hand": on_hand,
        "reserved": reserved,
        "available": on_hand - reserved,
        "balance_count": row["count"] or 0,
        "warehouse_count": Warehouse.objects.filter(is_active=True).count(),
        "listing_count": ProductListing.objects.filter(
            status__in=[ListingStatus.ACTIVE, ListingStatus.OUT_OF_STOCK]
        ).count(),
    }


def stock_by_warehouse(*, limit: int = 20) -> list[dict]:
    rows = (
        StockBalance.objects.values("warehouse__name", "listing__package_unit__name")
        .annotate(on_hand=Sum("on_hand"), reserved=Sum("reserved"))
        .order_by("warehouse__name")[:limit]
    )
    return [
        {
            "warehouse": row["warehouse__name"],
            "unit": row["listing__package_unit__name"] or "—",
            "on_hand": row["on_hand"],
            "reserved": row["reserved"],
            "available": (row["on_hand"] or 0) - (row["reserved"] or 0),
        }
        for row in rows
    ]


def stock_by_product(*, filters=None, limit: int = 25) -> list[dict]:
    queryset = StockBalance.objects.all()
    if filters is not None and filters.warehouse_id:
        queryset = queryset.filter(warehouse_id=filters.warehouse_id)
    if filters is not None and filters.product_id:
        queryset = queryset.filter(listing__product_id=filters.product_id)
    rows = (
        queryset.values("listing__product__name", "listing__package_unit__name")
        .annotate(on_hand=Sum("on_hand"), reserved=Sum("reserved"))
        .order_by("-on_hand")[:limit]
    )
    return [
        {
            "product": row["listing__product__name"],
            "unit": row["listing__package_unit__name"] or "—",
            "on_hand": row["on_hand"],
            "reserved": row["reserved"],
            "available": (row["on_hand"] or 0) - (row["reserved"] or 0),
        }
        for row in rows
    ]


def low_stock_listings(*, limit: int = 25) -> list[dict]:
    from apps.catalog.selectors import low_stock_listings as _low

    out = []
    for listing in _low().select_related("product", "state", "package_unit")[:limit]:
        out.append(
            {
                "listing": listing,
                "product": listing.product.name,
                "state": listing.state.name if listing.state_id else "",
                "unit": listing.package_unit.name if listing.package_unit_id else "",
                "available": listing.available_stock,
                "threshold": listing.low_stock_threshold,
            }
        )
    return out


def movements_by_kind(*, filters=None) -> list[dict]:
    return [
        {"kind": row["kind"], "count": row["count"]}
        for row in count_filtered(StockMovement.objects.all(), filters)
        .values("kind")
        .annotate(count=Count("id"))
        .order_by("kind")
    ]


def movements_trend(*, filters=None) -> list[dict]:
    rows = (
        count_filtered(StockMovement.objects.all(), filters)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    return [{"day": row["day"], "count": row["count"]} for row in rows if row["day"]]


def listings_by_origin_state(*, limit: int = 20) -> list[dict]:
    rows = (
        ProductListing.objects.filter(status=ListingStatus.ACTIVE)
        .values("state__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:limit]
    )
    return [{"state": row["state__name"], "count": row["count"]} for row in rows]


# ---------------------------------------------------------------------------
# Agricultural services
# ---------------------------------------------------------------------------


def services_metrics(*, filters=None) -> dict:
    requests = count_filtered(ServiceRequest.objects.all(), filters)
    if filters is not None:
        if filters.status:
            requests = requests.filter(status=filters.status)
        if filters.division:
            requests = requests.filter(service_type=filters.division)

    appointments = count_filtered(ConsultationAppointment.objects.all(), filters)
    issued = ServiceQuotation.objects.filter(
        status__in=[ServiceQuotationStatus.ISSUED, ServiceQuotationStatus.ACCEPTED]
    )
    accepted = ServiceQuotation.objects.filter(status=ServiceQuotationStatus.ACCEPTED)
    return {
        "total_requests": requests.count(),
        "open_requests": requests.exclude(
            status__in=[
                ServiceRequestStatus.COMPLETED,
                ServiceRequestStatus.REJECTED,
                ServiceRequestStatus.CANCELLED,
            ]
        ).count(),
        "by_division": list(
            requests.values("service_type").annotate(count=Count("id")).order_by("service_type")
        ),
        "consultancy_requests": requests.filter(service_type=ServiceType.CONSULTANCY).count(),
        "confirmed_appointments": appointments.filter(
            status__in=[AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED]
        ).count(),
        "completed_consultations": appointments.filter(status=AppointmentStatus.COMPLETED).count(),
        "farm_projects_by_status": list(
            FarmProject.objects.values("status").annotate(count=Count("id")).order_by("status")
        ),
        "farm_milestones_total": sum(
            project.milestones.count()
            for project in FarmProject.objects.prefetch_related("milestones")
        ),
        "marketing_enquiries": MarketingEnquiry.objects.count(),
        "marketing_proposals_issued": MarketingProposal.objects.filter(
            status__in=[MarketingProposalStatus.ISSUED, MarketingProposalStatus.ACCEPTED]
        ).count(),
        "storage_bookings_active": StorageBooking.objects.filter(
            status__in=[StorageBookingStatus.CONFIRMED, StorageBookingStatus.CHECKED_IN]
        ).count(),
        "storage_utilization": storage_utilization(),
        "quotations_issued": issued.count(),
        "quotations_accepted": accepted.count(),
        "quotation_acceptance_rate": _percent(accepted.count(), issued.count()),
    }


def storage_utilization() -> list[dict]:
    today = timezone.localdate()
    out = []
    for facility in StorageFacility.objects.all():
        allocated = (
            StorageCapacityAllocation.objects.filter(
                facility=facility,
                released_at__isnull=True,
                start_date__lte=today,
                end_date__gt=today,
            ).aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )
        capacity = facility.capacity or ZERO
        out.append(
            {
                "facility": facility.name,
                "unit": facility.get_capacity_unit_display(),
                "allocated": allocated,
                "capacity": capacity,
                "percent": _percent(allocated, capacity),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_metrics(*, filters=None) -> dict:
    enquiries = count_filtered(ExportEnquiry.objects.all(), filters)
    if filters is not None:
        if filters.destination_id:
            enquiries = enquiries.filter(destination_id=filters.destination_id)
        if filters.status:
            enquiries = enquiries.filter(status=filters.status)
    quotations = count_filtered(ExportQuotation.objects.all(), filters)
    if filters is not None and filters.destination_id:
        quotations = quotations.filter(destination_id=filters.destination_id)
    orders = count_filtered(ExportOrder.objects.all(), filters)
    if filters is not None and filters.destination_id:
        orders = orders.filter(destination_id=filters.destination_id)
    shipments = count_filtered(ExportShipment.objects.all(), filters)
    return {
        "enquiries_total": enquiries.count(),
        "open_enquiries": enquiries.filter(status__in=OPEN_EXPORT_ENQUIRY_STATES).count(),
        "enquiries_by_destination": list(
            enquiries.values("destination__country__name", "destination__country_code")
            .annotate(count=Count("id"))
            .order_by("-count")
        ),
        "quotations_issued": quotations.filter(
            status__in=[ExportQuotationStatus.ISSUED, ExportQuotationStatus.ACCEPTED]
        ).count(),
        "quotations_accepted": quotations.filter(status=ExportQuotationStatus.ACCEPTED).count(),
        "orders_total": orders.count(),
        "orders_active": orders.filter(status__in=EXPORT_ACTIVE_ORDER_STATES).count(),
        "shipments_dispatched": shipments.filter(status__in=EXPORT_SHIPPED_STATES).count(),
        "shipments_delivered": shipments.filter(status=ShipmentStatus.DELIVERED).count(),
        "compliance_by_status": list(
            orders.values("compliance_status")
            .annotate(count=Count("id"))
            .order_by("compliance_status")
        ),
        "orders_by_status": list(
            orders.values("status").annotate(count=Count("id")).order_by("status")
        ),
        "products": export_products(filters=filters),
        "verified_receipts_by_currency": [
            {"currency": row["currency"], "total": _money(row["total"])}
            for row in settled_payments(filters)
            .filter(export_order__isnull=False)
            .values("currency")
            .annotate(total=Sum("verified_amount"))
            .order_by("currency")
        ],
    }


def export_products(*, filters=None, limit: int = 20) -> list[dict]:
    queryset = ExportOrderItem.objects.exclude(order__status=ExportOrderStatus.CANCELLED)
    if filters is not None and filters.destination_id:
        queryset = queryset.filter(order__destination_id=filters.destination_id)
    rows = (
        queryset.values("description")
        .annotate(quantity=Sum("quantity"), orders=Count("order", distinct=True))
        .order_by("-quantity")[:limit]
    )
    return [
        {"product": row["description"], "quantity": row["quantity"], "orders": row["orders"]}
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def training_metrics(*, filters=None) -> dict:
    enrollments = count_filtered(Enrollment.objects.all(), filters)
    if filters is not None and filters.status:
        enrollments = enrollments.filter(status=filters.status)
    attendance = count_filtered(AttendanceRecord.objects.all(), filters)
    total_attendance = attendance.count()
    attended = attendance.filter(
        status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]
    ).count()
    finished = enrollments.filter(
        status__in=[EnrollmentStatus.COMPLETED, EnrollmentStatus.CANCELLED]
    ).count()
    completed = enrollments.filter(status=EnrollmentStatus.COMPLETED).count()
    return {
        "total_enrollments": enrollments.count(),
        "confirmed_enrollments": enrollments.filter(
            status__in=CONFIRMED_ENROLLMENT_STATUSES
        ).count(),
        "completed_enrollments": completed,
        "attendance_records": total_attendance,
        "attended_records": attended,
        "attendance_rate": _percent(attended, total_attendance),
        "completion_rate": _percent(completed, finished),
        "certificates_issued": _certificates_issued_count(filters),
        "enrollments_by_status": list(
            enrollments.values("status").annotate(count=Count("id")).order_by("status")
        ),
        "course_popularity": [
            {
                "course": row["session__course__title"],
                "total": row["total"],
                "confirmed": row["confirmed"],
            }
            for row in enrollments.values("session__course__title")
            .annotate(
                total=Count("id"),
                confirmed=Count("id", filter=Q(status__in=CONFIRMED_ENROLLMENT_STATUSES)),
            )
            .order_by("-total")[:10]
        ],
    }


def _certificates_issued_count(filters=None):
    from apps.training.models import Certificate, CertificateStatus

    return (
        count_filtered(Certificate.objects.all(), filters)
        .filter(status=CertificateStatus.ISSUED)
        .count()
    )


# ---------------------------------------------------------------------------
# Customers & support
# ---------------------------------------------------------------------------


def customers_new_by_month(*, filters=None) -> list[dict]:
    """Customer accounts created per month (aggregate only — no personal data)."""
    queryset = count_filtered(User.objects.filter(role=UserRole.CUSTOMER), filters)
    rows = (
        queryset.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    )
    return [{"month": row["month"], "new_customers": row["count"]} for row in rows if row["month"]]


def customer_metrics(*, filters=None) -> dict:
    customers = count_filtered(User.objects.filter(role=UserRole.CUSTOMER), filters)
    active_ids = set(
        Order.objects.exclude(status__in=NON_SALES_ORDER_STATES)
        .values_list("user_id", flat=True)
        .distinct()
    )
    repeat = (
        Order.objects.exclude(status__in=NON_SALES_ORDER_STATES)
        .values("user_id")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
        .count()
    )
    return {
        "new_customers": customers.count(),
        "total_customers": User.objects.filter(role=UserRole.CUSTOMER).count(),
        "active_customers": len(active_ids),
        "repeat_customers": repeat,
        "service_usage_customers": ServiceRequest.objects.values("customer_id").distinct().count(),
        "training_participants": Enrollment.objects.values("student_id").distinct().count(),
    }


def support_analytics(*, filters=None) -> dict:
    tickets = count_filtered(SupportTicket.objects.all(), filters)
    rows = list(tickets.values("id", "created_at", "resolved_at"))
    first_by_ticket: dict = {}
    for row in (
        SupportMessage.objects.filter(is_internal=False, sender__is_staff=True)
        .order_by("created_at")
        .values("ticket_id", "created_at")
    ):
        first_by_ticket.setdefault(row["ticket_id"], row["created_at"])

    response_seconds = []
    resolution_seconds = []
    for row in rows:
        first_at = first_by_ticket.get(row["id"])
        if first_at and row["created_at"]:
            delta = (first_at - row["created_at"]).total_seconds()
            if delta >= 0:
                response_seconds.append(delta)
        if row["resolved_at"] and row["created_at"]:
            delta = (row["resolved_at"] - row["created_at"]).total_seconds()
            if delta >= 0:
                resolution_seconds.append(delta)

    def _avg(values):
        return (sum(values) / len(values)) if values else None

    return {
        "total": tickets.count(),
        "open": tickets.filter(status__in=OPEN_SUPPORT_STATUSES).count(),
        "resolved": tickets.filter(
            status__in=[SupportStatus.RESOLVED, SupportStatus.CLOSED]
        ).count(),
        "by_category": list(
            tickets.values("category").annotate(count=Count("id")).order_by("category")
        ),
        "by_priority": list(
            tickets.values("priority").annotate(count=Count("id")).order_by("priority")
        ),
        "by_status": list(tickets.values("status").annotate(count=Count("id")).order_by("status")),
        "backlog_unassigned": tickets.filter(
            status__in=OPEN_SUPPORT_STATUSES, assigned_to__isnull=True
        ).count(),
        "avg_first_response_seconds": _avg(response_seconds),
        "avg_first_response_display": format_duration(_avg(response_seconds)),
        "avg_resolution_seconds": _avg(resolution_seconds),
        "avg_resolution_display": format_duration(_avg(resolution_seconds)),
        "responded_count": len(response_seconds),
        "staff_workload": list(
            tickets.filter(assigned_to__isnull=False)
            .values("assigned_to__email")
            .annotate(count=Count("id"))
            .order_by("-count")[:15]
        ),
    }


# ---------------------------------------------------------------------------
# Executive roll-up
# ---------------------------------------------------------------------------


def executive_overview(*, filters=None, include_finance: bool = True) -> dict:
    base_orders = counted_orders(filters)
    data: dict = {
        "period_label": filters.label() if filters else "All time",
        "orders_total": base_orders.count(),
        "orders_fulfilled": base_orders.filter(status__in=FULFILLED_ORDER_STATES).count(),
        "orders_open": base_orders.exclude(
            status__in=(*NON_SALES_ORDER_STATES, *FULFILLED_ORDER_STATES)
        ).count(),
        "new_customers": count_filtered(
            User.objects.filter(role=UserRole.CUSTOMER), filters
        ).count(),
        "open_support_tickets": SupportTicket.objects.filter(
            status__in=OPEN_SUPPORT_STATUSES
        ).count(),
        "stock": stock_summary(),
        "low_stock_count": len(low_stock_listings(limit=500)),
        "export_open_enquiries": ExportEnquiry.objects.filter(
            status__in=OPEN_EXPORT_ENQUIRY_STATES
        ).count(),
        "export_active_orders": ExportOrder.objects.filter(
            status__in=EXPORT_ACTIVE_ORDER_STATES
        ).count(),
        "services_open_requests": ServiceRequest.objects.exclude(
            status__in=[
                ServiceRequestStatus.COMPLETED,
                ServiceRequestStatus.REJECTED,
                ServiceRequestStatus.CANCELLED,
            ]
        ).count(),
        "training_confirmed_enrollments": Enrollment.objects.filter(
            status__in=CONFIRMED_ENROLLMENT_STATUSES
        ).count(),
    }
    if include_finance:
        base = base_currency()
        gross = verified_receipts(filters=filters, currency=base)
        refunds = confirmed_refunds(filters=filters, currency=base)
        data.update(
            {
                "base_currency": base,
                "gross_receipts": gross,
                "confirmed_refunds": refunds,
                "net_receipts": gross - refunds,
                "receipts_by_currency": receipts_by_currency(filters=filters),
                "receipts_by_division": receipts_by_division(filters=filters, currency=base),
                "pending_payments": pending_payments_count(),
                "outstanding_invoices": outstanding_invoice_balance(filters=filters),
            }
        )
    return data


__all__ = [
    "EXPORT_ACTIVE_ORDER_STATES",
    "EXPORT_SHIPPED_STATES",
    "FULFILLED_ORDER_STATES",
    "NON_SALES_ORDER_STATES",
    "OPEN_EXPORT_ENQUIRY_STATES",
    "OPEN_SUPPORT_STATUSES",
    "SETTLED_PAYMENT_STATES",
    "base_currency",
    "confirmed_refunds",
    "count_filtered",
    "counted_orders",
    "customer_metrics",
    "customers_new_by_month",
    "executive_overview",
    "export_metrics",
    "export_products",
    "format_duration",
    "listings_by_origin_state",
    "low_stock_listings",
    "movements_by_kind",
    "movements_trend",
    "order_status_distribution",
    "outstanding_invoice_balance",
    "pending_payments_count",
    "receipts_by_currency",
    "receipts_by_day",
    "receipts_by_division",
    "receipts_by_method",
    "refunds_by_status",
    "sales_by_delivery_state",
    "sales_by_origin_lga",
    "sales_by_origin_state",
    "sales_overview",
    "sales_trend",
    "services_metrics",
    "settled_payments",
    "stock_by_product",
    "stock_by_warehouse",
    "stock_summary",
    "storage_utilization",
    "support_analytics",
    "top_categories",
    "top_products",
    "total_outstanding_invoice_balance",
    "training_metrics",
    "verified_receipts",
]

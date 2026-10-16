"""Read layer for the service domain (no mutations, no side effects)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    Consultant,
    ConsultationAppointment,
    FarmProject,
    FarmProjectStatus,
    MarketingEnquiry,
    QuotationStatus,
    ServiceQuotation,
    ServiceRequest,
    ServiceRequestStatus,
    StorageBooking,
    StorageCapacityAllocation,
    StorageFacility,
)

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Customer reads (ownership enforced by the caller's user)
# ---------------------------------------------------------------------------


def customer_service_requests(user, *, service_type: str = "", status: str = ""):
    query = ServiceRequest.objects.filter(customer=user).select_related(
        "state", "lga", "assigned_to"
    )
    if service_type:
        query = query.filter(service_type=service_type)
    if status:
        query = query.filter(status=status)
    return query


def customer_service_request(user, reference: str):
    return (
        ServiceRequest.objects.filter(customer=user, reference=reference)
        .select_related("state", "lga", "assigned_to")
        .first()
    )


def customer_quotations(user, *, status: str = "", request=None):
    query = ServiceQuotation.objects.filter(customer=user).prefetch_related("items")
    if status:
        query = query.filter(status=status)
    if request is not None:
        query = query.filter(request=request)
    return query


def customer_quotation(user, pk):
    return (
        ServiceQuotation.objects.filter(customer=user, pk=pk)
        .select_related("request")
        .prefetch_related("items")
        .first()
    )


def customer_appointments(user):
    return (
        ConsultationAppointment.objects.filter(request__customer=user)
        .select_related("service", "consultant__user", "request")
        .order_by("-scheduled_start")
    )


def customer_farm_projects(user):
    return (
        FarmProject.objects.filter(request__request__customer=user)
        .select_related("request__request", "manager")
        .prefetch_related("milestones", "progress_reports")
    )


def customer_storage_bookings(user):
    return (
        StorageBooking.objects.filter(request__request__customer=user)
        .select_related("facility", "unit", "request__request")
        .order_by("-created_at")
    )


def customer_marketing_enquiries(user):
    return (
        MarketingEnquiry.objects.filter(request__customer=user)
        .prefetch_related("proposals", "campaigns")
        .order_by("-created_at")
    )


# ---------------------------------------------------------------------------
# Staff reads
# ---------------------------------------------------------------------------


def staff_service_requests(
    *, service_type: str = "", status: str = "", assigned_to=None, query: str = ""
):
    queryset = ServiceRequest.objects.select_related("customer", "assigned_to", "state", "lga")
    if service_type:
        queryset = queryset.filter(service_type=service_type)
    if status:
        queryset = queryset.filter(status=status)
    if assigned_to is not None:
        queryset = queryset.filter(assigned_to=assigned_to)
    if query:
        queryset = queryset.filter(
            Q(reference__icontains=query)
            | Q(title__icontains=query)
            | Q(customer__email__icontains=query)
        )
    return queryset


def staff_quotations(*, status: str = "", query: str = ""):
    qs = ServiceQuotation.objects.select_related("customer", "request").prefetch_related("items")
    if status:
        qs = qs.filter(status=status)
    if query:
        qs = qs.filter(
            Q(reference__icontains=query)
            | Q(customer__email__icontains=query)
            | Q(request__reference__icontains=query)
        )
    return qs


def staff_consultants(*, active_only: bool = True):
    qs = Consultant.objects.select_related("user").prefetch_related("availability")
    if active_only:
        qs = qs.filter(is_active=True)
    return qs


def staff_appointments(*, status: str = "", consultant=None):
    qs = ConsultationAppointment.objects.select_related(
        "service", "consultant__user", "request__customer"
    )
    if status:
        qs = qs.filter(status=status)
    if consultant is not None:
        qs = qs.filter(consultant=consultant)
    return qs.order_by("-scheduled_start")


def staff_farm_projects(*, status: str = ""):
    qs = FarmProject.objects.select_related(
        "manager", "request__request__customer"
    ).prefetch_related("milestones")
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


def staff_marketing_enquiries(*, query: str = ""):
    qs = MarketingEnquiry.objects.select_related("request__customer", "service")
    if query:
        qs = qs.filter(
            Q(product_type__icontains=query)
            | Q(request__reference__icontains=query)
            | Q(request__customer__email__icontains=query)
        )
    return qs.order_by("-created_at")


def staff_storage_facilities(*, active_only: bool = True):
    qs = StorageFacility.objects.prefetch_related("units", "accepted_produce_types")
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("name")


def staff_storage_bookings(*, status: str = ""):
    qs = StorageBooking.objects.select_related("facility", "unit", "request__request__customer")
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


# ---------------------------------------------------------------------------
# Metrics (all derived from real records — nothing is invented)
# ---------------------------------------------------------------------------


def service_overview_metrics(*, days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=days)
    requests = ServiceRequest.objects.all()
    by_division = list(
        requests.values("service_type").annotate(total=Count("id")).order_by("service_type")
    )
    open_requests = requests.exclude(
        status__in=[
            ServiceRequestStatus.COMPLETED,
            ServiceRequestStatus.REJECTED,
            ServiceRequestStatus.CANCELLED,
        ]
    ).count()
    since_count = requests.filter(created_at__gte=since).count()
    issued = ServiceQuotation.objects.filter(
        status__in=[QuotationStatus.ISSUED, QuotationStatus.ACCEPTED]
    )
    accepted_value = (
        issued.filter(status=QuotationStatus.ACCEPTED).aggregate(total=Sum("total"))["total"]
        or ZERO
    )
    return {
        "total_requests": requests.count(),
        "open_requests": open_requests,
        "requests_since": since_count,
        "by_division": by_division,
        "quotations_pending": ServiceQuotation.objects.filter(
            status__in=[QuotationStatus.DRAFT, QuotationStatus.PENDING_APPROVAL]
        ).count(),
        "quotations_issued": issued.count(),
        "accepted_quotation_value": accepted_value,
        "storage_active_bookings": StorageBooking.objects.filter(
            status__in=["confirmed", "checked_in"]
        ).count(),
        "farm_active_projects": FarmProject.objects.filter(status=FarmProjectStatus.ACTIVE).count(),
    }


def facility_utilization(facility, *, at_date=None) -> dict:
    at_date = at_date or timezone.localdate()
    allocated = (
        StorageCapacityAllocation.objects.filter(
            facility=facility,
            released_at__isnull=True,
            start_date__lte=at_date,
            end_date__gt=at_date,
        ).aggregate(total=Sum("quantity"))["total"]
        or ZERO
    )
    capacity = facility.capacity or ZERO
    percent = float((allocated / capacity) * 100) if capacity else 0.0
    return {"allocated": allocated, "capacity": capacity, "percent": round(percent, 1)}


def request_status_timeline(service_request):
    return service_request.status_history.select_related("actor").order_by("created_at")


__all__ = [
    "customer_appointments",
    "customer_farm_projects",
    "customer_quotation",
    "customer_quotations",
    "customer_service_request",
    "customer_service_requests",
    "facility_utilization",
    "request_status_timeline",
    "service_overview_metrics",
    "staff_appointments",
    "staff_consultants",
    "staff_farm_projects",
    "staff_marketing_enquiries",
    "staff_quotations",
    "staff_service_requests",
    "staff_storage_bookings",
    "staff_storage_facilities",
]

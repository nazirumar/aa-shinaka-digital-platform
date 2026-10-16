"""Read-only queries for the export domain.

Keeping reads here (and writes in :mod:`apps.export.services`) matches the
project's service-layer convention. Reporting deliberately separates enquiries,
accepted orders, dispatched shipments, delivered shipments and *verified*
revenue — an enquiry is never counted as a completed sale.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum

from apps.orders.payment_models import PaymentState

from .models import (
    ComplianceItemStatus,
    ExportComplianceChecklist,
    ExportDestination,
    ExportDestinationRequirement,
    ExportDocument,
    ExportEnquiry,
    ExportEnquiryStatus,
    ExportOrder,
    ExportOrderStatus,
    ExportQuotation,
    ExportQuotationStatus,
    ExportShipment,
    ExportTradeRestriction,
    ShipmentStatus,
)

# ---------------------------------------------------------------------------
# Destinations & product eligibility
# ---------------------------------------------------------------------------


def active_restriction_for(*, destination, product):
    """Return the most specific active restriction blocking ``product``.

    A restriction matches when it names the product, or its category (when the
    restriction has no product override). Returns ``None`` when unobstructed.
    """
    if destination is None or product is None:
        return None
    qs = list(
        ExportTradeRestriction.objects.filter(destination=destination, is_active=True).filter(
            Q(product=product) | Q(product__isnull=True, category=product.category)
        )
    )
    if not qs:
        return None
    # Prefer a restriction that names the product over a category-wide one.
    qs.sort(key=lambda r: 0 if r.product_id == product.pk else 1)
    return qs[0]


def destination_requirements_for(destination, *, product=None, category=None):
    """Active requirements relevant to a product/category at a destination."""
    qs = ExportDestinationRequirement.objects.filter(destination=destination, is_active=True)
    if product is not None or category is not None:
        qs = qs.filter(
            Q(product__isnull=True, category__isnull=True)
            | Q(product=product)
            | Q(category=category)
        )
    return qs


def document_requirements_for(destination, *, product=None, category=None):
    from .models import ExportDocumentRequirement

    qs = ExportDocumentRequirement.objects.filter(destination=destination).select_related(
        "document_type"
    )
    if product is not None or category is not None:
        qs = qs.filter(
            Q(product__isnull=True, category__isnull=True)
            | Q(product=product)
            | Q(category=category)
        )
    return qs


def active_destinations():
    """Destinations that are approved *and* switched on for trade."""
    return ExportDestination.objects.filter(is_active=True, approval_status="approved")


def public_destinations():
    """Destinations a customer may choose (approved *and* active)."""
    return (
        ExportDestination.objects.filter(is_active=True, approval_status="approved")
        .select_related("country")
        .order_by("country__name")
    )


def stale_requirements(*, limit: int | None = None):
    """Requirements whose review interval has lapsed (flagged for review)."""
    qs = ExportDestinationRequirement.objects.filter(
        is_active=True, review_interval_days__gt=0
    ).select_related("destination", "destination__country")
    stale = [r for r in qs if r.is_stale]
    stale.sort(key=lambda r: (r.last_verified_at is not None, r.last_verified_at))
    return stale if limit is None else stale[:limit]


# ---------------------------------------------------------------------------
# Customer scoping (strict per-user isolation)
# ---------------------------------------------------------------------------


def enquiries_for(user):
    return (
        ExportEnquiry.objects.filter(customer=user)
        .select_related("destination", "destination__country")
        .prefetch_related("items")
    )


def quotations_for(user):
    return (
        ExportQuotation.objects.filter(customer=user)
        .select_related("destination", "destination__country")
        .prefetch_related("items")
    )


def orders_for(user):
    return (
        ExportOrder.objects.filter(customer=user)
        .select_related("destination", "destination__country", "quotation")
        .prefetch_related("items", "shipments")
    )


def visible_documents(order, *, staff: bool = False):
    qs = ExportDocument.objects.filter(order=order).select_related("document_type")
    if not staff:
        qs = qs.filter(is_customer_visible=True)
    return qs


def shipments_for(user):
    return (
        ExportShipment.objects.filter(order__customer=user)
        .select_related("order", "provider")
        .prefetch_related("milestones")
    )


# ---------------------------------------------------------------------------
# Staff queues
# ---------------------------------------------------------------------------


def staff_enquiries(*, status: str = "", destination: str = "", q: str = ""):
    qs = ExportEnquiry.objects.select_related(
        "customer", "destination", "destination__country", "assigned_to"
    ).prefetch_related("items")
    if status:
        qs = qs.filter(status=status)
    if destination:
        qs = qs.filter(destination_id=destination)
    if q:
        qs = qs.filter(
            Q(reference__icontains=q)
            | Q(customer__email__icontains=q)
            | Q(delivery_destination__icontains=q)
        )
    return qs


def staff_quotations(*, status: str = "", destination: str = "", q: str = ""):
    qs = ExportQuotation.objects.select_related(
        "customer", "destination", "destination__country", "enquiry"
    ).prefetch_related("items")
    if status:
        qs = qs.filter(status=status)
    if destination:
        qs = qs.filter(destination_id=destination)
    if q:
        qs = qs.filter(Q(reference__icontains=q) | Q(customer__email__icontains=q))
    return qs


def staff_orders(*, status: str = "", destination: str = "", q: str = ""):
    qs = ExportOrder.objects.select_related(
        "customer", "destination", "destination__country", "quotation"
    ).prefetch_related("items", "shipments")
    if status:
        qs = qs.filter(status=status)
    if destination:
        qs = qs.filter(destination_id=destination)
    if q:
        qs = qs.filter(Q(reference__icontains=q) | Q(customer__email__icontains=q))
    return qs


def staff_documents(*, status: str = "", order: str = "", q: str = ""):
    qs = ExportDocument.objects.select_related(
        "order", "order__customer", "document_type", "reviewed_by"
    )
    if status:
        qs = qs.filter(verification_status=status)
    if order:
        qs = qs.filter(order_id=order)
    if q:
        qs = qs.filter(
            Q(reference__icontains=q)
            | Q(document_reference__icontains=q)
            | Q(order__reference__icontains=q)
        )
    return qs


def compliance_queues(*, status: str = "", q: str = ""):
    qs = ExportComplianceChecklist.objects.select_related(
        "order", "order__customer", "order__destination", "approved_by"
    ).prefetch_related("items")
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(order__reference__icontains=q) | Q(order__customer__email__icontains=q))
    return qs


def shipments_queue(*, status: str = "", q: str = ""):
    qs = ExportShipment.objects.select_related(
        "order", "order__customer", "provider"
    ).prefetch_related("milestones")
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(
            Q(reference__icontains=q)
            | Q(tracking_reference__icontains=q)
            | Q(order__reference__icontains=q)
        )
    return qs


# ---------------------------------------------------------------------------
# Reporting (Task 12)
# ---------------------------------------------------------------------------

_OPEN_ENQUIRY_STATUSES = [
    ExportEnquiryStatus.SUBMITTED,
    ExportEnquiryStatus.UNDER_REVIEW,
    ExportEnquiryStatus.REQUIREMENTS_REQUESTED,
    ExportEnquiryStatus.QUOTED,
]

_ORDER_PIPELINE_STATUSES = [
    ExportOrderStatus.PENDING_PAYMENT,
    ExportOrderStatus.PAYMENT_VERIFIED,
    ExportOrderStatus.IN_PRODUCTION,
    ExportOrderStatus.READY_FOR_SHIPMENT,
    ExportOrderStatus.SHIPPED,
    ExportOrderStatus.DELIVERED,
    ExportOrderStatus.COMPLETED,
]


def overview_metrics() -> dict:
    """Dashboard headline figures — each clearly distinct in meaning."""
    return {
        "enquiries": ExportEnquiry.objects.count(),
        "open_enquiries": ExportEnquiry.objects.filter(status__in=_OPEN_ENQUIRY_STATUSES).count(),
        "quotations_issued": ExportQuotation.objects.filter(
            status__in=[ExportQuotationStatus.ISSUED, ExportQuotationStatus.ACCEPTED]
        ).count(),
        "accepted_quotations": ExportQuotation.objects.filter(
            status=ExportQuotationStatus.ACCEPTED
        ).count(),
        "orders": ExportOrder.objects.count(),
        "open_orders": ExportOrder.objects.exclude(
            status__in=[ExportOrderStatus.COMPLETED, ExportOrderStatus.CANCELLED]
        ).count(),
        "dispatched_shipments": ExportShipment.objects.filter(
            status__in=[
                ShipmentStatus.DISPATCHED,
                ShipmentStatus.IN_TRANSIT,
                ShipmentStatus.CUSTOMS_PROCESSING,
            ]
        ).count(),
        "delivered_shipments": ExportShipment.objects.filter(
            status=ShipmentStatus.DELIVERED
        ).count(),
        "verified_revenue": verified_revenue(),
        "active_destinations": ExportDestination.objects.filter(is_active=True).count(),
    }


def enquiries_by_destination() -> list[dict]:
    return list(
        ExportEnquiry.objects.values("destination__country__name", "destination__country_code")
        .annotate(total=Count("id"))
        .order_by("-total")
    )


def quotations_by_status() -> list[dict]:
    return list(
        ExportQuotation.objects.values("status").annotate(total=Count("id")).order_by("status")
    )


def orders_by_status() -> list[dict]:
    return list(ExportOrder.objects.values("status").annotate(total=Count("id")).order_by("status"))


def shipment_status_breakdown() -> list[dict]:
    return list(
        ExportShipment.objects.values("status").annotate(total=Count("id")).order_by("status")
    )


def product_quantities() -> list[dict]:
    """Aggregate ordered quantities by product (accepted orders, not enquiries)."""
    from .models import ExportOrderItem

    return list(
        ExportOrderItem.objects.filter(order__status__in=_ORDER_PIPELINE_STATUSES)
        .values("description")
        .annotate(quantity=Sum("quantity"), orders=Count("order", distinct=True))
        .order_by("-quantity")
    )


def verified_revenue(currency: str | None = None) -> Decimal:
    """Revenue from *verified* payments on export orders only."""
    from apps.orders.payment_models import Payment

    qs = Payment.objects.filter(
        export_order__isnull=False,
        status__in=[
            PaymentState.PAID,
            PaymentState.REFUNDED,
            PaymentState.PARTIALLY_REFUNDED,
        ],
    )
    if currency:
        qs = qs.filter(currency=currency)
    total = qs.aggregate(total=Sum("verified_amount"))["total"]
    return total or Decimal("0.00")


def verified_revenue_by_currency() -> list[dict]:
    from apps.orders.payment_models import Payment

    return list(
        Payment.objects.filter(
            export_order__isnull=False,
            status__in=[
                PaymentState.PAID,
                PaymentState.REFUNDED,
                PaymentState.PARTIALLY_REFUNDED,
            ],
        )
        .values("currency")
        .annotate(total=Sum("verified_amount"))
        .order_by("currency")
    )


def compliance_delays(*, limit: int = 10) -> list[dict]:
    """Orders with outstanding mandatory compliance items, oldest first."""
    from .models import ExportComplianceChecklistItem

    outstanding = (
        ExportComplianceChecklistItem.objects.filter(
            is_mandatory=True,
            status__in=[
                ComplianceItemStatus.REQUIRED,
                ComplianceItemStatus.PENDING,
                ComplianceItemStatus.SUBMITTED,
                ComplianceItemStatus.REJECTED,
            ],
            checklist__order__status__in=[
                ExportOrderStatus.PENDING_PAYMENT,
                ExportOrderStatus.PAYMENT_VERIFIED,
                ExportOrderStatus.IN_PRODUCTION,
                ExportOrderStatus.READY_FOR_SHIPMENT,
            ],
        )
        .values("checklist__order__reference", "checklist__order__created_at")
        .annotate(outstanding=Count("id"))
        .order_by("checklist__order__created_at")[:limit]
    )
    return list(outstanding)

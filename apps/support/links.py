"""Ownership-validated linking of a support ticket to a customer's own records.

Never trust ``related_type``/``related_id`` supplied by a customer: every lookup
filters on the authenticated customer and raises ``ValidationError`` when the
record does not belong to them (Task 10 / Task 19 — no IDOR).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from .models import SupportRelatedType


def _order(customer, reference):
    from apps.orders.models import Order

    return Order.objects.filter(user=customer, number=reference).first()


def _payment(customer, reference):
    from apps.orders.payment_models import Payment

    return Payment.objects.filter(customer=customer, reference=reference).first()


def _export_enquiry(customer, reference):
    from apps.export.models import ExportEnquiry

    return ExportEnquiry.objects.filter(customer=customer, reference=reference).first()


def _service_request(customer, reference):
    from apps.services.models import ServiceRequest

    return ServiceRequest.objects.filter(customer=customer, reference=reference).first()


def _training_enrollment(customer, reference):
    from apps.training.models import Enrollment

    return Enrollment.objects.filter(student=customer, reference=reference).first()


_RESOLVERS = {
    SupportRelatedType.PRODUCT_ORDER: _order,
    SupportRelatedType.PAYMENT: _payment,
    SupportRelatedType.EXPORT_ENQUIRY: _export_enquiry,
    SupportRelatedType.SERVICE_REQUEST: _service_request,
    SupportRelatedType.TRAINING_ENROLLMENT: _training_enrollment,
}


def resolve_related(customer, related_type: str, related_id: str):
    """Return the customer-owned record or raise ``ValidationError``."""
    if not related_type:
        return None
    resolver = _RESOLVERS.get(related_type)
    if resolver is None:
        raise ValidationError("That related record type cannot be linked.")
    if not related_id:
        raise ValidationError("A related reference is required.")
    obj = resolver(customer, related_id)
    if obj is None:
        raise ValidationError("The linked record was not found in your account.")
    return obj


def eligible_records(customer) -> dict[str, list[dict]]:
    """Group the customer's own linkable records by related type (for the form)."""
    from apps.export.models import ExportEnquiry
    from apps.orders.models import Order
    from apps.orders.payment_models import Payment
    from apps.services.models import ServiceRequest
    from apps.training.models import Enrollment

    orders = Order.objects.filter(user=customer).order_by("-created_at")[:50]
    payments = Payment.objects.filter(customer=customer).order_by("-created_at")[:50]
    enquiries = ExportEnquiry.objects.filter(customer=customer).order_by("-created_at")[:50]
    requests = ServiceRequest.objects.filter(customer=customer).order_by("-created_at")[:50]
    enrollments = Enrollment.objects.filter(student=customer).order_by("-created_at")[:50]

    return {
        SupportRelatedType.PRODUCT_ORDER: [
            {"id": o.number, "label": f"Order {o.number}"} for o in orders
        ],
        SupportRelatedType.PAYMENT: [
            {"id": p.reference, "label": f"Payment {p.reference}"} for p in payments
        ],
        SupportRelatedType.EXPORT_ENQUIRY: [
            {"id": e.reference, "label": f"Export enquiry {e.reference}"} for e in enquiries
        ],
        SupportRelatedType.SERVICE_REQUEST: [
            {
                "id": r.reference,
                "label": f"Service request {r.reference} ({r.get_service_type_display()})",
            }
            for r in requests
        ],
        SupportRelatedType.TRAINING_ENROLLMENT: [
            {"id": e.reference, "label": f"Enrolment {e.reference}"} for e in enrollments
        ],
    }

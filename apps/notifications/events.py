"""Event-specific notification builders (Task 6).

Each helper turns a genuine domain state change into an in-app notification via
:func:`apps.notifications.services.emit`. Domain services call these right after
the matching transactional email helper, so the in-app feed and the dedupe logs
stay in step. Every helper is defensive: a missing link/recipient yields no
notification rather than an error, so a notification problem can never break a
business flow.
"""

from __future__ import annotations

from django.urls import NoReverseMatch, reverse

from .models import NotificationCategory
from .services import emit


def _path(name: str, *args, **kwargs) -> str:
    try:
        return reverse(name, args=args, kwargs=kwargs)
    except NoReverseMatch:  # pragma: no cover - route not present yet
        return ""


def _customer_of(obj):
    return getattr(obj, "customer", None) or getattr(obj, "user", None)


# ---------------------------------------------------------------------------
# Orders & payments
# ---------------------------------------------------------------------------
def order_created(order):
    return emit(
        recipient=getattr(order, "user", None),
        category=NotificationCategory.ORDERS,
        event="order.created",
        title=f"Order {order.number} received",
        message=(
            f"We received order {order.number}. It will be confirmed once payment is verified."
        ),
        url=_path("orders:order_detail", number=order.number),
        reference_type="orders.Order",
        reference_id=order.pk,
        dedupe_key=f"order-created:{order.pk}",
    )


def order_dispatched(order):
    return emit(
        recipient=getattr(order, "user", None),
        category=NotificationCategory.ORDERS,
        event="order.dispatched",
        title=f"Order {order.number} dispatched",
        message=f"Order {order.number} has been dispatched.",
        url=_path("orders:order_detail", number=order.number),
        reference_type="orders.Order",
        reference_id=order.pk,
        dedupe_key=f"order-dispatched:{order.pk}",
    )


def _payment_target_url(payment) -> str:
    if getattr(payment, "order_id", None):
        return _path("orders:order_detail", number=payment.order.number)
    if getattr(payment, "service_quotation_id", None):
        return _path("services:quotation_detail", pk=payment.service_quotation_id)
    if getattr(payment, "export_order_id", None):
        return _path("export:order_detail", reference=payment.export_order.reference)
    if getattr(payment, "training_enrollment_id", None):
        return _path(
            "training_account:enrollment_detail",
            reference=payment.training_enrollment.reference,
        )
    return ""


def payment_verified(payment):
    return emit(
        recipient=getattr(payment, "customer", None),
        category=NotificationCategory.PAYMENTS,
        event="payment.verified",
        title="Payment verified",
        message=(f"We verified your payment of {payment.currency} {payment.expected_amount}."),
        url=_payment_target_url(payment),
        reference_type="orders.Payment",
        reference_id=payment.pk,
        dedupe_key=f"payment-verified:{payment.pk}",
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def export_quotation_issued(quotation):
    return emit(
        recipient=_customer_of(quotation),
        category=NotificationCategory.EXPORT,
        event="export.quotation.issued",
        title=f"Export quotation {quotation.reference} issued",
        message=f"Your export quotation {quotation.reference} is ready to review.",
        url=_path("export:quotation_detail", pk=quotation.pk),
        reference_type="export.ExportQuotation",
        reference_id=quotation.pk,
        dedupe_key=f"export-quotation-issued:{quotation.pk}",
    )


def export_shipment_updated(shipment):
    order = getattr(shipment, "order", None)
    status = getattr(shipment, "status", "")
    return emit(
        recipient=getattr(order, "customer", None),
        category=NotificationCategory.EXPORT,
        event="export.shipment.updated",
        title=f"Shipment {shipment.reference} updated",
        message=f"Your export shipment {shipment.reference} is now {status}.",
        url=_path("export:shipment_detail", reference=shipment.reference),
        reference_type="export.ExportShipment",
        reference_id=shipment.pk,
        dedupe_key=f"export-shipment:{shipment.pk}:{status}",
    )


# ---------------------------------------------------------------------------
# Agricultural services
# ---------------------------------------------------------------------------
def _service_request_reference(obj):
    request = getattr(obj, "request", None)
    # FarmProject / StorageBooking wrap a FarmXRequest/StorageServiceRequest that
    # in turn points at the shared ServiceRequest.
    nested = getattr(request, "request", None)
    target = nested or request
    return getattr(target, "reference", ""), getattr(target, "customer", None)


def consultancy_appointment_confirmed(appointment):
    reference, customer = _service_request_reference(appointment)
    return emit(
        recipient=customer,
        category=NotificationCategory.SERVICES,
        event="services.appointment.confirmed",
        title="Consultancy appointment confirmed",
        message="Your consultancy appointment has been confirmed.",
        url=_path("services:request_detail", reference=reference) if reference else "",
        reference_type="services.ConsultationAppointment",
        reference_id=appointment.pk,
        dedupe_key=f"appointment-confirmed:{appointment.pk}",
    )


def farming_milestone_updated(milestone):
    project = getattr(milestone, "project", None)
    reference, customer = _service_request_reference(project) if project else ("", None)
    status = getattr(milestone, "status", "")
    return emit(
        recipient=customer,
        category=NotificationCategory.SERVICES,
        event="services.farm.milestone",
        title="Farming project milestone updated",
        message=f"A milestone on your farming project is now {status}.",
        url=_path("services:request_detail", reference=reference) if reference else "",
        reference_type="services.FarmProjectMilestone",
        reference_id=milestone.pk,
        dedupe_key=f"farm-milestone:{milestone.pk}:{status}",
    )


def storage_booking_confirmed(booking):
    reference, customer = _service_request_reference(booking)
    return emit(
        recipient=customer,
        category=NotificationCategory.SERVICES,
        event="services.storage.confirmed",
        title=f"Storage booking {booking.reference} confirmed",
        message=f"Your storage booking {booking.reference} has been confirmed.",
        url=_path("services:request_detail", reference=reference) if reference else "",
        reference_type="services.StorageBooking",
        reference_id=booking.pk,
        dedupe_key=f"storage-confirmed:{booking.pk}",
    )


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def training_enrollment_confirmed(enrollment):
    return emit(
        recipient=getattr(enrollment, "student", None),
        category=NotificationCategory.TRAINING,
        event="training.enrollment.confirmed",
        title=f"Enrolment {enrollment.reference} confirmed",
        message=f"Your enrolment {enrollment.reference} has been confirmed.",
        url=_path("training_account:enrollment_detail", reference=enrollment.reference),
        reference_type="training.Enrollment",
        reference_id=enrollment.pk,
        dedupe_key=f"training-enrollment-confirmed:{enrollment.pk}",
    )


def certificate_issued(certificate):
    return emit(
        recipient=getattr(certificate, "student", None),
        category=NotificationCategory.TRAINING,
        event="training.certificate.issued",
        title="Certificate issued",
        message=f"Your certificate {certificate.certificate_number} has been issued.",
        url=_path("training_account:certificate_view", pk=certificate.pk),
        reference_type="training.Certificate",
        reference_id=certificate.pk,
        dedupe_key=f"certificate-issued:{certificate.pk}",
    )


# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------
def support_ticket_reply(message):
    """Notify the customer when a staff member replies to their ticket."""
    ticket = getattr(message, "ticket", None)
    if ticket is None:
        return None
    return emit(
        recipient=getattr(ticket, "customer", None),
        category=NotificationCategory.SUPPORT,
        event="support.reply",
        title=f"New reply on ticket {ticket.reference}",
        message=f"Support replied to your ticket {ticket.reference}.",
        url=_path("support:ticket_detail", reference=ticket.reference),
        reference_type="support.SupportTicket",
        reference_id=ticket.pk,
        dedupe_key=f"support-reply:{getattr(message, 'pk', '')}",
    )


__all__ = [
    "certificate_issued",
    "consultancy_appointment_confirmed",
    "export_quotation_issued",
    "export_shipment_updated",
    "farming_milestone_updated",
    "order_created",
    "order_dispatched",
    "payment_verified",
    "storage_booking_confirmed",
    "support_ticket_reply",
    "training_enrollment_confirmed",
]

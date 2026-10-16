"""Export-domain notifications (Task 13).

Reuses the Phase 6 email helper (``apps.orders.notifications.send_notification``)
so there is a single templating/mail path. Every notification is recorded in
:class:`~apps.export.models.ExportNotificationLog` keyed on a stable dedupe key,
so a retried or duplicated call never double-notifies.
"""

from __future__ import annotations

from apps.orders.notifications import send_notification

from .models import ExportNotificationLog


def notify_once(
    *, event: str, dedupe_key: str, to: str, subject: str, heading: str, intro: str, **extra
) -> bool:
    """Send ``heading``/``intro`` once for ``dedupe_key``; return whether it sent."""
    if not to:
        return False
    _, created = ExportNotificationLog.objects.get_or_create(
        dedupe_key=dedupe_key[:160], defaults={"event": event}
    )
    if not created:
        return False
    send_notification(to=to, subject=subject, heading=heading, intro=intro, **extra)
    return True


def _customer_email(obj) -> str:
    return getattr(getattr(obj, "customer", None), "email", "")


def enquiry_received(enquiry) -> bool:
    return notify_once(
        event="export_enquiry_received",
        dedupe_key=f"export-enquiry-received:{enquiry.pk}",
        to=_customer_email(enquiry),
        subject=f"We received your export enquiry {enquiry.reference}",
        heading="Export enquiry received",
        intro=(
            f"Thank you. We received export enquiry {enquiry.reference} for "
            f"{enquiry.destination.country.name}. Our export team will review the "
            "destination's requirements and respond with a quotation."
        ),
    )


def quotation_issued(quotation) -> bool:
    return notify_once(
        event="export_quotation_issued",
        dedupe_key=f"export-quotation-issued:{quotation.pk}:{quotation.revision}",
        to=_customer_email(quotation),
        subject=f"Export quotation {quotation.reference} is ready",
        heading="Your export quotation is ready",
        intro=(
            f"Quotation {quotation.reference} for {quotation.destination.country.name} "
            f"totals {quotation.currency} {quotation.total}. Review the commercial terms "
            f"({quotation.incoterm} {quotation.named_place}) and accept it to proceed."
        ),
    )


def quotation_accepted(quotation) -> bool:
    return notify_once(
        event="export_quotation_accepted",
        dedupe_key=f"export-quotation-accepted:{quotation.pk}:{quotation.revision}",
        to=_customer_email(quotation),
        subject=f"Export quotation {quotation.reference} accepted",
        heading="Quotation accepted",
        intro=(
            f"We recorded your acceptance of quotation {quotation.reference}. "
            "We will now raise the export order with the agreed payment terms."
        ),
    )


def compliance_document_requested(order, label: str) -> bool:
    # Sent to the owning customer when a specific document is outstanding.
    return notify_once(
        event="export_compliance_requested",
        dedupe_key=f"export-compliance-requested:{order.pk}:{label}"[:160],
        to=_customer_email(order),
        subject=f"Action needed for export order {order.reference}",
        heading="Document required",
        intro=(f"Export order {order.reference} needs the following to clear compliance: {label}."),
    )


def document_reviewed(document) -> bool:
    decision = document.verification_status
    return notify_once(
        event="export_document_reviewed",
        dedupe_key=f"export-document-reviewed:{document.pk}:{decision}",
        to=_customer_email(document.order),
        subject=f"Export document {document.reference} {decision}",
        heading="Export document reviewed",
        intro=(
            f"Document {document.reference} ({document.document_type.name}) for order "
            f"{document.order.reference} was recorded as '{decision}'."
        ),
    )


def payment_verified(order, payment=None) -> bool:
    return notify_once(
        event="export_payment_verified",
        dedupe_key=f"export-payment-verified:{payment.pk if payment else order.pk}",
        to=_customer_email(order),
        subject=f"Payment verified for export order {order.reference}",
        heading="Payment verified",
        intro=(
            f"Your payment for export order {order.reference} has been verified. "
            f"Amount paid: {order.currency} {order.amount_paid}."
        ),
    )


def shipment_dispatched(shipment) -> bool:
    return notify_once(
        event="export_shipment_dispatched",
        dedupe_key=f"export-shipment-dispatched:{shipment.pk}",
        to=_customer_email(shipment.order),
        subject=f"Shipment {shipment.reference} dispatched",
        heading="Shipment dispatched",
        intro=(
            f"Shipment {shipment.reference} for order {shipment.order.reference} has been "
            f"dispatched ({shipment.get_transport_mode_display()})."
        ),
    )


def shipment_status_updated(shipment) -> bool:
    return notify_once(
        event="export_shipment_status",
        dedupe_key=f"export-shipment-status:{shipment.pk}:{shipment.status}",
        to=_customer_email(shipment.order),
        subject=f"Shipment {shipment.reference}: {shipment.get_status_display()}",
        heading="Shipment update",
        intro=(f"Shipment {shipment.reference} is now '{shipment.get_status_display()}'."),
    )


def delivery_confirmed(shipment) -> bool:
    return notify_once(
        event="export_delivery_confirmed",
        dedupe_key=f"export-delivery-confirmed:{shipment.pk}",
        to=_customer_email(shipment.order),
        subject=f"Delivery confirmed for {shipment.reference}",
        heading="Delivery confirmed",
        intro=(
            f"Shipment {shipment.reference} for order {shipment.order.reference} has been "
            "delivered."
        ),
    )

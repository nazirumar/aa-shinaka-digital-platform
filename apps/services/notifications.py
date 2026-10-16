"""Service-domain notifications (Task 10).

Reuses the Phase 6 email helper (``apps.orders.notifications.send_notification``)
so there is a single templating/mail path. Each notification is recorded in
:class:`~apps.services.models.ServiceNotificationLog` keyed on a stable
dedupe key, so a retried/duplicated service call never double-notifies.
"""

from __future__ import annotations

from apps.orders.notifications import send_notification

from .models import ServiceNotificationLog


def _company_reference(obj) -> str:
    return getattr(obj, "reference", "") or getattr(obj, "number", "")


def notify_once(
    *, event: str, dedupe_key: str, to: str, subject: str, heading: str, intro: str, **extra
):
    """Send ``intro``/``heading`` once for ``dedupe_key``; return whether it sent."""
    if not to:
        return False
    _, created = ServiceNotificationLog.objects.get_or_create(
        dedupe_key=dedupe_key[:160], defaults={"event": event}
    )
    if not created:
        return False
    send_notification(to=to, subject=subject, heading=heading, intro=intro, **extra)
    return True


def _customer_email(request_obj) -> str:
    return getattr(getattr(request_obj, "customer", None), "email", "")


def service_request_submitted(service_request) -> bool:
    return notify_once(
        event="service_request_submitted",
        dedupe_key=f"request-submitted:{service_request.pk}",
        to=_customer_email(service_request),
        subject=f"We received your {service_request.get_service_type_display()} request",
        heading="Request received",
        intro=(
            f"Thank you. We received request {service_request.reference} and our team "
            "will review it and get back to you."
        ),
    )


def staff_review_completed(service_request, *, message: str = "") -> bool:
    return notify_once(
        event="staff_review_completed",
        dedupe_key=f"reviewed:{service_request.pk}:{service_request.status}",
        to=_customer_email(service_request),
        subject=f"Update on your request {service_request.reference}",
        heading="Your request has been reviewed",
        intro=message or f"Our team has reviewed request {service_request.reference}.",
    )


def quotation_issued(quotation) -> bool:
    return notify_once(
        event="quotation_issued",
        dedupe_key=f"quotation-issued:{quotation.pk}",
        to=getattr(quotation.customer, "email", ""),
        subject=f"Quotation {quotation.reference} is ready",
        heading="Your quotation is ready",
        intro=(
            f"We issued quotation {quotation.reference} for {quotation.currency} "
            f"{quotation.total}. You can review and respond from your account."
        ),
    )


def quotation_accepted(quotation) -> bool:
    return notify_once(
        event="quotation_accepted",
        dedupe_key=f"quotation-accepted:{quotation.pk}",
        to=getattr(quotation.customer, "email", ""),
        subject=f"Quotation {quotation.reference} accepted",
        heading="Quotation accepted",
        intro=(
            f"Thanks — we recorded your acceptance of quotation {quotation.reference}. "
            "Our team will proceed as agreed."
        ),
    )


def appointment_confirmed(appointment) -> bool:
    return notify_once(
        event="appointment_confirmed",
        dedupe_key=f"appointment-confirmed:{appointment.pk}:{appointment.scheduled_start.isoformat()}",
        to=_customer_email(appointment.request),
        subject=f"Consultation confirmed for {appointment.scheduled_start:%d %b %Y, %H:%M}",
        heading="Your consultation is confirmed",
        intro=(
            f"Your {appointment.get_mode_display().lower()} consultation is confirmed for "
            f"{appointment.scheduled_start:%d %b %Y at %H:%M}."
        ),
    )


def appointment_rescheduled(appointment) -> bool:
    return notify_once(
        event="appointment_rescheduled",
        dedupe_key=f"appointment-rescheduled:{appointment.pk}:{appointment.scheduled_start.isoformat()}",
        to=_customer_email(appointment.request),
        subject=f"Consultation rescheduled to {appointment.scheduled_start:%d %b %Y, %H:%M}",
        heading="Your consultation was rescheduled",
        intro=(
            f"Your consultation has been moved to {appointment.scheduled_start:%d %b %Y at %H:%M}."
        ),
    )


def milestone_updated(milestone) -> bool:
    project = milestone.project
    request_obj = project.request.request
    return notify_once(
        event="milestone_updated",
        dedupe_key=f"milestone:{milestone.pk}:{milestone.status}",
        to=_customer_email(request_obj),
        subject=f"Project update: {milestone.title}",
        heading="Project milestone updated",
        intro=(
            f"Milestone '{milestone.title}' on project {project.reference} is now "
            f"{milestone.get_status_display().lower()}."
        ),
    )


def storage_booking_confirmed(booking) -> bool:
    request_obj = booking.request.request
    return notify_once(
        event="storage_booking_confirmed",
        dedupe_key=f"storage-confirmed:{booking.pk}",
        to=_customer_email(request_obj),
        subject=f"Storage booking {booking.reference} confirmed",
        heading="Your storage booking is confirmed",
        intro=(
            f"Storage booking {booking.reference} at {booking.facility.name} is confirmed "
            f"from {booking.start_date:%d %b %Y} to {booking.end_date:%d %b %Y}."
        ),
    )


def service_completed(service_request) -> bool:
    return notify_once(
        event="service_completed",
        dedupe_key=f"service-completed:{service_request.pk}",
        to=_customer_email(service_request),
        subject=f"Request {service_request.reference} completed",
        heading="Service completed",
        intro=(
            f"Request {service_request.reference} has been completed. "
            "Any reports are available in your account."
        ),
    )

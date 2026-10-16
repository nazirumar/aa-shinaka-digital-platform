"""Customer email notifications for payment/refund/invoice events (Task 13).

Every helper is a no-op when there is no recipient and is wrapped so a mail
failure can never break a payment flow. Event helpers are only called on genuine
state changes (the settlement/refund services are idempotent), so retried
webhooks do not send duplicate notifications.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _company():
    try:
        from apps.cms.models import SiteSetting

        return SiteSetting.load()
    except Exception:  # pragma: no cover - CMS not migrated yet
        return None


def _order_context(order) -> dict:
    return {
        "order": order,
        "order_number": getattr(order, "number", ""),
        "order_total": getattr(order, "grand_total", None),
        "currency": getattr(order, "currency", "NGN"),
    }


def _payment_label(payment) -> str:
    """Human label for a payment's target (order, quotation, export or training)."""
    if getattr(payment, "order_id", None):
        return payment.order.number
    if getattr(payment, "service_quotation_id", None):
        return payment.service_quotation.reference
    if getattr(payment, "export_order_id", None):
        return payment.export_order.reference
    if getattr(payment, "training_enrollment_id", None):
        return payment.training_enrollment.reference
    return payment.reference


def _payment_context(payment) -> dict:
    """Context for a payment that may settle an order, quotation, export or enrolment."""
    context = _order_context(getattr(payment, "order", None))
    context["reference"] = _payment_label(payment)
    if payment.service_quotation_id:
        context["currency"] = payment.currency
        context["order_total"] = payment.expected_amount
    if getattr(payment, "export_order_id", None):
        context["currency"] = payment.currency
        context["order_total"] = payment.expected_amount
    if getattr(payment, "training_enrollment_id", None):
        context["currency"] = payment.currency
        context["order_total"] = payment.expected_amount
    return context


def send_notification(*, to: str, subject: str, heading: str, intro: str, **extra) -> None:
    """Render and send one notification email (text + HTML) to ``to``."""
    if not to:
        return
    context = {
        "company": _company(),
        "heading": heading,
        "intro": intro,
        "site_url": getattr(settings, "PAYSTACK_CALLBACK_URL", "") or "",
    }
    context.update(extra)
    try:
        text = render_to_string("orders/email/notification_body.txt", context)
        html = render_to_string("orders/email/notification_body.html", context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to],
        )
        message.attach_alternative(html, "text/html")
        message.send(fail_silently=False)
    except Exception:  # pragma: no cover - notifications must never break flows
        logger.exception("Failed to send payment notification '%s'.", subject)


def notify_payment_initiated(payment) -> None:
    label = _payment_label(payment)
    send_notification(
        to=payment.customer.email,
        subject=f"Payment started for {label}",
        heading="Your payment has started",
        intro=(
            f"We created a payment of {payment.currency} {payment.expected_amount} for "
            f"{label}. Complete it with the provider to confirm."
        ),
        **_payment_context(payment),
    )


def notify_payment_verified(payment) -> None:
    label = _payment_label(payment)
    send_notification(
        to=payment.customer.email,
        subject=f"Payment received for {label}",
        heading="Payment received",
        intro=(
            f"We verified your payment of {payment.currency} {payment.settled_amount} for "
            f"{label}. It is now confirmed."
        ),
        **_payment_context(payment),
    )


def notify_payment_failed(payment) -> None:
    label = _payment_label(payment)
    send_notification(
        to=payment.customer.email,
        subject=f"Payment not completed for {label}",
        heading="Payment not completed",
        intro=(
            f"Your payment attempt for {label} was not completed. No funds were captured; "
            "you can try again or choose a bank transfer where offered."
        ),
        **_payment_context(payment),
    )


def notify_payment_needs_review(payment) -> None:
    label = _payment_label(payment)
    send_notification(
        to=payment.customer.email,
        subject=f"{label} is under payment review",
        heading="Your payment is under review",
        intro=(
            f"We captured a payment of {payment.currency} {payment.settled_amount} for {label}, "
            "but it could not be confirmed automatically. Our finance team will review it."
        ),
        **_payment_context(payment),
    )


def notify_bank_transfer_under_review(submission) -> None:
    send_notification(
        to=submission.customer.email,
        subject=f"Bank transfer received for review ({submission.payment.order.number})",
        heading="Your bank transfer is under review",
        intro=(
            f"We received your bank transfer reference {submission.transfer_reference} for order "
            f"{submission.payment.order.number}. Our finance team will confirm settlement before "
            "the order is processed."
        ),
        **_order_context(submission.payment.order),
    )


def notify_bank_transfer_reviewed(submission) -> None:
    approved = submission.get_status_display()
    send_notification(
        to=submission.customer.email,
        subject=f"Bank transfer review: {approved} ({submission.payment.order.number})",
        heading=f"Bank transfer {approved.lower()}",
        intro=(
            f"Your bank transfer for order {submission.payment.order.number} was "
            f"{approved.lower()}."
        ),
        **_order_context(submission.payment.order),
    )


def notify_invoice_issued(invoice) -> None:
    send_notification(
        to=invoice.customer_email,
        subject=f"Invoice {invoice.number} for order {invoice.order.number}",
        heading="Your invoice is ready",
        intro=(
            f"Invoice {invoice.number} for {invoice.currency} {invoice.total} has been issued for "
            f"order {invoice.order.number}."
        ),
        invoice=invoice,
        **_order_context(invoice.order),
    )


def notify_receipt_issued(receipt) -> None:
    payment = receipt.payment
    label = _payment_label(payment)
    send_notification(
        to=payment.customer.email,
        subject=f"Receipt {receipt.number} for {label}",
        heading="Your receipt is ready",
        intro=(
            f"We issued receipt {receipt.number} for your verified payment of "
            f"{receipt.currency} {receipt.amount}."
        ),
        receipt=receipt,
        **_payment_context(payment),
    )


def notify_refund_requested(refund) -> None:
    payment = refund.payment
    send_notification(
        to=payment.customer.email,
        subject=f"Refund requested for order {payment.order.number}",
        heading="Refund requested",
        intro=(
            f"A refund of {payment.currency} {refund.amount} has been requested for order "
            f"{payment.order.number}. It is subject to finance approval and reconciliation."
        ),
        **_order_context(payment.order),
    )


def notify_refund_completed(refund) -> None:
    payment = refund.payment
    send_notification(
        to=payment.customer.email,
        subject=f"Refund processed for order {payment.order.number}",
        heading="Refund processed",
        intro=(
            f"Your refund of {payment.currency} {refund.amount} for order {payment.order.number} "
            "has been processed by the provider."
        ),
        **_order_context(payment.order),
    )

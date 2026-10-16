"""Phase 6 payment services: Paystack, webhooks, bank transfers, refunds,
invoices, receipts and reconciliation.

Design rules (see ``docs/ARCHITECTURE.md``):

* The **authoritative order amount** is always read from the database, never
  from the client or the browser redirect.
* Payments are only marked ``paid`` after a *server-side* provider verification
  (API verify call or a signature-verified webhook) whose currency and amount
  match the expected values.
* Every state change is transactional and idempotent: duplicate callbacks,
  duplicate webhooks and out-of-order events must not double-settle an order,
  re-commit stock, re-issue a receipt or double-refund.
* The order state machine stays in :mod:`apps.orders.services`; this module
  calls ``services.settle_order`` after a verified capture.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability
from apps.core.audit import record_audit, redact
from apps.notifications import events as notification_events

from . import notifications, paystack, services
from .models import Order, OrderStatus, PaymentStatus, ReservationStatus
from .payment_models import (
    OPEN_PAYMENT_STATES,
    REFUNDABLE_PAYMENT_STATES,
    BankTransferStatus,
    BankTransferSubmission,
    CompanyBankAccount,
    Invoice,
    InvoiceState,
    Payment,
    PaymentAttempt,
    PaymentAttemptStatus,
    PaymentProvider,
    PaymentState,
    PaymentWebhookEvent,
    Receipt,
    Refund,
    RefundProviderState,
    RefundState,
    WebhookEventStatus,
)

logger = logging.getLogger(__name__)

PAYABLE_ORDER_STATUSES = frozenset({OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_REVIEW})

_METHOD_FOR_CHANNEL = {
    "card": "card",
    "bank": "bank",
    "bank_transfer": "transfer",
    "transfer": "transfer",
    "ussd": "ussd",
    "qr": "qr",
    "mobile_money": "mobile_money",
}

CANCELLED_OR_EXPIRED = frozenset({OrderStatus.CANCELLED, OrderStatus.EXPIRED})

_REFUNDABLE_ORDER_STATUSES = frozenset(
    {
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
        OrderStatus.READY_FOR_DISPATCH,
        OrderStatus.DISPATCHED,
        OrderStatus.DELIVERED,
        OrderStatus.COMPLETED,
    }
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def configured_currency() -> str:
    return (getattr(settings, "PAYSTACK_CURRENCY", "NGN") or "NGN").upper()


def _generate_number(prefix: str, model, field: str = "number") -> str:
    today = timezone.now().strftime("%Y%m%d")
    for _ in range(10):
        candidate = f"{prefix}-{today}-{secrets.token_hex(3).upper()}"
        if not model.objects.filter(**{field: candidate}).exists():
            return candidate
    raise ValidationError("Could not allocate a unique reference. Please try again.")


def _callback_url(order, request=None) -> str:
    from django.urls import reverse

    path = reverse("orders:payment_callback", kwargs={"number": order.number})
    if request is not None:
        return request.build_absolute_uri(path)
    configured = getattr(settings, "PAYSTACK_CALLBACK_URL", "") or ""
    if configured:
        return configured
    hosts = getattr(settings, "ALLOWED_HOSTS", []) or []
    scheme = "http" if getattr(settings, "DEBUG", False) else "https"
    return f"{scheme}://{hosts[0]}{path}" if hosts else path


def _method_for_channel(channel: str) -> str:
    return _METHOD_FOR_CHANNEL.get((channel or "").strip().lower(), "")


# ---------------------------------------------------------------------------
# Paystack initialisation
# ---------------------------------------------------------------------------


def initialize_payment(order, *, actor, request=None, channel: str = "") -> Payment:
    """Create a :class:`Payment` and a hosted Paystack checkout for ``order``.

    Reuses any open Paystack payment for the same order/amount so re-clicking
    "Pay" never creates duplicate charges or references.
    """
    if not paystack.is_enabled():
        raise ValidationError("Online card payment is not currently available.")
    if order.user_id != getattr(actor, "id", None) and not has_capability(
        actor, Capability.ORDERS_MANAGE
    ):
        raise PermissionDenied("You cannot pay for this order.")

    currency = configured_currency()
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.payment_status == PaymentStatus.PAID:
            raise ValidationError("This order is already paid.")
        if order.status not in PAYABLE_ORDER_STATUSES:
            raise ValidationError("This order can no longer be paid.")
        if order.currency.upper() != currency:
            raise ValidationError(
                f"This order's currency ({order.currency}) is not supported by the provider."
            )
        if order.grand_total <= 0:
            raise ValidationError("This order has no amount to pay.")
        if not order.reservations.filter(status=ReservationStatus.ACTIVE).exists():
            raise ValidationError("Your stock reservation has expired. Please place a new order.")
        existing = (
            Payment.objects.filter(
                order=order,
                provider=PaymentProvider.PAYSTACK,
                status__in=OPEN_PAYMENT_STATES,
                expected_amount=order.grand_total,
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            return existing
        payment = Payment.objects.create(
            order=order,
            customer=order.user,
            reference=_generate_number("AS-PAY", Payment, field="reference"),
            provider=PaymentProvider.PAYSTACK,
            currency=order.currency,
            expected_amount=order.grand_total,
            status=PaymentState.PENDING,
        )

    try:
        data = paystack.initialize_transaction(
            email=order.user.email,
            amount_kobo=paystack.to_kobo(order.grand_total),
            currency=order.currency,
            reference=payment.reference,
            callback_url=_callback_url(order, request),
            metadata={
                "order": order.number,
                "payment_reference": payment.reference,
                "customer_id": str(order.user_id),
            },
            channels=[channel] if channel else None,
        )
    except paystack.PaystackError as exc:
        PaymentAttempt.objects.create(
            payment=payment,
            provider_reference=payment.reference,
            status=PaymentAttemptStatus.FAILED,
            failure_code=exc.code,
            failure_message=str(exc)[:500],
        )
        payment.status = PaymentState.FAILED
        payment.note = f"Initialisation failed: {exc.code}."
        payment.save(update_fields=["status", "note", "updated_at"])
        record_audit(
            actor=actor,
            action="orders.payment.initialize_failed",
            target=payment,
            after={"code": exc.code},
            request=request,
        )
        notify_safe(notifications.notify_payment_failed, payment)
        raise ValidationError("We could not start the payment. Please try again.") from exc

    attempt = PaymentAttempt.objects.create(
        payment=payment,
        provider_reference=str(data.get("reference") or payment.reference)[:120],
        authorization_url=str(data.get("authorization_url") or "")[:500],
        access_code=str(data.get("access_code") or "")[:120],
        status=PaymentAttemptStatus.INITIALIZED,
    )
    payment.status = PaymentState.PROCESSING
    payment.provider_reference = attempt.provider_reference
    payment.method = _method_for_channel(channel)
    payment.save(update_fields=["status", "provider_reference", "method", "updated_at"])
    record_audit(
        actor=actor,
        action="orders.payment.initialized",
        target=payment,
        after={"reference": payment.reference, "amount": str(payment.expected_amount)},
        request=request,
    )
    notify_safe(notifications.notify_payment_initiated, payment)
    return payment


def latest_authorization_url(payment: Payment) -> str:
    attempt = payment.attempts.order_by("-created_at").first()
    return attempt.authorization_url if attempt else ""


def _service_callback_url(quotation, request=None) -> str:
    from django.urls import reverse

    path = reverse("services:service_payment_callback", kwargs={"reference": quotation.reference})
    if request is not None:
        return request.build_absolute_uri(path)
    configured = getattr(settings, "PAYSTACK_CALLBACK_URL", "") or ""
    if configured:
        return configured
    hosts = getattr(settings, "ALLOWED_HOSTS", []) or []
    scheme = "http" if getattr(settings, "DEBUG", False) else "https"
    return f"{scheme}://{hosts[0]}{path}" if hosts else path


def initialize_quotation_payment(quotation, *, actor, request=None, channel: str = "") -> Payment:
    """Create a Paystack checkout to pay an issued service quotation.

    Mirrors :func:`initialize_payment` but settles a ``ServiceQuotation``
    instead of an order. Reuses Phase 6 idempotency: re-clicking "Pay" returns
    any open payment for the same quotation/amount rather than charging twice.
    """
    from apps.services.models import QuotationPaymentStatus, QuotationStatus

    if not paystack.is_enabled():
        raise ValidationError("Online card payment is not currently available.")
    if quotation.customer_id != getattr(actor, "id", None) and not has_capability(
        actor, Capability.FINANCE_MANAGE
    ):
        raise PermissionDenied("You cannot pay for this quotation.")

    currency = configured_currency()
    with transaction.atomic():
        quotation = type(quotation).objects.select_for_update().get(pk=quotation.pk)
        if quotation.payment_status == QuotationPaymentStatus.PAID:
            raise ValidationError("This quotation is already paid.")
        if quotation.status not in {QuotationStatus.ISSUED, QuotationStatus.ACCEPTED}:
            raise ValidationError("This quotation is not ready for payment.")
        if quotation.currency.upper() != currency:
            raise ValidationError(
                f"This quotation's currency ({quotation.currency}) is not supported."
            )
        if quotation.total <= 0:
            raise ValidationError("This quotation has no amount to pay.")
        existing = (
            Payment.objects.filter(
                service_quotation=quotation,
                provider=PaymentProvider.PAYSTACK,
                status__in=OPEN_PAYMENT_STATES,
                expected_amount=quotation.total,
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            return existing
        payment = Payment.objects.create(
            service_quotation=quotation,
            customer=quotation.customer,
            reference=_generate_number("AS-PAY", Payment, field="reference"),
            provider=PaymentProvider.PAYSTACK,
            currency=quotation.currency,
            expected_amount=quotation.total,
            status=PaymentState.PENDING,
        )

    try:
        data = paystack.initialize_transaction(
            email=quotation.customer.email,
            amount_kobo=paystack.to_kobo(quotation.total),
            currency=quotation.currency,
            reference=payment.reference,
            callback_url=_service_callback_url(quotation, request),
            metadata={
                "service_quotation": quotation.reference,
                "payment_reference": payment.reference,
                "customer_id": str(quotation.customer_id),
            },
            channels=[channel] if channel else None,
        )
    except paystack.PaystackError as exc:
        PaymentAttempt.objects.create(
            payment=payment,
            provider_reference=payment.reference,
            status=PaymentAttemptStatus.FAILED,
            failure_code=exc.code,
            failure_message=str(exc)[:500],
        )
        payment.status = PaymentState.FAILED
        payment.note = f"Initialisation failed: {exc.code}."
        payment.save(update_fields=["status", "note", "updated_at"])
        notify_safe(notifications.notify_payment_failed, payment)
        raise ValidationError("We could not start the payment. Please try again.") from exc

    attempt = PaymentAttempt.objects.create(
        payment=payment,
        provider_reference=str(data.get("reference") or payment.reference)[:120],
        authorization_url=str(data.get("authorization_url") or "")[:500],
        access_code=str(data.get("access_code") or "")[:120],
        status=PaymentAttemptStatus.INITIALIZED,
    )
    payment.status = PaymentState.PROCESSING
    payment.provider_reference = attempt.provider_reference
    payment.method = _method_for_channel(channel)
    payment.save(update_fields=["status", "provider_reference", "method", "updated_at"])
    record_audit(
        actor=actor,
        action="services.quotation.payment_initialized",
        target=payment,
        after={"reference": payment.reference, "amount": str(payment.expected_amount)},
        request=request,
    )
    notify_safe(notifications.notify_payment_initiated, payment)
    return payment


def _export_callback_url(order, request=None) -> str:
    from django.urls import reverse

    path = reverse("export:payment_callback", kwargs={"reference": order.reference})
    if request is not None:
        return request.build_absolute_uri(path)
    configured = getattr(settings, "PAYSTACK_CALLBACK_URL", "") or ""
    if configured:
        return configured
    hosts = getattr(settings, "ALLOWED_HOSTS", []) or []
    scheme = "http" if getattr(settings, "DEBUG", False) else "https"
    return f"{scheme}://{hosts[0]}{path}" if hosts else path


def initialize_export_payment(
    export_order, *, actor, amount, purpose=None, request=None, channel: str = ""
) -> Payment:
    """Create a Paystack checkout to pay (part of) an export order.

    Mirrors :func:`initialize_quotation_payment`. Currency eligibility is
    enforced against the configured provider currency — Paystack is **not**
    assumed to support every international currency, so an unsupported export
    currency is rejected here (a finance-recorded bank transfer can still settle
    the order through the same verification path).
    """
    from apps.export.models import ExportOrderStatus

    from .payment_models import PaymentPurpose

    if purpose is None:
        purpose = PaymentPurpose.FULL
    if not paystack.is_enabled():
        raise ValidationError("Online card payment is not currently available.")
    if export_order.customer_id != getattr(actor, "id", None) and not has_capability(
        actor, Capability.FINANCE_MANAGE
    ):
        raise PermissionDenied("You cannot pay for this export order.")

    currency = configured_currency()
    with transaction.atomic():
        export_order = type(export_order).objects.select_for_update().get(pk=export_order.pk)
        if export_order.status in {
            ExportOrderStatus.COMPLETED,
            ExportOrderStatus.CANCELLED,
        }:
            raise ValidationError("This export order can no longer be paid.")
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError("This export order has no amount to pay.")
        if export_order.currency.upper() != currency:
            raise ValidationError(
                f"This export order's currency ({export_order.currency}) is not supported "
                "for online payment."
            )
        existing = (
            Payment.objects.filter(
                export_order=export_order,
                provider=PaymentProvider.PAYSTACK,
                status__in=OPEN_PAYMENT_STATES,
                expected_amount=amount,
                purpose=purpose,
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            return existing
        payment = Payment.objects.create(
            export_order=export_order,
            customer=export_order.customer,
            reference=_generate_number("AS-PAY", Payment, field="reference"),
            provider=PaymentProvider.PAYSTACK,
            currency=export_order.currency,
            expected_amount=amount,
            purpose=purpose,
            status=PaymentState.PENDING,
        )

    try:
        data = paystack.initialize_transaction(
            email=export_order.customer.email,
            amount_kobo=paystack.to_kobo(amount),
            currency=export_order.currency,
            reference=payment.reference,
            callback_url=_export_callback_url(export_order, request),
            metadata={
                "export_order": export_order.reference,
                "payment_reference": payment.reference,
                "purpose": purpose,
                "customer_id": str(export_order.customer_id),
            },
            channels=[channel] if channel else None,
        )
    except paystack.PaystackError as exc:
        PaymentAttempt.objects.create(
            payment=payment,
            provider_reference=payment.reference,
            status=PaymentAttemptStatus.FAILED,
            failure_code=exc.code,
            failure_message=str(exc)[:500],
        )
        payment.status = PaymentState.FAILED
        payment.note = f"Initialisation failed: {exc.code}."
        payment.save(update_fields=["status", "note", "updated_at"])
        notify_safe(notifications.notify_payment_failed, payment)
        raise ValidationError("We could not start the payment. Please try again.") from exc

    attempt = PaymentAttempt.objects.create(
        payment=payment,
        provider_reference=str(data.get("reference") or payment.reference)[:120],
        authorization_url=str(data.get("authorization_url") or "")[:500],
        access_code=str(data.get("access_code") or "")[:120],
        status=PaymentAttemptStatus.INITIALIZED,
    )
    payment.status = PaymentState.PROCESSING
    payment.provider_reference = attempt.provider_reference
    payment.method = _method_for_channel(channel)
    payment.save(update_fields=["status", "provider_reference", "method", "updated_at"])
    record_audit(
        actor=actor,
        action="export.order.payment_initialized",
        target=payment,
        after={"reference": payment.reference, "amount": str(payment.expected_amount)},
        request=request,
    )
    notify_safe(notifications.notify_payment_initiated, payment)
    return payment


def _training_callback_url(enrollment, request=None) -> str:
    from django.urls import reverse

    path = reverse("training:payment_callback", kwargs={"reference": enrollment.reference})
    if request is not None:
        return request.build_absolute_uri(path)
    configured = getattr(settings, "PAYSTACK_CALLBACK_URL", "") or ""
    if configured:
        return configured
    hosts = getattr(settings, "ALLOWED_HOSTS", []) or []
    scheme = "http" if getattr(settings, "DEBUG", False) else "https"
    return f"{scheme}://{hosts[0]}{path}" if hosts else path


def initialize_training_payment(
    enrollment, *, actor, amount=None, purpose=None, request=None, channel: str = ""
) -> Payment:
    """Create a Paystack checkout to pay a training enrolment fee.

    Only the student (or finance) may pay. The amount defaults to the outstanding
    balance and is always the verified amount later, never a client figure.
    """
    from .payment_models import PaymentPurpose

    if purpose is None:
        purpose = PaymentPurpose.FULL
    if not paystack.is_enabled():
        raise ValidationError("Online card payment is not currently available.")
    if enrollment.student_id != getattr(actor, "id", None) and not has_capability(
        actor, Capability.FINANCE_MANAGE
    ):
        raise PermissionDenied("You cannot pay for this enrolment.")

    currency = configured_currency()
    with transaction.atomic():
        enrollment = (
            type(enrollment)
            .objects.select_for_update()
            .select_related("session")
            .get(pk=enrollment.pk)
        )
        if enrollment.status in {"cancelled", "completed"}:
            raise ValidationError("This enrolment can no longer be paid.")
        fee = enrollment.session.fee or Decimal("0")
        if amount is None:
            amount = fee - (enrollment.amount_paid or Decimal("0"))
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError("This enrolment has no amount to pay.")
        if enrollment.session.currency.upper() != currency:
            raise ValidationError(
                f"This session's currency ({enrollment.session.currency}) is not supported "
                "for online payment."
            )
        existing = (
            Payment.objects.filter(
                training_enrollment=enrollment,
                provider=PaymentProvider.PAYSTACK,
                status__in=OPEN_PAYMENT_STATES,
                expected_amount=amount,
                purpose=purpose,
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            return existing
        payment = Payment.objects.create(
            training_enrollment=enrollment,
            customer=enrollment.student,
            reference=_generate_number("AS-PAY", Payment, field="reference"),
            provider=PaymentProvider.PAYSTACK,
            currency=enrollment.session.currency,
            expected_amount=amount,
            purpose=purpose,
            status=PaymentState.PENDING,
        )

    try:
        data = paystack.initialize_transaction(
            email=enrollment.student.email,
            amount_kobo=paystack.to_kobo(amount),
            currency=enrollment.session.currency,
            reference=payment.reference,
            callback_url=_training_callback_url(enrollment, request),
            metadata={
                "training_enrollment": enrollment.reference,
                "payment_reference": payment.reference,
                "purpose": purpose,
                "customer_id": str(enrollment.student_id),
            },
            channels=[channel] if channel else None,
        )
    except paystack.PaystackError as exc:
        PaymentAttempt.objects.create(
            payment=payment,
            provider_reference=payment.reference,
            status=PaymentAttemptStatus.FAILED,
            failure_code=exc.code,
            failure_message=str(exc)[:500],
        )
        payment.status = PaymentState.FAILED
        payment.note = f"Initialisation failed: {exc.code}."
        payment.save(update_fields=["status", "note", "updated_at"])
        notify_safe(notifications.notify_payment_failed, payment)
        raise ValidationError("We could not start the payment. Please try again.") from exc

    attempt = PaymentAttempt.objects.create(
        payment=payment,
        provider_reference=str(data.get("reference") or payment.reference)[:120],
        authorization_url=str(data.get("authorization_url") or "")[:500],
        access_code=str(data.get("access_code") or "")[:120],
        status=PaymentAttemptStatus.INITIALIZED,
    )
    payment.status = PaymentState.PROCESSING
    payment.provider_reference = attempt.provider_reference
    payment.method = _method_for_channel(channel)
    payment.save(update_fields=["status", "provider_reference", "method", "updated_at"])
    record_audit(
        actor=actor,
        action="training.enrollment.payment_initialized",
        target=payment,
        after={"reference": payment.reference, "amount": str(payment.expected_amount)},
        request=request,
    )
    notify_safe(notifications.notify_payment_initiated, payment)
    return payment


# ---------------------------------------------------------------------------
# Paystack verification
# ---------------------------------------------------------------------------


def verify_payment(payment: Payment, *, request=None, source: str = "verify") -> Payment:
    """Authoritatively verify a payment server-side and settle it if valid.

    Never trusts the browser redirect: the status is re-fetched from Paystack.
    """
    if payment.status in REFUNDABLE_PAYMENT_STATES:
        return payment
    if not paystack.is_enabled():
        raise ValidationError("Payment verification is not currently available.")
    reference = payment.provider_reference or payment.reference
    data = paystack.verify_transaction(reference)
    return _apply_verification(payment, data, source=source, request=request)


def _apply_verification(
    payment: Payment, data: dict, *, source: str = "verify", request=None
) -> Payment:
    """Apply an authoritative provider transaction payload to a payment."""
    notified: str | None = None
    receipt_created = None

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        previous_status = payment.status
        if payment.status in REFUNDABLE_PAYMENT_STATES:
            return payment

        status = str(data.get("status", "")).lower()
        raw_amount = data.get("amount")
        provider_amount = paystack.from_kobo(raw_amount if raw_amount is not None else 0)
        provider_currency = str(data.get("currency") or payment.currency).upper()
        provider_reference = str(
            data.get("id")
            or data.get("reference")
            or payment.provider_reference
            or payment.reference
        )
        payment.provider_reference = provider_reference[:120]
        payment.channel = str(data.get("channel") or payment.channel)[:40]

        if status == "failed":
            payment.status = PaymentState.FAILED
            payment.save(update_fields=["status", "provider_reference", "channel", "updated_at"])
            if previous_status not in {PaymentState.FAILED, PaymentState.ABANDONED}:
                notified = "failed"
        elif status in {"abandoned", "reversed", "cancelled"}:
            payment.status = PaymentState.ABANDONED
            payment.save(update_fields=["status", "provider_reference", "channel", "updated_at"])
            if previous_status not in {PaymentState.FAILED, PaymentState.ABANDONED}:
                notified = "failed"
        elif status != "success":
            payment.save(update_fields=["provider_reference", "channel", "updated_at"])
        elif provider_currency != payment.currency.upper():
            payment.status = PaymentState.FAILED
            payment.requires_review = True
            payment.review_reason = f"Currency mismatch: provider returned {provider_currency}."
            payment.save(
                update_fields=[
                    "provider_reference",
                    "channel",
                    "status",
                    "requires_review",
                    "review_reason",
                    "updated_at",
                ]
            )
            record_audit(
                actor=None,
                action="orders.payment.verification_rejected",
                target=payment,
                after={"reason": "currency_mismatch", "provider_currency": provider_currency},
                request=request,
            )
        elif provider_amount < payment.expected_amount:
            payment.status = PaymentState.FAILED
            payment.requires_review = True
            payment.review_reason = (
                f"Underpaid: received {provider_amount}, expected {payment.expected_amount}."
            )
            payment.save(
                update_fields=[
                    "provider_reference",
                    "channel",
                    "status",
                    "requires_review",
                    "review_reason",
                    "updated_at",
                ]
            )
            record_audit(
                actor=None,
                action="orders.payment.verification_rejected",
                target=payment,
                after={"reason": "amount_mismatch", "received": str(provider_amount)},
                request=request,
            )
        else:
            if provider_amount > payment.expected_amount:
                payment.requires_review = True
                payment.review_reason = (
                    f"Overpaid: received {provider_amount}, expected {payment.expected_amount}."
                )
            payment.status = PaymentState.PAID
            payment.verified_amount = provider_amount
            payment.verified_at = timezone.now()
            payment.save(
                update_fields=[
                    "provider_reference",
                    "channel",
                    "status",
                    "verified_amount",
                    "verified_at",
                    "requires_review",
                    "review_reason",
                    "updated_at",
                ]
            )

            if payment.order_id is not None:
                order = Order.objects.select_for_update().get(pk=payment.order_id)
                if order.payment_status != PaymentStatus.PAID:
                    if order.status in PAYABLE_ORDER_STATUSES:
                        services.settle_order(
                            order,
                            actor=None,
                            reference=payment.reference,
                            note=f"Payment verified via {payment.get_provider_display()}.",
                            request=request,
                        )
                        invoice = Invoice.objects.filter(order=order).first()
                        if invoice is not None and invoice.status != InvoiceState.PAID:
                            invoice.status = InvoiceState.PAID
                            invoice.save(update_fields=["status", "updated_at"])
                    else:
                        reason = f"Payment captured for an order in '{order.get_status_display()}'."
                        payment.requires_review = True
                        payment.review_reason = f"{payment.review_reason} {reason}".strip()
                        payment.save(
                            update_fields=["requires_review", "review_reason", "updated_at"]
                        )
                        record_audit(
                            actor=None,
                            action="orders.payment.needs_review",
                            target=payment,
                            after={"order": order.number, "order_status": order.status},
                            request=request,
                        )
            elif payment.service_quotation_id is not None:
                # Reuse the shared idempotent settlement path for service quotations.
                from apps.services import payments as service_payments

                service_payments.settle_quotation_payment(payment, source=source, request=request)
            elif payment.export_order_id is not None:
                # Reuse the shared idempotent settlement path for export orders.
                from apps.export import payments as export_payments

                export_payments.settle_export_payment(payment, source=source, request=request)
            elif payment.training_enrollment_id is not None:
                # Reuse the shared idempotent settlement path for training enrolments.
                from apps.training import payments as training_payments

                training_payments.settle_training_payment(payment, source=source, request=request)

            receipt, created = _ensure_receipt(payment)
            receipt_created = receipt if created else None

            record_audit(
                actor=None,
                action="orders.payment.verified",
                target=payment,
                after={
                    "reference": payment.reference,
                    "amount": str(payment.verified_amount),
                    "source": source,
                },
                request=request,
            )
            notified = "paid"

    if notified == "paid":
        notify_safe(notifications.notify_payment_verified, payment)
        notify_safe(notification_events.payment_verified, payment)
        if receipt_created is not None:
            notify_safe(notifications.notify_receipt_issued, receipt_created)
        if payment.requires_review:
            notify_safe(notifications.notify_payment_needs_review, payment)
    elif notified == "failed":
        notify_safe(notifications.notify_payment_failed, payment)
    return payment


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def process_webhook(
    *, raw_body: bytes, signature: str, provider: str = PaymentProvider.PAYSTACK, request=None
) -> PaymentWebhookEvent:
    """Verify, deduplicate and apply one provider webhook delivery."""
    if not paystack.verify_webhook_signature(raw_body, signature):
        raise PermissionDenied("Invalid webhook signature.")
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("Malformed webhook payload.") from exc
    if not isinstance(event, dict):
        raise ValidationError("Malformed webhook payload.")

    event_type = str(event.get("event", ""))[:80]
    event_id = str(event.get("id") or "") or hashlib.sha256(raw_body).hexdigest()

    record, created = PaymentWebhookEvent.objects.get_or_create(
        provider=provider,
        event_id=event_id[:160],
        defaults={
            "event_type": event_type,
            "payload": redact(event),
            "status": WebhookEventStatus.RECEIVED,
        },
    )
    if not created and record.status == WebhookEventStatus.PROCESSED:
        return record  # duplicate delivery — already handled

    # Operational kill switch: when the integration is disabled the event is
    # still verified and recorded for audit/forensics, but never applied — so a
    # stale secret key cannot keep settling orders or committing stock.
    if not paystack.is_enabled():
        PaymentWebhookEvent.objects.filter(pk=record.pk).update(
            status=WebhookEventStatus.IGNORED,
            processed_at=timezone.now(),
            error="Paystack integration disabled; event recorded but not applied.",
        )
        record.refresh_from_db()
        return record

    try:
        outcome = _handle_event(record, event_type, event)
    except Exception as exc:
        PaymentWebhookEvent.objects.filter(pk=record.pk).update(
            status=WebhookEventStatus.FAILED,
            error=str(exc)[:500],
            attempts=record.attempts + 1,
        )
        raise
    PaymentWebhookEvent.objects.filter(pk=record.pk).update(
        status=WebhookEventStatus.PROCESSED if outcome != "ignored" else WebhookEventStatus.IGNORED,
        processed_at=timezone.now(),
        attempts=record.attempts + 1,
    )
    record.refresh_from_db()
    return record


def _handle_event(record: PaymentWebhookEvent, event_type: str, event: dict) -> str:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if event_type == "charge.success":
        payment = _find_payment(data)
        if payment is None:
            raise ValidationError("No matching payment for charge.success.")
        record.payment = payment
        record.save(update_fields=["payment", "updated_at"])
        _apply_verification(payment, data, source="webhook")
        return "processed"
    if event_type == "charge.failed":
        payment = _find_payment(data)
        if payment is not None:
            record.payment = payment
            record.save(update_fields=["payment", "updated_at"])
            _apply_verification(payment, data, source="webhook")
        return "processed"
    if event_type in {"refund.processed", "refund.pending", "refund.failed"}:
        refund = _find_refund(data)
        if refund is None:
            return "ignored"  # out-of-order / unknown — reconciliation will retry
        if event_type == "refund.processed":
            complete_refund(
                refund,
                provider_status=RefundProviderState.SUCCESS,
                provider_reference=str(data.get("id") or refund.provider_reference),
            )
        elif event_type == "refund.failed":
            fail_refund(refund, reason="Provider reported the refund failed.")
        return "processed"
    return "ignored"


def _find_payment(data: dict) -> Payment | None:
    reference = str(data.get("reference") or "")
    provider_reference = str(data.get("id") or "")
    queryset = Payment.objects.filter(provider=PaymentProvider.PAYSTACK)
    payment = queryset.filter(reference=reference).first() if reference else None
    if payment is None and provider_reference:
        payment = queryset.filter(provider_reference=provider_reference).first()
    if payment is None:
        metadata = data.get("metadata") or {}
        ref = str(metadata.get("payment_reference") or "")
        if ref:
            payment = queryset.filter(reference=ref).first()
    return payment


def _find_refund(data: dict) -> Refund | None:
    provider_reference = str(data.get("id") or "")
    refund = (
        Refund.objects.filter(provider_reference=provider_reference).first()
        if provider_reference
        else None
    )
    if refund is None:
        transaction_id = str(data.get("transaction") or "")
        if transaction_id:
            payment = Payment.objects.filter(provider_reference=transaction_id).first()
            if payment is not None:
                refund = (
                    payment.refunds.filter(
                        status__in=[
                            RefundState.REQUESTED,
                            RefundState.APPROVED,
                            RefundState.PROCESSING,
                        ]
                    )
                    .order_by("-created_at")
                    .first()
                )
    return refund


# ---------------------------------------------------------------------------
# Bank transfers
# ---------------------------------------------------------------------------


def create_bank_account(
    *,
    actor,
    bank_name: str,
    account_name: str,
    account_number: str,
    currency: str = "NGN",
    instructions: str = "",
    sort_order: int = 0,
    request=None,
) -> CompanyBankAccount:
    if not has_capability(actor, Capability.FINANCE_MANAGE):
        raise PermissionDenied("You are not authorised to configure bank accounts.")
    account = CompanyBankAccount.objects.create(
        bank_name=bank_name.strip(),
        account_name=account_name.strip(),
        account_number=account_number.strip(),
        currency=(currency or "NGN").upper(),
        instructions=instructions,
        sort_order=sort_order,
    )
    record_audit(
        actor=actor,
        action="orders.bank_account.create",
        target=account,
        after={"bank_name": account.bank_name, "account_number": account.account_number},
        request=request,
    )
    return account


def update_bank_account(
    account: CompanyBankAccount, *, actor, request=None, **fields
) -> CompanyBankAccount:
    if not has_capability(actor, Capability.FINANCE_MANAGE):
        raise PermissionDenied("You are not authorised to configure bank accounts.")
    for name, value in fields.items():
        setattr(account, name, value)
    account.save()
    record_audit(
        actor=actor,
        action="orders.bank_account.update",
        target=account,
        after={key: str(value) for key, value in fields.items()},
        request=request,
    )
    return account


def set_bank_account_active(account: CompanyBankAccount, *, actor, is_active: bool, request=None):
    if not has_capability(actor, Capability.FINANCE_MANAGE):
        raise PermissionDenied("You are not authorised to configure bank accounts.")
    account.is_active = is_active
    account.save(update_fields=["is_active", "updated_at"])
    record_audit(
        actor=actor,
        action="orders.bank_account.toggle",
        target=account,
        after={"is_active": is_active},
        request=request,
    )
    return account


def record_bank_transfer(
    order,
    *,
    actor,
    bank_account: CompanyBankAccount,
    transfer_reference: str,
    claimed_amount,
    proof=None,
    transfer_date=None,
    request=None,
) -> BankTransferSubmission:
    """Record a customer's claimed manual transfer (never confirms settlement)."""
    if order.user_id != getattr(actor, "id", None) and not has_capability(
        actor, Capability.ORDERS_MANAGE
    ):
        raise PermissionDenied("You cannot submit a transfer for this order.")
    if bank_account is None or not bank_account.is_active:
        raise ValidationError("Choose an active company bank account.")
    reference = (transfer_reference or "").strip()
    if not reference:
        raise ValidationError("Enter the transfer reference from your bank.")
    amount = _money(claimed_amount)
    if amount <= 0:
        raise ValidationError("Enter the amount you transferred.")

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.payment_status == PaymentStatus.PAID:
            raise ValidationError("This order is already paid.")
        if order.status not in PAYABLE_ORDER_STATUSES:
            raise ValidationError("This order can no longer accept a bank transfer.")
        if not order.reservations.filter(status=ReservationStatus.ACTIVE).exists():
            raise ValidationError("Your stock reservation has expired. Please place a new order.")
        # A single bank transaction must never settle more than one order.
        if BankTransferSubmission.objects.filter(
            transfer_reference=reference,
            account_number_snapshot=bank_account.account_number,
            status=BankTransferStatus.APPROVED,
        ).exists():
            raise ValidationError("This transfer reference has already been used.")

        payment = (
            Payment.objects.filter(order=order, provider=PaymentProvider.BANK_TRANSFER)
            .exclude(status__in=REFUNDABLE_PAYMENT_STATES)
            .order_by("-created_at")
            .first()
        )
        if payment is None:
            payment = Payment.objects.create(
                order=order,
                customer=order.user,
                reference=_generate_number("AS-BT", Payment, field="reference"),
                provider=PaymentProvider.BANK_TRANSFER,
                method="bank",
                currency=order.currency,
                expected_amount=order.grand_total,
                status=PaymentState.PROCESSING,
            )
        submission = BankTransferSubmission.objects.create(
            payment=payment,
            customer=order.user,
            bank_account=bank_account,
            bank_name_snapshot=bank_account.bank_name,
            account_number_snapshot=bank_account.account_number,
            transfer_reference=reference,
            claimed_amount=amount,
            transfer_date=transfer_date,
            proof=proof,
            status=BankTransferStatus.SUBMITTED,
        )
        if order.status == OrderStatus.PENDING_PAYMENT:
            services.transition_order(
                order,
                to_status=OrderStatus.PAYMENT_REVIEW,
                actor=actor,
                reason="Bank transfer submitted.",
                request=request,
            )
        record_audit(
            actor=actor,
            action="orders.bank_transfer.submit",
            target=submission,
            after={"reference": reference, "amount": str(amount)},
            request=request,
        )
    notify_safe(notifications.notify_bank_transfer_under_review, submission)
    return submission


def review_bank_transfer(
    submission: BankTransferSubmission,
    *,
    actor,
    approve: bool,
    notes: str = "",
    settlement_confirmed: bool = False,
    request=None,
) -> BankTransferSubmission:
    """Finance reviews a submission. Uploaded proof alone is never enough."""
    if not has_capability(actor, Capability.FINANCE_MANAGE):
        raise PermissionDenied("You are not authorised to review bank transfers.")

    with transaction.atomic():
        submission = BankTransferSubmission.objects.select_for_update().get(pk=submission.pk)
        if submission.status in {BankTransferStatus.APPROVED, BankTransferStatus.REJECTED}:
            raise ValidationError("This submission has already been reviewed.")

        if approve:
            if not settlement_confirmed:
                raise ValidationError(
                    "Confirm the funds were received in the bank statement before approving."
                )
            payment = Payment.objects.select_for_update().get(pk=submission.payment_id)
            if submission.claimed_amount != payment.expected_amount:
                raise ValidationError(
                    "The claimed amount does not match the order total. Reject or correct it."
                )
            if (
                BankTransferSubmission.objects.filter(
                    transfer_reference=submission.transfer_reference,
                    account_number_snapshot=submission.account_number_snapshot,
                    status=BankTransferStatus.APPROVED,
                )
                .exclude(pk=submission.pk)
                .exists()
            ):
                raise ValidationError("This transfer has already settled another order.")

            submission.status = BankTransferStatus.APPROVED
            submission.settlement_confirmed = True
            submission.reviewed_by = actor
            submission.reviewed_at = timezone.now()
            submission.review_notes = notes
            submission.save(
                update_fields=[
                    "status",
                    "settlement_confirmed",
                    "reviewed_by",
                    "reviewed_at",
                    "review_notes",
                    "updated_at",
                ]
            )
            payment.status = PaymentState.PAID
            payment.verified_amount = submission.claimed_amount
            payment.verified_at = timezone.now()
            payment.method = "bank"
            payment.save(
                update_fields=["status", "verified_amount", "verified_at", "method", "updated_at"]
            )
            services.settle_order(
                submission.payment.order,
                actor=actor,
                reference=submission.transfer_reference,
                note="Bank transfer settlement confirmed by finance.",
                request=request,
            )
            invoice = Invoice.objects.filter(order=submission.payment.order).first()
            if invoice is not None and invoice.status != InvoiceState.PAID:
                invoice.status = InvoiceState.PAID
                invoice.save(update_fields=["status", "updated_at"])
            _ensure_receipt(payment)
            record_audit(
                actor=actor,
                action="orders.bank_transfer.approve",
                target=submission,
                after={"reference": submission.transfer_reference},
                request=request,
            )
        else:
            submission.status = BankTransferStatus.REJECTED
            submission.reviewed_by = actor
            submission.reviewed_at = timezone.now()
            submission.review_notes = notes
            submission.save(
                update_fields=["status", "reviewed_by", "reviewed_at", "review_notes", "updated_at"]
            )
            payment = Payment.objects.filter(pk=submission.payment_id).first()
            if payment is not None and payment.status not in REFUNDABLE_PAYMENT_STATES:
                payment.status = PaymentState.FAILED
                payment.note = "Bank transfer rejected by finance."
                payment.save(update_fields=["status", "note", "updated_at"])
            record_audit(
                actor=actor,
                action="orders.bank_transfer.reject",
                target=submission,
                after={"reference": submission.transfer_reference},
                request=request,
            )
    notify_safe(notifications.notify_bank_transfer_reviewed, submission)
    return submission


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------


def request_refund(payment: Payment, *, actor, amount, reason: str = "", request=None) -> Refund:
    if not has_capability(actor, Capability.FINANCE_MANAGE):
        raise PermissionDenied("You are not authorised to request refunds.")
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status not in REFUNDABLE_PAYMENT_STATES:
            raise ValidationError("Only settled payments can be refunded.")
        value = _money(amount)
        if value <= 0:
            raise ValidationError("Enter a refund amount greater than zero.")
        settled = payment.settled_amount
        committed = payment.refunds.filter(
            status__in=[
                RefundState.REQUESTED,
                RefundState.APPROVED,
                RefundState.PROCESSING,
                RefundState.COMPLETED,
            ]
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        if value + committed > settled:
            remaining = settled - committed
            raise ValidationError(
                f"Refund exceeds the refundable balance ({remaining} {payment.currency} left)."
            )
        refund = Refund.objects.create(
            payment=payment,
            reference=_generate_number("AS-RF", Refund, field="reference"),
            amount=value,
            reason=reason,
            status=RefundState.REQUESTED,
            requested_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
        record_audit(
            actor=actor,
            action="orders.refund.request",
            target=refund,
            after={"reference": refund.reference, "amount": str(value)},
            request=request,
        )
    notify_safe(notifications.notify_refund_requested, refund)
    return refund


def approve_refund(refund: Refund, *, actor, request=None) -> Refund:
    if not has_capability(actor, Capability.FINANCE_MANAGE):
        raise PermissionDenied("You are not authorised to approve refunds.")
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        if refund.status != RefundState.REQUESTED:
            raise ValidationError("This refund is not awaiting approval.")
        refund.status = RefundState.APPROVED
        refund.approved_by = actor if getattr(actor, "is_authenticated", False) else None
        refund.save(update_fields=["status", "approved_by", "updated_at"])
        record_audit(
            actor=actor,
            action="orders.refund.approve",
            target=refund,
            after={"reference": refund.reference},
            request=request,
        )

    payment = refund.payment
    if payment.provider == PaymentProvider.PAYSTACK and paystack.is_enabled():
        settled = payment.settled_amount
        try:
            data = paystack.refund_transaction(
                transaction=payment.provider_reference or payment.reference,
                amount_kobo=None if refund.amount >= settled else paystack.to_kobo(refund.amount),
                merchant_note=refund.reason[:200],
            )
        except paystack.PaystackError as exc:
            refund.status = RefundState.FAILED
            refund.provider_status = RefundProviderState.FAILED
            refund.failure_reason = str(exc)[:500]
            refund.save(update_fields=["status", "provider_status", "failure_reason", "updated_at"])
            raise ValidationError("Could not initiate the refund with Paystack.") from exc
        refund.status = RefundState.PROCESSING
        refund.provider_status = RefundProviderState.PROCESSING
        refund.provider_reference = str(data.get("id") or "")[:120]
        refund.save(update_fields=["status", "provider_status", "provider_reference", "updated_at"])
    else:
        # Offline/bank-transfer refunds are settled manually by finance.
        refund.status = RefundState.PROCESSING
        refund.provider_status = RefundProviderState.PENDING
        refund.save(update_fields=["status", "provider_status", "updated_at"])
    return refund


def complete_refund(
    refund: Refund,
    *,
    provider_status: str = RefundProviderState.SUCCESS,
    provider_reference: str = "",
    request=None,
) -> Refund:
    """Mark a refund completed after provider/bank settlement is confirmed."""
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        if refund.status == RefundState.COMPLETED:
            return refund
        refund.status = RefundState.COMPLETED
        refund.provider_status = provider_status or RefundProviderState.SUCCESS
        refund.processed_at = timezone.now()
        if provider_reference:
            refund.provider_reference = provider_reference[:120]
        refund.failure_reason = ""
        refund.save(
            update_fields=[
                "status",
                "provider_status",
                "processed_at",
                "provider_reference",
                "failure_reason",
                "updated_at",
            ]
        )

        payment = Payment.objects.select_for_update().get(pk=refund.payment_id)
        settled = payment.settled_amount
        total = payment.refunds.filter(status=RefundState.COMPLETED).aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0.00")
        order = (
            Order.objects.select_for_update().get(pk=payment.order_id) if payment.order_id else None
        )
        if total >= settled:
            payment.status = PaymentState.REFUNDED
            if order is not None:
                order.payment_status = "refunded"
                order.save(update_fields=["payment_status", "updated_at"])
                if order.status in _REFUNDABLE_ORDER_STATUSES:
                    try:
                        services.transition_order(
                            order,
                            to_status=OrderStatus.REFUNDED,
                            actor=None,
                            reason="Payment fully refunded.",
                            request=request,
                        )
                    except ValidationError:  # pragma: no cover - defensive
                        pass
        else:
            payment.status = PaymentState.PARTIALLY_REFUNDED
            if order is not None:
                order.payment_status = "partially_refunded"
                order.save(update_fields=["payment_status", "updated_at"])
        payment.save(update_fields=["status", "updated_at"])
        record_audit(
            actor=None,
            action="orders.refund.completed",
            target=refund,
            after={"reference": refund.reference, "amount": str(refund.amount)},
            request=request,
        )
    notify_safe(notifications.notify_refund_completed, refund)
    return refund


def fail_refund(refund: Refund, *, reason: str = "", request=None) -> Refund:
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        if refund.status == RefundState.COMPLETED:
            return refund
        refund.status = RefundState.FAILED
        refund.provider_status = RefundProviderState.FAILED
        refund.failure_reason = reason[:500]
        refund.save(update_fields=["status", "provider_status", "failure_reason", "updated_at"])
        record_audit(
            actor=None,
            action="orders.refund.failed",
            target=refund,
            after={"reference": refund.reference, "reason": reason[:200]},
            request=request,
        )
    return refund


# ---------------------------------------------------------------------------
# Invoices & receipts
# ---------------------------------------------------------------------------


def generate_invoice(order, *, request=None, notify: bool = True) -> Invoice:
    """Create the (unpaid) invoice for an order; idempotent per order."""
    from .selectors import invoice_billing_snapshot

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        invoice = Invoice.objects.filter(order=order).first()
        if invoice is not None:
            return invoice
        snapshot = invoice_billing_snapshot(order)
        invoice = Invoice.objects.create(
            order=order,
            number=_generate_number("AS-INV", Invoice, field="number"),
            currency=order.currency,
            customer_name=snapshot["name"],
            customer_email=snapshot["email"],
            customer_phone=snapshot["phone"],
            billing_address=snapshot["address"],
            subtotal=order.subtotal,
            shipping_amount=order.shipping_amount,
            discount_amount=order.discount_amount,
            tax_amount=order.tax_amount,
            total=order.grand_total,
            status=(
                InvoiceState.PAID
                if order.payment_status == PaymentStatus.PAID
                else InvoiceState.UNPAID
            ),
            issued_at=timezone.now(),
        )
    if notify:
        notify_safe(notifications.notify_invoice_issued, invoice)
    return invoice


def _ensure_receipt(payment: Payment) -> tuple[Receipt, bool]:
    receipt = Receipt.objects.filter(payment=payment).first()
    if receipt is not None:
        return receipt, False
    receipt = Receipt.objects.create(
        payment=payment,
        number=_generate_number("AS-RC", Receipt, field="number"),
        amount=payment.verified_amount or payment.expected_amount,
        currency=payment.currency,
        issued_at=timezone.now(),
    )
    return receipt, True


def issue_receipt(payment: Payment, *, notify: bool = True) -> Receipt:
    """Issue the receipt for a verified payment (idempotent)."""
    if payment.status not in REFUNDABLE_PAYMENT_STATES:
        raise ValidationError("Receipts are issued only for verified payments.")
    receipt, created = _ensure_receipt(payment)
    if created and notify:
        notify_safe(notifications.notify_receipt_issued, receipt)
    return receipt


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile_payment(payment: Payment) -> dict:
    """Re-verify a single open Paystack payment against the provider."""
    if payment.provider != PaymentProvider.PAYSTACK:
        return {"reference": payment.reference, "action": "skipped", "reason": "not_paystack"}
    if payment.status not in OPEN_PAYMENT_STATES:
        return {"reference": payment.reference, "action": "skipped", "reason": "settled"}
    if not paystack.is_enabled():
        raise ValidationError("Paystack is not enabled; reconciliation skipped.")
    before = payment.status
    data = paystack.verify_transaction(payment.provider_reference or payment.reference)
    _apply_verification(payment, data, source="reconcile")
    payment.refresh_from_db()
    return {
        "reference": payment.reference,
        "action": "verified" if payment.status != before else "unchanged",
        "before": before,
        "after": payment.status,
    }


def reconcile_pending_payments(*, older_than_minutes: int = 15, limit: int = 100) -> dict:
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
    queryset = Payment.objects.filter(
        provider=PaymentProvider.PAYSTACK,
        status__in=OPEN_PAYMENT_STATES,
        created_at__lte=cutoff,
    ).order_by("created_at")[:limit]
    summary = {"checked": 0, "verified": 0, "unchanged": 0, "errors": 0}
    for payment in queryset:
        try:
            result = reconcile_payment(payment)
        except Exception as exc:  # network/provider errors are expected
            logger.warning(
                "Reconciliation failed for %s: %s", payment.reference, type(exc).__name__
            )
            result = {"action": "error"}
        if result.get("action") == "verified":
            summary["verified"] += 1
        elif result.get("action") == "error":
            summary["errors"] += 1
        else:
            summary["unchanged"] += 1
        summary["checked"] += 1
    return summary


def reconcile_refunds(*, limit: int = 100) -> dict:
    """Flag stale in-flight refunds for finance attention (manual reconciliation)."""
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=3)
    stale = list(
        Refund.objects.filter(
            status__in=[RefundState.APPROVED, RefundState.PROCESSING],
            updated_at__lte=cutoff,
        )[:limit]
    )
    for refund in stale:
        refund.failure_reason = "Awaiting provider/bank settlement confirmation."
        refund.save(update_fields=["failure_reason", "updated_at"])
    return {"checked": len(stale), "flagged": len(stale)}


def reconcile_all() -> dict:
    return {
        "payments": reconcile_pending_payments(),
        "refunds": reconcile_refunds(),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def notify_safe(func, *args) -> None:
    """Call a notification helper, swallowing errors so flows never break."""
    try:
        func(*args)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Notification helper %s failed.", getattr(func, "__name__", func))

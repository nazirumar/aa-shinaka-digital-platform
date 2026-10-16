"""Service-quotation payment settlement.

Phase 6 owns provider verification and reconciliation in
:mod:`apps.orders.payments`. When a *verified* payment targets a
:class:`~apps.services.models.ServiceQuotation` (``payment.service_quotation``),
the idempotent branch there calls :func:`settle_quotation_payment`, which marks
the quotation paid and activates the downstream service.

A browser callback alone never reaches this function — only a verified provider
response or a finance approval does. The amount settled is the verified amount
recorded by Phase 6, never a client-supplied figure.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit

from . import notifications
from .models import QuotationPaymentStatus, QuotationStatus, ServiceQuotation


@transaction.atomic
def settle_quotation_payment(payment, *, source: str = "", request=None) -> ServiceQuotation | None:
    """Mark a quotation paid after a verified payment (idempotent).

    Returns the quotation, or ``None`` if the payment does not target one.
    """
    if getattr(payment, "service_quotation_id", None) is None:
        return None

    quotation = ServiceQuotation.objects.select_for_update().get(pk=payment.service_quotation_id)
    if quotation.payment_status == QuotationPaymentStatus.PAID:
        return quotation  # already settled — safe to call twice

    quotation.payment_status = QuotationPaymentStatus.PAID
    quotation.paid_at = timezone.now()
    update_fields = ["payment_status", "paid_at", "updated_at"]
    if quotation.status == QuotationStatus.ISSUED:
        # Paying an issued quotation is an implicit acceptance.
        quotation.status = QuotationStatus.ACCEPTED
        quotation.decided_at = timezone.now()
        update_fields += ["status", "decided_at"]
    quotation.save(update_fields=update_fields)

    record_audit(
        actor=None,
        action="services.quotation.paid",
        target=quotation,
        after={
            "reference": quotation.reference,
            "payment": payment.reference,
            "source": source or "provider",
        },
        request=request,
    )

    from .services import activate_paid_service

    activate_paid_service(quotation)

    notifications.notify_once(
        event="quotation_paid",
        dedupe_key=f"quotation-paid:{quotation.pk}",
        to=getattr(quotation.customer, "email", ""),
        subject=f"Payment received for quotation {quotation.reference}",
        heading="Payment received",
        intro=(
            f"We verified your payment of {payment.currency} "
            f"{payment.verified_amount or payment.expected_amount} for quotation "
            f"{quotation.reference}."
        ),
    )
    return quotation

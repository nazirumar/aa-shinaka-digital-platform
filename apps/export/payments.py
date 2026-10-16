"""Export-order payment settlement (Task 9).

Phase 6 owns provider verification and reconciliation in
:mod:`apps.orders.payments`. When a *verified* payment targets an
:class:`~apps.export.models.ExportOrder` (``payment.export_order``), the
idempotent branch there calls :func:`settle_export_payment`, which applies the
verified amount to the order and advances it to *payment verified* once the
required deposit (or full amount) is met.

A browser callback alone never reaches this function — only a verified provider
response or a finance reconciliation does. The amount settled is the verified
amount recorded by Phase 6, never a client-supplied figure.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.orders.payment_models import Payment

from . import services
from .models import ExportOrder


@transaction.atomic
def settle_export_payment(
    payment: Payment, *, source: str = "", request=None
) -> ExportOrder | None:
    """Apply a verified payment to its export order (idempotent).

    Returns the order, or ``None`` if the payment does not target one. Called
    only from the single Phase 6 verification path, which already guards against
    re-applying an already-settled payment.
    """
    if getattr(payment, "export_order_id", None) is None:
        return None

    order = ExportOrder.objects.select_for_update().get(pk=payment.export_order_id)
    amount = (
        payment.verified_amount if payment.verified_amount is not None else payment.expected_amount
    )
    services.record_verified_payment(
        order, amount=Decimal(str(amount)), actor=None, payment=payment
    )
    order.refresh_from_db()
    return order

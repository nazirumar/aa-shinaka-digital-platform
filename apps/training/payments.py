"""Training-enrolment payment settlement (Task 6).

Phase 6 owns provider verification and reconciliation in
:mod:`apps.orders.payments`. When a *verified* payment targets an
:class:`~apps.training.models.Enrollment` (``payment.training_enrollment``), the
idempotent branch there calls :func:`settle_training_payment`, which applies the
verified amount to the enrolment and confirms it once the required fee (or
approved deposit) is met.

A browser callback alone never reaches this function — only a verified provider
response or a finance reconciliation does. The amount settled is the verified
amount recorded by Phase 6, never a client-supplied figure.
"""

from __future__ import annotations

from django.db import transaction

from . import services
from .models import Enrollment


@transaction.atomic
def settle_training_payment(payment, *, source: str = "", request=None):
    """Apply a verified payment to its training enrolment (idempotent).

    Returns the enrolment, or ``None`` if the payment does not target one.
    """
    if getattr(payment, "training_enrollment_id", None) is None:
        return None
    enrollment = Enrollment.objects.select_for_update().get(pk=payment.training_enrollment_id)
    return services.settle_enrollment_payment(
        enrollment, payment=payment, source=source, request=request
    )

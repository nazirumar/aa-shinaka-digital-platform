"""Celery tasks for the order app."""

from __future__ import annotations

from celery import shared_task

from . import payments, services


@shared_task(name="orders.expire_reservations")
def expire_reservations() -> int:
    """Release stock held by abandoned pending-payment orders.

    Scheduled via ``CELERY_BEAT_SCHEDULE``; the same logic is exposed as the
    ``expire_orders`` management command for environments without Celery beat.
    """
    return services.expire_orders()


@shared_task(name="orders.reconcile_payments")
def reconcile_payments() -> dict:
    """Re-verify in-flight Paystack payments and flag stale refunds.

    Scheduled via ``CELERY_BEAT_SCHEDULE``; the same logic is exposed as the
    ``reconcile_payments`` management command for deployments without beat.
    """
    return payments.reconcile_pending_payments()

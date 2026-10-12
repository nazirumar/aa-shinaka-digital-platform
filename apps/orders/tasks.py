"""Celery tasks for the order app."""

from __future__ import annotations

from celery import shared_task

from . import services


@shared_task(name="orders.expire_reservations")
def expire_reservations() -> int:
    """Release stock held by abandoned pending-payment orders.

    Scheduled via ``CELERY_BEAT_SCHEDULE``; the same logic is exposed as the
    ``expire_orders`` management command for environments without Celery beat.
    """
    return services.expire_orders()

"""Celery tasks for asynchronous notification delivery."""

from __future__ import annotations

from celery import shared_task

from .models import NotificationDelivery, NotificationDeliveryStatus
from .services import deliver_delivery


@shared_task(bind=True, name="notifications.deliver_delivery", max_retries=3)
def deliver_delivery_task(self, delivery_id) -> bool:
    """Deliver one channel delivery, retrying with exponential backoff."""
    if deliver_delivery(delivery_id):
        return True
    try:
        delivery = NotificationDelivery.objects.get(pk=delivery_id)
    except NotificationDelivery.DoesNotExist:
        return False
    if delivery.status == NotificationDeliveryStatus.PENDING:
        raise self.retry(countdown=60 * (2**self.request.retries))
    return False


@shared_task(name="notifications.deliver_pending")
def deliver_pending_task() -> int:
    """Sweep pending deliveries (safety net for missed schedules)."""
    delivered = 0
    pending = (
        NotificationDelivery.objects.filter(status=NotificationDeliveryStatus.PENDING)
        .select_related("notification", "notification__recipient")
        .order_by("created_at")[:500]
    )
    for delivery in pending:
        if deliver_delivery(delivery.pk):
            delivered += 1
    return delivered

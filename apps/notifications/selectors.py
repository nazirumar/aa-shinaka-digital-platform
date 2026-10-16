"""Read-only querysets for the notification centre (ownership-scoped)."""

from __future__ import annotations

from django.db.models import QuerySet

from .models import Notification, NotificationDelivery


def notifications_for(user, *, category: str = "", unread_only: bool = False) -> QuerySet:
    """Notifications belonging to ``user`` only, newest first."""
    queryset = Notification.objects.filter(recipient=user)
    if category:
        queryset = queryset.filter(category=category)
    if unread_only:
        queryset = queryset.filter(is_read=False)
    return queryset.order_by("-created_at")


def notification_for(user, pk) -> Notification | None:
    """Return a single notification owned by ``user`` (or ``None``)."""
    return Notification.objects.filter(recipient=user, pk=pk).first()


def deliveries_for(notification) -> QuerySet[NotificationDelivery]:
    return NotificationDelivery.objects.filter(notification=notification).order_by("channel")

"""Notification services: create, de-duplicate, deliver, read-state.

The service layer is the single entry point for the notification centre. Domain
modules call :func:`emit` (usually through the helpers in
:mod:`apps.notifications.events`) at genuine state-change points. ``emit`` writes
the in-app :class:`~apps.notifications.models.Notification` inside the caller's
transaction so it rolls back with the business operation, then schedules channel
delivery **after the transaction commits**.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from .channels import ChannelNotConfigured, get_channel
from .models import (
    Notification,
    NotificationCategory,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationPreference,
    max_delivery_attempts,
)

logger = logging.getLogger(__name__)

SAFE_URL_MAX = 300


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------
def get_preference(user) -> NotificationPreference:
    """Return the user's preference row, creating the default one on demand."""
    preference, _ = NotificationPreference.objects.get_or_create(user=user)
    return preference


def update_preference(
    user,
    *,
    in_app_enabled=None,
    email_enabled=None,
    sms_enabled=None,
    whatsapp_enabled=None,
    categories=None,
) -> NotificationPreference:
    preference = get_preference(user)
    fields = []
    for field, value in (
        ("in_app_enabled", in_app_enabled),
        ("email_enabled", email_enabled),
        ("sms_enabled", sms_enabled),
        ("whatsapp_enabled", whatsapp_enabled),
    ):
        if value is not None:
            setattr(preference, field, bool(value))
            fields.append(field)
    if categories is not None:
        merged = dict(preference.categories or {})
        for key in NotificationCategory.values:
            if key in categories:
                merged[key] = bool(categories[key])
        preference.categories = merged
        fields.append("categories")
    if fields:
        preference.save(update_fields=[*fields, "updated_at"])
    return preference


def category_enabled(user, category: str) -> bool:
    preference = get_preference(user)
    if isinstance(preference.categories, dict):
        return preference.categories.get(category, True)
    return True


# ---------------------------------------------------------------------------
# Safe links
# ---------------------------------------------------------------------------
def safe_url(url: str) -> str:
    """Return ``url`` only if it is a safe, same-site relative path.

    Customers must never be redirected to an attacker-supplied absolute URL, so
    anything that is not a single-slash-rooted path is discarded.
    """
    if not url:
        return ""
    candidate = url.strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return ""
    if "\r" in candidate or "\n" in candidate:
        return ""
    return candidate[:SAFE_URL_MAX]


# ---------------------------------------------------------------------------
# Creation / emission
# ---------------------------------------------------------------------------
def emit(
    *,
    recipient,
    category: str,
    event: str,
    title: str,
    message: str = "",
    url: str = "",
    reference_type: str = "",
    reference_id: str = "",
    dedupe_key: str | None = None,
    channels: list[str] | None = None,
    manage_email: bool = False,
    schedule: bool = True,
) -> Notification | None:
    """Create (or return) an in-app notification and schedule its delivery.

    Idempotent on ``dedupe_key`` so retried webhooks/events never duplicate.
    Returns ``None`` when the recipient is unknown or has muted the category.
    """
    if recipient is None:
        return None
    key = (dedupe_key or f"{event}:{reference_type}:{reference_id}")[:180]
    existing = Notification.objects.filter(dedupe_key=key).first()
    if existing is not None:
        return existing

    preference = get_preference(recipient)
    categories = preference.categories if isinstance(preference.categories, dict) else {}
    if categories.get(category) is False:
        # The customer muted this category: nothing is stored or sent.
        return None

    notification = Notification.objects.create(
        recipient=recipient,
        category=category,
        event=event,
        title=title[:200],
        message=message or "",
        url=safe_url(url),
        reference_type=reference_type[:60],
        reference_id=str(reference_id or "")[:64],
        dedupe_key=key,
    )

    if channels is None:
        channels = [NotificationChannel.IN_APP]
        if manage_email:
            channels.append(NotificationChannel.EMAIL)

    pending_ids: list[str] = []
    for name in channels:
        channel = get_channel(name)
        if not channel.is_enabled_for(preference):
            status = NotificationDeliveryStatus.SKIPPED
        elif name == NotificationChannel.IN_APP:
            status = NotificationDeliveryStatus.DELIVERED
        else:
            status = NotificationDeliveryStatus.PENDING
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            channel=name,
            status=status,
            delivered_at=timezone.now() if status == NotificationDeliveryStatus.DELIVERED else None,
        )
        if status == NotificationDeliveryStatus.PENDING:
            pending_ids.append(str(delivery.pk))

    if pending_ids and schedule:
        transaction.on_commit(lambda: _deliver_many(pending_ids))
    return notification


# ``transaction.on_commit`` needs a no-arg callable.
def _deliver_many(delivery_ids: list[str]) -> None:
    for delivery_id in delivery_ids:
        try:
            _deliver_or_enqueue(delivery_id)
        except Exception:  # pragma: no cover - delivery must never break a flow
            logger.exception("Notification delivery failed for %s.", delivery_id)


def _deliver_or_enqueue(delivery_id: str) -> None:
    try:
        from .tasks import deliver_delivery_task

        deliver_delivery_task.delay(delivery_id)
    except Exception:
        logger.exception("Could not queue notification delivery %s; sending inline.", delivery_id)
        deliver_delivery(delivery_id)


def deliver_delivery(delivery_id, *, max_attempts: int | None = None) -> bool:
    """Attempt to deliver one channel delivery; update attempts/status.

    Returns ``True`` when the delivery is confirmed delivered. On failure the
    attempt count is incremented; once the limit is reached the delivery is
    marked ``failed`` (never silently dropped).
    """
    limit = max_attempts or max_delivery_attempts()
    try:
        delivery = NotificationDelivery.objects.select_related(
            "notification", "notification__recipient"
        ).get(pk=delivery_id)
    except NotificationDelivery.DoesNotExist:
        return False
    if delivery.status == NotificationDeliveryStatus.DELIVERED:
        return True

    channel = get_channel(delivery.channel)
    delivery.attempt_count += 1
    delivery.last_attempt_at = timezone.now()
    try:
        reference = channel.send(delivery.notification)
    except Exception as exc:
        delivery.error_detail = str(exc)[:2000]
        delivery.status = (
            NotificationDeliveryStatus.FAILED
            if delivery.attempt_count >= limit
            else NotificationDeliveryStatus.PENDING
        )
        delivery.save(
            update_fields=[
                "attempt_count",
                "last_attempt_at",
                "status",
                "error_detail",
                "updated_at",
            ]
        )
        logger.warning(
            "Notification delivery %s to %s failed (attempt %s): %s",
            delivery.channel,
            delivery.notification.recipient_id,
            delivery.attempt_count,
            exc,
        )
        return False

    delivery.status = NotificationDeliveryStatus.DELIVERED
    delivery.delivered_at = timezone.now()
    delivery.provider_reference = str(reference or "")[:200]
    delivery.error_detail = ""
    delivery.save(
        update_fields=[
            "attempt_count",
            "last_attempt_at",
            "status",
            "delivered_at",
            "provider_reference",
            "error_detail",
            "updated_at",
        ]
    )
    return True


def deliver_pending_for(notification) -> int:
    """Deliver every pending channel of ``notification``; return success count."""
    delivered = 0
    for delivery in notification.deliveries.filter(
        status=NotificationDeliveryStatus.PENDING
    ).select_related("notification", "notification__recipient"):
        if deliver_delivery(delivery.pk):
            delivered += 1
    return delivered


# ---------------------------------------------------------------------------
# Read state
# ---------------------------------------------------------------------------
def mark_read(notification, *, user) -> bool:
    """Mark ``notification`` read if it belongs to ``user`` (idempotent)."""
    if notification.recipient_id != getattr(user, "pk", None):
        return False
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
    return True


def mark_all_read(user) -> int:
    return Notification.objects.filter(recipient=user, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )


def mark_unread(notification, *, user) -> bool:
    if notification.recipient_id != getattr(user, "pk", None):
        return False
    if notification.is_read:
        notification.is_read = False
        notification.read_at = None
        notification.save(update_fields=["is_read", "read_at"])
    return True


def unread_count(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(recipient=user, is_read=False).count()


__all__ = [
    "ChannelNotConfigured",
    "deliver_delivery",
    "deliver_pending_for",
    "emit",
    "get_preference",
    "mark_all_read",
    "mark_read",
    "mark_unread",
    "safe_url",
    "unread_count",
    "update_preference",
]

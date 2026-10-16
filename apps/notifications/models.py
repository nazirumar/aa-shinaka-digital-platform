"""Unified notification data models.

Phase 10 consolidates customer-facing communications into one place:

* :class:`Notification` — the in-app record a customer sees in the notification
  centre (one row per real event, de-duplicated on ``dedupe_key``).
* :class:`NotificationPreference` — per-user channel and category choices.
* :class:`NotificationDelivery` — a per-channel delivery attempt ledger so email
  (and, later, SMS/WhatsApp) delivery can be tracked and retried without ever
  claiming success that a provider did not confirm.

The existing per-domain dedupe logs (orders/services/export/training) remain the
authority for transactional *email* idempotency; this app adds the in-app feed,
preferences and delivery tracking on top without duplicating domain records.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class NotificationCategory(models.TextChoices):
    """Broad categories a customer can filter and mute independently."""

    ORDERS = "orders", "Orders"
    PAYMENTS = "payments", "Payments & invoices"
    EXPORT = "export", "Export services"
    SERVICES = "services", "Agricultural services"
    TRAINING = "training", "Training academy"
    SUPPORT = "support", "Support"
    ACCOUNT = "account", "Account"
    GENERAL = "general", "General"


class NotificationChannel(models.TextChoices):
    IN_APP = "in_app", "In-app"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"


class NotificationDeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DELIVERED = "delivered", "Delivered"
    SKIPPED = "skipped", "Skipped"
    FAILED = "failed", "Failed"


class UUIDPkModel(models.Model):
    """Abstract base giving a UUID primary key and immutable ``created_at``."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)

    class Meta:
        abstract = True


class Notification(UUIDPkModel):
    """A single in-app notification for one recipient.

    Created inside the same transaction as the business event so it is rolled
    back with it; channel delivery is scheduled only after that transaction
    commits (see :mod:`apps.notifications.tasks`).
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    category = models.CharField(max_length=20, choices=NotificationCategory.choices, db_index=True)
    event = models.CharField(max_length=80, db_index=True)
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    # A safe, site-relative link to the related record (never an absolute URL
    # supplied by a user). Validated by ``services.safe_link``.
    url = models.CharField(max_length=300, blank=True)
    reference_type = models.CharField(max_length=60, blank=True)
    reference_id = models.CharField(max_length=64, blank=True)
    # Stable per-recipient event key so retried events never duplicate a row.
    dedupe_key = models.CharField(max_length=180, unique=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        indexes: ClassVar[list] = [
            models.Index(fields=["recipient", "-created_at"], name="notif_recipient_created_idx"),
            models.Index(
                fields=["recipient", "is_read", "-created_at"],
                name="notif_recipient_read_idx",
            ),
            models.Index(
                fields=["recipient", "category", "-created_at"],
                name="notif_recip_cat_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event} → {self.recipient_id}"


def default_categories() -> dict:
    """All categories enabled until a customer turns one off."""
    return {choice.value: True for choice in NotificationCategory}


class NotificationPreference(models.Model):
    """Per-user notification channel and category preferences."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )
    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    # Optional channels stay off until a provider is configured and the customer
    # opts in. No provider credentials are hardcoded anywhere.
    sms_enabled = models.BooleanField(default=False)
    whatsapp_enabled = models.BooleanField(default=False)
    categories = models.JSONField(default=default_categories, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        verbose_name = "Notification preference"
        verbose_name_plural = "Notification preferences"

    def __str__(self) -> str:
        return f"Preferences for {self.user_id}"

    def category_enabled(self, category: str) -> bool:
        """An unknown category defaults to enabled (fail-open for delivery)."""
        if not isinstance(self.categories, dict) or not self.categories:
            return True
        return bool(self.categories.get(category, True))


class NotificationDelivery(models.Model):
    """A single per-channel delivery attempt for a notification."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=20, choices=NotificationChannel.choices)
    status = models.CharField(
        max_length=16,
        choices=NotificationDeliveryStatus.choices,
        default=NotificationDeliveryStatus.PENDING,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    provider_reference = models.CharField(max_length=200, blank=True)
    error_detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["channel"]
        verbose_name = "Notification delivery"
        verbose_name_plural = "Notification deliveries"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["notification", "channel"], name="uniq_notification_channel"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.notification_id} · {self.channel} · {self.status}"


def max_delivery_attempts() -> int:
    return int(getattr(settings, "NOTIFICATION_MAX_ATTEMPTS", 3))

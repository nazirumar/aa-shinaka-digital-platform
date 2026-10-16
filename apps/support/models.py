"""Support-centre data models (Phase 10).

A customer raises a :class:`SupportTicket` (optionally linked to one of their own
orders or services), replies through :class:`SupportMessage`, attaches evidence
with :class:`SupportAttachment`, and every status change is recorded in
:class:`SupportStatusHistory`. Internal-only staff notes live on the message row
(``is_internal``) and are never exposed to customers by the selectors/views.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import UUIDTimeStampedModel

REFERENCE_PREFIX = "AS-ST"


class SupportCategory(models.TextChoices):
    PRODUCT_ORDER = "product_order", "Product order"
    PAYMENT = "payment", "Payment"
    EXPORT = "export", "Export enquiry"
    CONSULTANCY = "consultancy", "Consultancy"
    FARMING = "farming", "Farming"
    MARKETING = "marketing", "Marketing"
    STORAGE = "storage", "Storage"
    TRAINING = "training", "Training"
    GENERAL = "general", "General enquiry"


class SupportPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class SupportStatus(models.TextChoices):
    OPEN = "open", "Open"
    ASSIGNED = "assigned", "Assigned"
    IN_PROGRESS = "in_progress", "In progress"
    WAITING_FOR_CUSTOMER = "waiting_for_customer", "Waiting for customer"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"
    REOPENED = "reopened", "Reopened"


# Allowed transitions (Task 12). Anything not listed is rejected server-side.
SUPPORT_TRANSITIONS: dict[str, set[str]] = {
    SupportStatus.OPEN: {
        SupportStatus.ASSIGNED,
        SupportStatus.IN_PROGRESS,
        SupportStatus.WAITING_FOR_CUSTOMER,
        SupportStatus.RESOLVED,
        SupportStatus.CLOSED,
    },
    SupportStatus.ASSIGNED: {
        SupportStatus.IN_PROGRESS,
        SupportStatus.WAITING_FOR_CUSTOMER,
        SupportStatus.RESOLVED,
        SupportStatus.CLOSED,
        SupportStatus.REOPENED,
    },
    SupportStatus.IN_PROGRESS: {
        SupportStatus.WAITING_FOR_CUSTOMER,
        SupportStatus.RESOLVED,
        SupportStatus.CLOSED,
    },
    SupportStatus.WAITING_FOR_CUSTOMER: {
        SupportStatus.IN_PROGRESS,
        SupportStatus.RESOLVED,
        SupportStatus.CLOSED,
    },
    SupportStatus.RESOLVED: {SupportStatus.CLOSED, SupportStatus.REOPENED},
    SupportStatus.CLOSED: {SupportStatus.REOPENED},
    SupportStatus.REOPENED: {
        SupportStatus.ASSIGNED,
        SupportStatus.IN_PROGRESS,
        SupportStatus.WAITING_FOR_CUSTOMER,
        SupportStatus.RESOLVED,
        SupportStatus.CLOSED,
    },
}

# A resolved ticket may be reopened within this window (Task 10 "configured rules").
REOPEN_WINDOW_DAYS = 30


class SupportRelatedType(models.TextChoices):
    PRODUCT_ORDER = "orders.Order", "Product order"
    PAYMENT = "orders.Payment", "Payment"
    EXPORT_ENQUIRY = "export.ExportEnquiry", "Export enquiry"
    SERVICE_REQUEST = "services.ServiceRequest", "Service request"
    TRAINING_ENROLLMENT = "training.Enrollment", "Training enrolment"


def generate_reference() -> str:
    stamp = timezone.now().strftime("%Y%m%d")
    return f"{REFERENCE_PREFIX}-{stamp}-{uuid.uuid4().hex[:6].upper()}"


class SupportTicket(UUIDTimeStampedModel):
    """A customer support case."""

    reference = models.CharField(max_length=32, unique=True, editable=False)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_tickets"
    )
    subject = models.CharField(max_length=200)
    category = models.CharField(
        max_length=32, choices=SupportCategory.choices, default=SupportCategory.GENERAL
    )
    priority = models.CharField(
        max_length=16, choices=SupportPriority.choices, default=SupportPriority.NORMAL
    )
    status = models.CharField(
        max_length=24, choices=SupportStatus.choices, default=SupportStatus.OPEN, db_index=True
    )
    related_type = models.CharField(max_length=40, choices=SupportRelatedType.choices, blank=True)
    related_id = models.CharField(max_length=64, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_support_tickets",
    )
    resolved_at = models.DateTimeField(null=True, blank=True, editable=False)
    closed_at = models.DateTimeField(null=True, blank=True, editable=False)
    reopened_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True, editable=False)

    class Meta:
        ordering: ClassVar[list[str]] = ["-last_activity_at"]
        verbose_name = "Support ticket"
        verbose_name_plural = "Support tickets"
        indexes: ClassVar[list] = [
            models.Index(
                fields=["customer", "-last_activity_at"], name="support_cust_activity_idx"
            ),
            models.Index(
                fields=["status", "-last_activity_at"], name="support_status_activity_idx"
            ),
            models.Index(fields=["assigned_to", "status"], name="support_assignee_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.reference} · {self.subject}"

    def save(self, *args, **kwargs):  # type: ignore[override]
        if not self.reference:
            self.reference = generate_reference()
        super().save(*args, **kwargs)

    @property
    def is_open(self) -> bool:
        return self.status not in {SupportStatus.CLOSED}

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in SUPPORT_TRANSITIONS.get(self.status, set())

    def can_reopen(self, *, now=None) -> bool:
        """Reopening is only allowed on recent resolves/closes (configured rule)."""
        now = now or timezone.now()
        if self.status not in {SupportStatus.RESOLVED, SupportStatus.CLOSED}:
            return True
        anchor = self.closed_at or self.resolved_at
        if anchor is None:
            return True
        return (now - anchor).days <= REOPEN_WINDOW_DAYS


class SupportMessage(UUIDTimeStampedModel):
    """A single message in a ticket conversation (customer or staff, public or note)."""

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_messages",
    )
    message = models.TextField()
    is_internal = models.BooleanField(default=False)

    class Meta:
        ordering: ClassVar[list[str]] = ["created_at"]
        verbose_name = "Support message"
        verbose_name_plural = "Support messages"

    def __str__(self) -> str:
        kind = "note" if self.is_internal else "message"
        return f"{self.ticket_id} · {kind} · {self.sender_id}"


class SupportAttachment(UUIDTimeStampedModel):
    """A customer/staff file attached to a ticket (optionally to one message)."""

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="attachments")
    message = models.ForeignKey(
        SupportMessage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attachments",
    )
    file = models.FileField(upload_to="support_attachments/%Y/%m/")
    original_filename = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_attachments",
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Support attachment"
        verbose_name_plural = "Support attachments"

    def __str__(self) -> str:
        return self.original_filename or (self.file.name or "attachment")


class SupportStatusHistory(models.Model):
    """Append-only status-transition audit trail."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        SupportTicket, on_delete=models.CASCADE, related_name="status_history"
    )
    previous_status = models.CharField(max_length=24, choices=SupportStatus.choices, blank=True)
    new_status = models.CharField(max_length=24, choices=SupportStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Support status history"
        verbose_name_plural = "Support status history"

    def __str__(self) -> str:
        return f"{self.ticket_id}: {self.previous_status} → {self.new_status}"

"""Persistent reporting records for Phase 11.

Analytics itself is **read-only** against the business domain: these models only
record reporting artefacts (generated exports, scheduled reports, their
executions and deliveries). They never store business figures of their own —
every number is derived from the authoritative source models at request time.

Retention is enforced by ``expires_at`` and the ``cleanup_report_exports`` task;
files are served only through a permission-checked view, never a public URL.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class UUIDTimeStampedModel(models.Model):
    """UUID primary key plus ``created_at`` / ``updated_at`` timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


class ExportFormat(models.TextChoices):
    CSV = "csv", "CSV"
    XLSX = "xlsx", "Excel (XLSX)"
    PDF = "pdf", "PDF"


class ExecutionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    EXPIRED = "expired", "Expired"


class ScheduleFrequency(models.TextChoices):
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


def _reference(prefix: str = "AS-RPT") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


class ReportExport(UUIDTimeStampedModel):
    """One generated report file plus the filters that produced it (history)."""

    reference = models.CharField(max_length=32, unique=True, db_index=True, editable=False)
    report_key = models.CharField(max_length=64, db_index=True)
    export_format = models.CharField(max_length=8, choices=ExportFormat.choices)
    filters = models.JSONField(default=dict, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_exports",
    )
    status = models.CharField(
        max_length=12, choices=ExecutionStatus.choices, default=ExecutionStatus.PENDING
    )
    is_financial = models.BooleanField(default=False, db_index=True)
    row_count = models.PositiveIntegerField(default=0)
    file = models.FileField(upload_to="analytics_reports/%Y/%m/", blank=True)
    error = models.TextField(blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Report export"
        verbose_name_plural = "Report exports"
        indexes: ClassVar[list] = [
            models.Index(fields=["report_key", "-created_at"], name="rpt_export_key_idx"),
            models.Index(fields=["requested_by", "-created_at"], name="rpt_export_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.reference} · {self.report_key} ({self.export_format})"

    def save(self, *args, **kwargs):  # type: ignore[override]
        if not self.reference:
            self.reference = _reference()
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone

        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def report_label(self) -> str:
        from .reports import get_report

        definition = get_report(self.report_key)
        return definition.label if definition else self.report_key


class ScheduledReport(UUIDTimeStampedModel):
    """An authorised staff member's recurring report configuration."""

    name = models.CharField(max_length=150)
    report_key = models.CharField(max_length=64, db_index=True)
    filters = models.JSONField(default=dict, blank=True)
    frequency = models.CharField(
        max_length=10, choices=ScheduleFrequency.choices, default=ScheduleFrequency.DAILY
    )
    export_format = models.CharField(
        max_length=8, choices=ExportFormat.choices, default=ExportFormat.CSV
    )
    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="scheduled_reports", blank=True
    )
    is_enabled = models.BooleanField(default=True, db_index=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scheduled_reports_created",
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Scheduled report"
        verbose_name_plural = "Scheduled reports"

    def __str__(self) -> str:
        return f"{self.name} · {self.get_frequency_display()}"

    @property
    def report_label(self) -> str:
        from .reports import get_report

        definition = get_report(self.report_key)
        return definition.label if definition else self.report_key


class ReportExecution(UUIDTimeStampedModel):
    """A single run of a scheduled report (also records duplicate prevention)."""

    scheduled_report = models.ForeignKey(
        ScheduledReport,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="executions",
    )
    report_key = models.CharField(max_length=64, db_index=True)
    filters = models.JSONField(default=dict, blank=True)
    # Identifies the schedule period (e.g. ``2026-10-15`` for a daily run) so a
    # schedule can never execute twice for the same period.
    period_key = models.CharField(max_length=32, blank=True, db_index=True)
    status = models.CharField(
        max_length=12, choices=ExecutionStatus.choices, default=ExecutionStatus.PENDING
    )
    triggered_by = models.CharField(max_length=16, default="schedule")
    row_count = models.PositiveIntegerField(default=0)
    export = models.ForeignKey(
        ReportExport,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="executions",
    )
    triggered_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_executions",
    )
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "Report execution"
        verbose_name_plural = "Report executions"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["scheduled_report", "period_key"],
                condition=~models.Q(period_key=""),
                name="uniq_schedule_period_execution",
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["status", "-created_at"], name="rpt_exec_idx")
        ]

    def __str__(self) -> str:
        return f"{self.report_key} execution [{self.status}]"


class ReportDelivery(UUIDTimeStampedModel):
    """Delivery outcome of an execution to one recipient address."""

    execution = models.ForeignKey(
        ReportExecution, on_delete=models.CASCADE, related_name="deliveries"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_deliveries",
    )
    email = models.EmailField()
    status = models.CharField(
        max_length=8, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["created_at"]
        verbose_name = "Report delivery"
        verbose_name_plural = "Report deliveries"

    def __str__(self) -> str:
        return f"{self.email} [{self.status}]"


__all__ = [
    "DeliveryStatus",
    "ExecutionStatus",
    "ExportFormat",
    "ReportDelivery",
    "ReportExecution",
    "ReportExport",
    "ScheduleFrequency",
    "ScheduledReport",
]

"""Write layer for analytics & reporting (Phase 11).

Only reporting records are written here (exports, schedules, executions,
deliveries) — never a business table. Reads/aggregations live in
:mod:`apps.analytics.selectors`; this module owns report generation, scheduling,
delivery, access logging and retention.

Generation is synchronous by default so behaviour is deterministic without a
running Celery worker; :mod:`apps.analytics.tasks` wraps the same functions for a
real deployment.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts.permissions import has_capability
from apps.core.audit import record_audit

from . import exports
from .filters import ReportFilters
from .models import (
    DeliveryStatus,
    ExecutionStatus,
    ReportDelivery,
    ReportExecution,
    ReportExport,
    ScheduledReport,
)
from .reports import build_rows, compute_totals, get_report

logger = logging.getLogger(__name__)


def retention_days() -> int:
    return int(getattr(settings, "ANALYTICS_REPORT_RETENTION_DAYS", 30))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def create_report_export(
    *, definition, filters: ReportFilters, export_format: str, user
) -> ReportExport:
    return ReportExport.objects.create(
        report_key=definition.key,
        export_format=export_format,
        filters=filters.as_dict(),
        requested_by=user if getattr(user, "is_authenticated", False) else None,
        is_financial=definition.is_financial,
        status=ExecutionStatus.PENDING,
    )


def _subtitle(definition, filters: ReportFilters) -> str:
    return f"{definition.division.title()} division · {filters.label()}"


def _footer(definition, filters: ReportFilters) -> str:
    stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    caution = (
        " Verified receipts are cash received, not accounting profit."
        if definition.is_financial
        else ""
    )
    return f"AA Shinaka · {definition.label} · generated {stamp}.{caution}"


def generate_report_export(export: ReportExport) -> ReportExport:
    """Render ``export`` to its file. Safe to call from a Celery task."""
    definition = get_report(export.report_key)
    export.status = ExecutionStatus.RUNNING
    export.save(update_fields=["status", "updated_at"])
    try:
        if definition is None:
            raise ValueError(f"Unknown report key {export.report_key!r}")
        filters = ReportFilters.from_dict(export.filters)
        rows = build_rows(definition, filters)
        content = exports.generate(
            definition.columns,
            rows,
            export_format=export.export_format,
            title=definition.label,
            subtitle=_subtitle(definition, filters),
            footer=_footer(definition, filters),
        )
        filename = exports.safe_filename(
            f"{definition.key}-{timezone.localtime():%Y%m%d-%H%M}", export.export_format
        )
        export.file.save(filename, ContentFile(content), save=False)
        export.row_count = len(rows)
        export.status = ExecutionStatus.SUCCEEDED
        export.generated_at = timezone.now()
        export.expires_at = timezone.now() + timedelta(days=retention_days())
        export.error = ""
        export.save()
    except Exception as exc:  # noqa: BLE001 - record failure, never crash the request
        logger.exception("Report generation failed for %s", export.report_key)
        export.status = ExecutionStatus.FAILED
        export.error = str(exc)[:2000]
        export.save(update_fields=["status", "error", "updated_at"])
    return export


def preview_report(definition, filters: ReportFilters, *, limit: int = 50) -> dict:
    """Build a bounded preview for the report builder page."""
    rows = build_rows(definition, filters)
    columns = definition.columns
    return {
        "columns": columns,
        "rows": rows[:limit],
        "row_count": len(rows),
        "totals": compute_totals(rows, columns),
        "truncated": len(rows) > limit,
    }


# ---------------------------------------------------------------------------
# Access logging
# ---------------------------------------------------------------------------


def record_report_access(*, actor, export: ReportExport, action: str, request=None) -> None:
    """Audit a report generation/download (financial reports are called out)."""
    record_audit(
        actor=actor,
        action=action,
        target=export,
        after={
            "report_key": export.report_key,
            "export_format": export.export_format,
            "financial": export.is_financial,
        },
        request=request,
        note="Financial report access" if export.is_financial else "Report access",
    )


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def compute_next_run_at(frequency: str, *, after=None):
    now = after or timezone.now()
    if frequency == "weekly":
        return now + timedelta(weeks=1)
    if frequency == "monthly":
        return now + timedelta(days=30)
    return now + timedelta(days=1)


def period_key_for(frequency: str, run_at) -> str:
    local = timezone.localtime(run_at)
    if frequency == "weekly":
        year, week, _ = local.isocalendar()
        return f"{year}-W{week:02d}"
    if frequency == "monthly":
        return f"{local.year}-{local.month:02d}"
    return local.date().isoformat()


def create_scheduled_report(
    *, name, definition, filters: ReportFilters, frequency, export_format, recipients, user
):
    scheduled = ScheduledReport.objects.create(
        name=name,
        report_key=definition.key,
        filters=filters.as_dict(),
        frequency=frequency,
        export_format=export_format,
        created_by=user if getattr(user, "is_authenticated", False) else None,
        next_run_at=compute_next_run_at(frequency),
    )
    scheduled.recipients.set(recipients)
    return scheduled


def due_schedules(*, now=None):
    now = now or timezone.now()
    return ScheduledReport.objects.filter(is_enabled=True, next_run_at__lte=now)


def _recipient_may_receive(recipient, definition) -> bool:
    if not getattr(recipient, "is_active", False) or not getattr(recipient, "is_staff", False):
        return False
    capability = "analytics.finance" if definition.is_financial else "reports.build"
    return has_capability(recipient, capability)


def deliver_report(execution: ReportExecution) -> list[ReportDelivery]:
    """Email a generated export to each authorised recipient."""
    delivered: list[ReportDelivery] = []
    scheduled = execution.scheduled_report
    if scheduled is None or execution.export is None:
        return delivered
    definition = get_report(execution.report_key)
    for recipient in scheduled.recipients.all():
        if definition is None or not _recipient_may_receive(recipient, definition):
            delivered.append(
                ReportDelivery.objects.create(
                    execution=execution,
                    recipient=recipient,
                    email=recipient.email,
                    status=DeliveryStatus.SKIPPED,
                    error="Recipient no longer has permission for this report.",
                )
            )
            continue
        delivery = ReportDelivery.objects.create(
            execution=execution, recipient=recipient, email=recipient.email
        )
        try:
            message = EmailMessage(
                subject=f"AA Shinaka scheduled report: {definition.label}",
                body=(
                    f"Attached is the scheduled '{definition.label}' report.\n"
                    f"Period: {ReportFilters.from_dict(execution.filters).label()}\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient.email],
            )
            if execution.export.file:
                execution.export.file.open("rb")
                message.attach(
                    execution.export.file.name.rsplit("/", 1)[-1],
                    execution.export.file.read(),
                    exports.CONTENT_TYPES_BY_FORMAT.get(
                        execution.export.export_format, "application/octet-stream"
                    ),
                )
                execution.export.file.close()
            message.send(fail_silently=False)
            delivery.status = DeliveryStatus.SENT
            delivery.sent_at = timezone.now()
        except Exception as exc:  # noqa: BLE001
            delivery.status = DeliveryStatus.FAILED
            delivery.error = str(exc)[:500]
        delivery.save()
        delivered.append(delivery)
    return delivered


def execute_scheduled_report(scheduled: ScheduledReport, *, now=None) -> ReportExecution | None:
    """Run one schedule at most once per period."""
    now = now or timezone.now()
    definition = get_report(scheduled.report_key)
    if definition is None:
        return None
    run_at = scheduled.next_run_at or now
    period_key = period_key_for(scheduled.frequency, run_at)

    if ReportExecution.objects.filter(scheduled_report=scheduled, period_key=period_key).exists():
        scheduled.next_run_at = compute_next_run_at(scheduled.frequency, after=now)
        scheduled.save(update_fields=["next_run_at", "updated_at"])
        return None

    try:
        execution = ReportExecution.objects.create(
            scheduled_report=scheduled,
            report_key=scheduled.report_key,
            filters=scheduled.filters,
            period_key=period_key,
            triggered_by="schedule",
            status=ExecutionStatus.RUNNING,
            started_at=now,
        )
    except IntegrityError:
        # Another worker already claimed this period.
        return None

    try:
        filters = ReportFilters.from_dict(scheduled.filters)
        export = ReportExport.objects.create(
            report_key=scheduled.report_key,
            export_format=scheduled.export_format,
            filters=filters.as_dict(),
            requested_by=scheduled.created_by,
            is_financial=definition.is_financial,
            status=ExecutionStatus.PENDING,
        )
        generate_report_export(export)
        execution.export = export
        execution.row_count = export.row_count
        execution.status = (
            ExecutionStatus.SUCCEEDED
            if export.status == ExecutionStatus.SUCCEEDED
            else ExecutionStatus.FAILED
        )
        execution.error = export.error
        execution.finished_at = timezone.now()
        execution.save()
        if execution.status == ExecutionStatus.SUCCEEDED:
            deliver_report(execution)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Scheduled report execution failed for %s", scheduled.pk)
        execution.status = ExecutionStatus.FAILED
        execution.error = str(exc)[:2000]
        execution.finished_at = timezone.now()
        execution.save()

    scheduled.last_run_at = now
    scheduled.next_run_at = compute_next_run_at(scheduled.frequency, after=now)
    scheduled.save(update_fields=["last_run_at", "next_run_at", "updated_at"])
    return execution


def run_due_schedules(*, now=None) -> int:
    now = now or timezone.now()
    count = 0
    for scheduled in due_schedules(now=now):
        if execute_scheduled_report(scheduled, now=now) is not None:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def cleanup_expired_exports(*, now=None) -> int:
    """Delete stored files past retention and mark the records expired."""
    now = now or timezone.now()
    cleaned = 0
    for export in ReportExport.objects.filter(expires_at__lte=now).exclude(
        status=ExecutionStatus.EXPIRED
    ):
        if export.file:
            export.file.delete(save=False)
        export.status = ExecutionStatus.EXPIRED
        export.file = ""
        export.save(update_fields=["status", "file", "updated_at"])
        cleaned += 1
    return cleaned


__all__ = [
    "cleanup_expired_exports",
    "compute_next_run_at",
    "create_report_export",
    "create_scheduled_report",
    "deliver_report",
    "due_schedules",
    "execute_scheduled_report",
    "generate_report_export",
    "period_key_for",
    "preview_report",
    "record_report_access",
    "retention_days",
    "run_due_schedules",
]

"""Celery tasks for analytics and reporting (Phase 11 — Task 14).

Deployments without Celery beat can run the equivalent management commands
(``manage.py run_scheduled_reports`` / ``cleanup_report_exports``). Every task
delegates to the idempotent functions in :mod:`apps.analytics.services`, so
running a task twice never produces a duplicate report.
"""

from __future__ import annotations

import logging

from celery import shared_task

from . import services

logger = logging.getLogger(__name__)


@shared_task(name="analytics.run_scheduled_reports")
def run_scheduled_reports() -> int:
    """Execute every due schedule at most once per period."""
    return services.run_due_schedules()


@shared_task(name="analytics.cleanup_report_exports")
def cleanup_report_exports() -> int:
    """Delete stored files past their retention window."""
    return services.cleanup_expired_exports()


@shared_task(name="analytics.generate_report_export")
def generate_report_export_task(export_id: str) -> str:
    """Render one queued ``ReportExport`` (used when async exports are enabled)."""
    from .models import ReportExport

    export = ReportExport.objects.filter(pk=export_id).first()
    if export is None:
        return ""
    from .services import generate_report_export

    generate_report_export(export)
    return str(export.pk)


__all__ = ["cleanup_report_exports", "generate_report_export_task", "run_scheduled_reports"]

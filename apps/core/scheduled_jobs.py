"""Idempotent periodic jobs, runnable without Celery beat.

Celery beat normally triggers these, but beat/worker are paid services on Render
and a deployment may deliberately run without them (``CELERY_ENABLED=false``).
Every job here delegates to the same idempotent service function the Celery task
uses, so running it twice is safe and running it from an external scheduler is
equivalent to beat.

Entry points:

* ``manage.py run_scheduled_jobs`` (cron, systemd timer, Render Cron Job);
* ``POST /internal/scheduled-jobs/`` with the ``SCHEDULED_JOBS_TOKEN`` header
  (any external cron that can make an HTTPS request).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


def _job_catalogue() -> list[tuple[str, Callable[[], object]]]:
    """Build the job list lazily so importing this module never loads apps early."""
    from apps.analytics import services as analytics_services
    from apps.notifications.tasks import deliver_pending_task
    from apps.orders import payments as order_payments
    from apps.orders import paystack
    from apps.orders import services as order_services
    from apps.training.tasks import send_session_reminders

    def reconcile_payments() -> dict:
        if not paystack.is_enabled():
            # Reconciliation calls the provider; do nothing while payments are
            # switched off rather than recording a failure for every open order.
            return {"skipped": "paystack_disabled"}
        return order_payments.reconcile_all()

    return [
        ("expire_order_reservations", order_services.expire_orders),
        ("reconcile_payments", reconcile_payments),
        ("training_session_reminders", send_session_reminders),
        ("scheduled_reports", analytics_services.run_due_schedules),
        ("cleanup_report_exports", analytics_services.cleanup_expired_exports),
        ("deliver_pending_notifications", deliver_pending_task),
    ]


def run_all(*, fail_fast: bool = False) -> dict:
    """Run every periodic job, isolating failures so one cannot stop the rest.

    Returns ``{"jobs": {name: {"ok": bool, "result"|"error": ...}}, "failed": n}``.
    """
    jobs: dict[str, dict] = {}
    failed = 0
    for name, job in _job_catalogue():
        try:
            jobs[name] = {"ok": True, "result": job()}
        except Exception as exc:  # noqa: BLE001 - report and continue with the rest
            failed += 1
            logger.exception("Scheduled job %s failed.", name)
            jobs[name] = {"ok": False, "error": type(exc).__name__}
            if fail_fast:
                raise
    return {"jobs": jobs, "failed": failed}

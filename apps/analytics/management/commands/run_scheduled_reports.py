"""Generate every due scheduled report.

Deployments without Celery beat can run this on a schedule (cron / systemd
timer). Execution is idempotent per period, so running it more often than the
schedule frequency never produces duplicate reports.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.analytics import services


class Command(BaseCommand):
    help = "Run all scheduled reports whose next run time has passed."

    def handle(self, *args, **options) -> None:
        count = services.run_due_schedules()
        self.stdout.write(self.style.SUCCESS(f"Ran {count} scheduled report(s)."))

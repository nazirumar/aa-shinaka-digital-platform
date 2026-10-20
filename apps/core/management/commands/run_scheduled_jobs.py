"""Run every periodic job once — the fallback when Celery beat is unavailable.

Examples::

    python manage.py run_scheduled_jobs
    python manage.py run_scheduled_jobs --json
    python manage.py run_scheduled_jobs --fail-on-error

All jobs are idempotent, so an external scheduler (cron, Render Cron Job,
cron-job.org) can run this command more often than the original beat cadence
without producing duplicate side effects.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.core.scheduled_jobs import run_all


class Command(BaseCommand):
    help = "Run the Celery-beat periodic jobs once (safe when no worker/beat is running)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print a single JSON object instead of human-readable lines.",
        )
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Exit non-zero if any job failed (default: report and exit 0).",
        )

    def handle(self, *args, **options) -> None:
        result = run_all()

        if options["json"]:
            self.stdout.write(json.dumps(result, default=str))
        else:
            for name, outcome in result["jobs"].items():
                if outcome["ok"]:
                    self.stdout.write(self.style.SUCCESS(f"{name}: {outcome['result']}"))
                else:
                    self.stderr.write(self.style.ERROR(f"{name}: failed ({outcome['error']})"))

        if result["failed"] and options["fail_on_error"]:
            raise CommandError(f"{result['failed']} scheduled job(s) failed.")

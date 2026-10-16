"""Run the analytics data-quality checks from the command line.

Read-only: every check derives its answer from existing records and never writes
to a business table. Use ``--strict`` in a cron/timer to fail the job (non-zero
exit) when any issue is found.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.data_quality import run_checks, summary


class Command(BaseCommand):
    help = "Report and (with --strict) fail on analytics data-quality issues."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with a non-zero status when any issue is found.",
        )

    def handle(self, *args, **options) -> None:
        results = run_checks()
        overall = summary(results)
        for result in results:
            mark = "ok" if result["ok"] else "!!"
            self.stdout.write(
                f"[{mark}] {result['key']}: {result['count']} "
                f"({result['severity']}) — {result['label']}"
            )
        self.stdout.write(
            f"{overall['failing_checks']} of {overall['check_count']} checks flagged issues; "
            f"{overall['issue_count']} affected record(s)."
        )
        if overall["healthy"]:
            self.stdout.write(self.style.SUCCESS("Analytics data quality: OK."))
        else:
            self.stdout.write(self.style.WARNING("Analytics data quality: issues found."))
            if options["strict"]:
                raise CommandError("Analytics data-quality checks failed (--strict).")

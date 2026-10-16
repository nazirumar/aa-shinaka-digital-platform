"""Reconcile in-flight Paystack payments against the provider.

Deployments without Celery beat can run this on a schedule (cron / systemd
timer). It is safe to run repeatedly: each payment is re-verified server-side
and only transitions once a matching, verified capture is found.
"""

from django.core.management.base import BaseCommand

from apps.orders import payments


class Command(BaseCommand):
    help = "Re-verify pending Paystack payments and flag stale refunds."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=15,
            help="Only reconcile payments older than this (default: 15).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum payments to reconcile in one run (default: 100).",
        )

    def handle(self, *args, **options):
        summary = payments.reconcile_pending_payments(
            older_than_minutes=options["older_than_minutes"], limit=options["limit"]
        )
        refunds = payments.reconcile_refunds()
        self.stdout.write(
            f"Payments checked: {summary['checked']} "
            f"(verified {summary['verified']}, unchanged {summary['unchanged']}, "
            f"errors {summary['errors']})."
        )
        self.stdout.write(f"Refunds flagged for attention: {refunds.get('flagged', 0)}.")
        self.stdout.write(self.style.SUCCESS("Reconciliation complete."))

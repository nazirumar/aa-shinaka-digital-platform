"""Release stock held by abandoned pending-payment orders.

Deployments without Celery beat can run this on a schedule (cron / systemd
timer). It is idempotent: each reservation is released exactly once.
"""

from django.core.management.base import BaseCommand

from apps.orders import services


class Command(BaseCommand):
    help = "Expire overdue pending-payment orders and release their stock reservations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Maximum number of orders to expire in one run (default: 500).",
        )

    def handle(self, *args, **options):
        expired = services.expire_orders(limit=options["limit"])
        if expired:
            self.stdout.write(self.style.SUCCESS(f"Expired {expired} order(s)."))
        else:
            self.stdout.write("No orders needed expiring.")

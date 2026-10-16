"""Delete analytics report files past their retention window.

Idempotent: already-expired exports are skipped. Safe to run on a schedule.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.analytics import services


class Command(BaseCommand):
    help = "Delete stored report exports whose retention window has passed."

    def handle(self, *args, **options) -> None:
        count = services.cleanup_expired_exports()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} report file(s)."))

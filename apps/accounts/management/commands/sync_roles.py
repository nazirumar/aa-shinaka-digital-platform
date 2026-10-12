"""Sync the Django groups and permissions that back each platform role."""

from django.core.management.base import BaseCommand

from apps.accounts.roles import sync_role_groups
from apps.accounts.selectors import account_counts


class Command(BaseCommand):
    help = "Create/refresh role groups and their permissions."

    def handle(self, *args, **options):
        groups = sync_role_groups()
        self.stdout.write(self.style.SUCCESS(f"Synced {len(groups)} role groups."))
        for role, group in groups.items():
            perms = ", ".join(sorted(group.permissions.values_list("codename", flat=True)))
            self.stdout.write(f"  {role:<20} -> {perms or '(no model permissions)'}")
        counts = account_counts()
        self.stdout.write(
            "Accounts: "
            f"{counts['customers_total']} customers "
            f"({counts['customers_verified']} verified), "
            f"{counts['staff_total']} staff ({counts['staff_active']} active)."
        )

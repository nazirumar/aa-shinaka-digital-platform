"""Create the first owner (superuser) account.

Useful on hosts without an interactive shell. Prefer environment variables so
the password never appears in shell history, but flags and a prompt also work::

    DJANGO_SUPERUSER_PASSWORD=... python manage.py bootstrap_owner --email me@example.com
    python manage.py bootstrap_owner --email me@example.com --password '...'
    python manage.py bootstrap_owner --email me@example.com   # prompts for the password

The command is idempotent: if a superuser already exists it exits without
changing anything (add ``--fail-if-exists`` to exit non-zero instead).
"""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from apps.core.owner_bootstrap import BootstrapError, ensure_owner, owner_exists


class Command(BaseCommand):
    help = "Create the first owner (superuser) account; a no-op once one exists."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--email", required=True, help="Owner email address (login).")
        parser.add_argument(
            "--password",
            default=None,
            help="Owner password. Falls back to $DJANGO_SUPERUSER_PASSWORD, then a prompt.",
        )
        parser.add_argument("--first-name", default="Owner")
        parser.add_argument("--last-name", default="")
        parser.add_argument(
            "--fail-if-exists",
            action="store_true",
            help="Exit non-zero when an owner already exists (default: report and exit 0).",
        )

    def handle(self, *args, **options) -> None:
        if owner_exists():
            message = "An owner account already exists; nothing to do."
            if options["fail_if_exists"]:
                raise CommandError(message)
            self.stdout.write(self.style.WARNING(message))
            return

        password = options["password"] or os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not password:
            # getpass is imported lazily so importing this module never blocks.
            from django.contrib.auth.management.commands.createsuperuser import (
                Command as CreatesuperuserCommand,
            )

            password = CreatesuperuserCommand().getpass(f"Password for {options['email']}: ")
            confirmation = CreatesuperuserCommand().getpass("Password (again): ")
            if password != confirmation:
                raise CommandError("Passwords do not match.")

        try:
            result = ensure_owner(
                email=options["email"],
                password=password,
                first_name=options["first_name"],
                last_name=options["last_name"],
            )
        except BootstrapError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Created owner account {result.email}."))

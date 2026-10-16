"""Create baseline + representative development data for AA Shinaka.

This is a **development-only** command. It fills the database with the
reference content the platform needs to look and behave like the real
product — site configuration, navigation, CMS pages, catalogue, service
config, training academy, export configuration and shipping zones — plus
optionally a small set of transactional demo records.

Nothing here is imported into production code, and no secret, real
customer, or real transaction data is created. Staff replace the
development values with verified information before any real use.

The command is idempotent: re-running it never overwrites content a
human has edited, and it can be previewed with ``--dry-run``.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.management.commands.seed_data_support import builders
from apps.core.management.commands.seed_data_support.media import ImageLibrary

HELP = (
    "Seed development data (site, CMS, catalogue, services, training, "
    "export, shipping). Use --with-demo-records to also create sample "
    "orders, service requests, enrolments and export enquiries."
)


class Command(BaseCommand):
    help = HELP

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing changes.",
        )
        parser.add_argument(
            "--no-images",
            action="store_true",
            help="Do not download or generate images (placeholder mode).",
        )
        parser.add_argument(
            "--force-images",
            action="store_true",
            help="Re-download and replace seed images even if records exist.",
        )
        parser.add_argument(
            "--with-demo-records",
            action="store_true",
            help="Also create sample orders, service requests, enrolments and export enquiries.",
        )
        parser.add_argument(
            "--skip-locations",
            action="store_true",
            help="Do not import the bundled Nigeria locations (use existing ones).",
        )

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_data is development-only and cannot run with DEBUG=False.")

        verbosity = int(options.get("verbosity", 1))
        library = ImageLibrary(
            enabled=not options["no_images"],
            verbosity=verbosity,
            logger=lambda message: self.stdout.write(message),
        )
        ctx = builders.SeedContext(
            command=self,
            library=library,
            with_demo_records=bool(options["with_demo_records"]),
            force_images=bool(options["force_images"]),
            verbosity=verbosity,
        )

        if options["dry_run"]:
            builders.dry_run(ctx, skip_locations=bool(options["skip_locations"]))
            return

        builders.run_all(ctx, skip_locations=bool(options["skip_locations"]))
        self._report(ctx)

    def _report(self, ctx: builders.SeedContext) -> None:
        c = ctx.counts
        lines = [
            self.style.SUCCESS("Seed data ready."),
            f"  Created this run: "
            f"{c['user']} users, {c['page']} pages, {c['hero_banner']} heroes, "
            f"{c['blog_post']} blog posts, {c['product']} products, "
            f"{c['product_listing']} listings, {c['warehouse']} warehouses, "
            f"{c['course']} courses, {c['training_session']} sessions.",
            "  Existing (kept): sites, roles and all human-edited content preserved.",
            "  Demo data is illustrative only — replace it before any real use.",
        ]
        for line in lines:
            self.stdout.write(line)
        for note in ctx.notes:
            self.stdout.write(self.style.WARNING(f"  note: {note}"))

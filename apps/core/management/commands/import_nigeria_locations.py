"""Import verified Nigeria location reference data (states + LGAs).

Usage
-----
    uv run python manage.py import_nigeria_locations --source data/ng_locations.csv
    uv run python manage.py import_nigeria_locations --source x.csv --dry-run
    uv run python manage.py import_nigeria_locations --source x.csv --strict

Expected CSV header (case-insensitive)::

    state_name,state_code,zone,lga_name,lga_code

* ``state_name`` / ``lga_name`` are required.
* ``state_code`` is required (short unique code, e.g. ``FC`` for FCT).
* ``zone`` must be one of NC, NE, NW, SE, SS, SW.
* ``lga_code`` is optional.

The command is idempotent (update-or-create) and records an audit row in
``NigeriaLocationImport``. ``--strict`` enforces the expected national totals
(37 state-level entries and 774 LGAs) and aborts otherwise.

This command deliberately does not bundle a dataset: an authoritative,
owner-approved source must be supplied and verified (see docs/DATABASE_DESIGN.md).
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

try:
    from apps.locations.models import LGA, GeopoliticalZone, NigeriaLocationImport, State
except Exception:  # pragma: no cover
    from apps.core.models import LGA, GeopoliticalZone, NigeriaLocationImport, State  # type: ignore[no-redef]

VALID_ZONES = {choice.value for choice in GeopoliticalZone}
REQUIRED_COLUMNS = {"state_name", "state_code", "zone", "lga_name"}


@dataclass
class ImportStats:
    states: int = 0
    lgas: int = 0
    state_rows: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


class Command(BaseCommand):
    help = "Import verified Nigeria states (36 + FCT) and LGAs from a CSV file."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--source", required=True, help="Path to the source CSV file.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate without writing to the database.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Abort unless counts match --expected-states/--expected-lgas.",
        )
        parser.add_argument("--expected-states", type=int, default=37)
        parser.add_argument("--expected-lgas", type=int, default=774)

    def handle(self, *args, **options) -> None:
        source = Path(options["source"])
        if not source.exists():
            raise CommandError(f"Source file not found: {source}")

        rows = self._read_rows(source)
        stats = self._validate(rows)
        self._check_totals(stats, options)

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(stats.state_rows)} states, {stats.lgas} LGAs validated. "
                    "No changes written."
                )
            )
            self._report_warnings(stats)
            return

        try:
            from apps.locations.models import Country
        except Exception:
            Country = None

        with transaction.atomic():
            ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria"})
            for row in rows:
                state, _ = State.objects.update_or_create(
                    code=row["state_code"].upper(),
                    defaults={
                        "name": row["state_name"].strip(),
                        "zone": row["zone"].upper(),
                        "slug": slugify(row["state_name"]),
                        "is_active": True,
                        "country": ng,
                    },
                )
                LGA.objects.update_or_create(
                    state=state,
                    name=row["lga_name"].strip(),
                    defaults={"code": row.get("lga_code", "").strip(), "is_active": True},
                )
            NigeriaLocationImport.objects.create(
                source=str(source),
                source_checksum=self._checksum(source),
                states_imported=len(stats.state_rows),
                lgas_imported=stats.lgas,
                succeeded=True,
                message="; ".join(stats.warnings),
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(stats.state_rows)} states and {stats.lgas} LGAs from {source}."
            )
        )
        self._report_warnings(stats)

    # -- helpers ------------------------------------------------------------
    def _read_rows(self, source: Path) -> list[dict[str, str]]:
        with source.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise CommandError("Source CSV is empty or has no header row.")
            normalised = {name.strip().lower(): name for name in reader.fieldnames}
            missing = REQUIRED_COLUMNS - set(normalised)
            if missing:
                raise CommandError(f"CSV is missing required columns: {sorted(missing)}")
            return [
                {key.strip().lower(): (value or "").strip() for key, value in row.items()}
                for row in reader
            ]

    def _validate(self, rows: list[dict[str, str]]) -> ImportStats:
        stats = ImportStats()
        seen_lga: set[tuple[str, str]] = set()
        codes_by_name: dict[str, str] = {}

        for line, row in enumerate(rows, start=2):
            state_name = row["state_name"]
            state_code = row["state_code"].upper()
            zone = row["zone"].upper()
            lga_name = row["lga_name"]
            if not state_name or not state_code or not lga_name:
                raise CommandError(
                    f"Line {line}: state_name, state_code and lga_name are required."
                )
            if zone not in VALID_ZONES:
                raise CommandError(
                    f"Line {line}: invalid zone '{zone}'. Expected one of {sorted(VALID_ZONES)}."
                )

            previous_code = codes_by_name.setdefault(state_name, state_code)
            if previous_code != state_code:
                raise CommandError(
                    f"Line {line}: state '{state_name}' has conflicting codes "
                    f"('{previous_code}' vs '{state_code}')."
                )

            key = (state_code, lga_name)
            if key in seen_lga:
                stats.warnings.append(
                    f"Duplicate LGA '{lga_name}' in state '{state_code}' ({line})."
                )
            seen_lga.add(key)

            stats.state_rows.add(state_name)
            stats.lgas += 1

        return stats

    def _check_totals(self, stats: ImportStats, options: dict) -> None:
        expected_states = options["expected_states"]
        expected_lgas = options["expected_lgas"]
        problems = []
        if len(stats.state_rows) != expected_states:
            problems.append(f"expected {expected_states} states, found {len(stats.state_rows)}")
        if stats.lgas != expected_lgas:
            problems.append(f"expected {expected_lgas} LGAs, found {stats.lgas}")
        if problems:
            message = "Nigeria location dataset validation failed: " + "; ".join(problems)
            if options["strict"]:
                raise CommandError(message)
            stats.warnings.append(message)

    def _report_warnings(self, stats: ImportStats) -> None:
        for warning in stats.warnings:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))

    @staticmethod
    def _checksum(source: Path) -> str:
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

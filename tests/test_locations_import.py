"""Tests for the Nigeria location importer management command."""

from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import LGA, NigeriaLocationImport, State

pytestmark = pytest.mark.django_db

FIXTURE = Path(__file__).parent / "fixtures" / "ng_locations_sample.csv"


def test_dry_run_does_not_write(db):
    call_command("import_nigeria_locations", "--source", str(FIXTURE), "--dry-run")

    assert State.objects.count() == 0
    assert LGA.objects.count() == 0
    assert NigeriaLocationImport.objects.count() == 0


def test_import_creates_states_and_lgas_and_audit_row():
    call_command(
        "import_nigeria_locations",
        "--source",
        str(FIXTURE),
        "--strict",
        "--expected-states",
        "2",
        "--expected-lgas",
        "5",
    )

    assert State.objects.count() == 2
    assert LGA.objects.count() == 5
    fct = State.objects.get(code="FC")
    assert fct.zone == "NC"
    assert fct.slug == "federal-capital-territory"
    assert LGA.objects.filter(state=fct).count() == 3

    audit = NigeriaLocationImport.objects.get()
    assert audit.succeeded is True
    assert audit.states_imported == 2
    assert audit.lgas_imported == 5
    assert len(audit.source_checksum) == 64


def test_import_is_idempotent():
    call_command("import_nigeria_locations", "--source", str(FIXTURE))
    call_command("import_nigeria_locations", "--source", str(FIXTURE))

    assert State.objects.count() == 2
    assert LGA.objects.count() == 5
    assert NigeriaLocationImport.objects.count() == 2


def test_strict_mode_fails_on_wrong_totals():
    with pytest.raises(CommandError):
        call_command(
            "import_nigeria_locations",
            "--source",
            str(FIXTURE),
            "--strict",
            "--expected-states",
            "37",
            "--expected-lgas",
            "774",
        )


def test_missing_source_file_raises():
    with pytest.raises(CommandError):
        call_command("import_nigeria_locations", "--source", "does-not-exist.csv")


def test_invalid_zone_is_rejected(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "state_name,state_code,zone,lga_name,lga_code\nLagos,LA,XX,Ikeja,\n",
        encoding="utf-8",
    )

    with pytest.raises(CommandError):
        call_command("import_nigeria_locations", "--source", str(bad))

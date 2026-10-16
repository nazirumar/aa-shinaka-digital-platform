"""Phase 13 — file upload security tests (Step 4).

Covers: EICAR fixture detection (the safe antivirus test vector), executable
magic sniffing, quarantine storage, scan-failure handling under both
enforcement policies, download blocking for infected/unscanned files, lazy
scanning of legacy files, and authorised release.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core.models import FileScanRecord
from apps.core.upload_security import (
    EICAR_SIGNATURE,
    bind_scanned_file,
    enforce_downloadable,
    release_scan,
    scan_bytes,
    screen_upload,
)
from apps.dashboard.models import AuditLog

User = get_user_model()
# db access + all quarantine writes redirected to a per-test temp MEDIA_ROOT.
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]

# The standard EICAR test file: the *safe* industry fixture that real AV
# products flag. Nothing about it executes or harms a machine.
EICAR_FILE = SimpleUploadedFile("eicar.txt", EICAR_SIGNATURE, content_type="text/plain")
EICAR_PDF = SimpleUploadedFile("invoice.pdf", EICAR_SIGNATURE, content_type="application/pdf")


# ---------------------------------------------------------------------------
# Scanner primitives
# ---------------------------------------------------------------------------
def test_builtin_scanner_flags_eicar_anywhere_in_file():
    result = scan_bytes("note.txt", b"hello " + EICAR_SIGNATURE + b" world")
    assert not result.clean
    assert result.threat == "Eicar-Test-Signature"


def test_builtin_scanner_flags_renamed_executable():
    result = scan_bytes("document.pdf", b"MZ\x90\x00 this is not really a pdf")
    assert not result.clean
    assert "executable" in result.threat.lower()


def test_builtin_scanner_flags_elf_in_image():
    result = scan_bytes("photo.png", b"\x7fELF\x02\x01\x01")
    assert not result.clean


def test_builtin_scanner_allows_plain_text():
    assert scan_bytes("report.txt", b"quarterly figures").clean
    assert scan_bytes("data.csv", b"a,b,c\n1,2,3\n").clean


def test_builtin_scanner_allows_pdf_header():
    assert scan_bytes("doc.pdf", b"%PDF-1.7 real content").clean


def test_text_files_skip_magic_check_but_not_eicar():
    # A text file may start with anything, but EICAR still triggers.
    assert scan_bytes("notes.txt", b"MZ is initials").clean
    assert not scan_bytes("notes.txt", EICAR_SIGNATURE).clean


# ---------------------------------------------------------------------------
# Upload screening
# ---------------------------------------------------------------------------
def test_clean_upload_produces_clean_record(customer):
    upload = SimpleUploadedFile("report.pdf", b"%PDF-1.7 figures")
    record = screen_upload(upload, kind="support_attachment", actor=customer)
    assert record.status == FileScanRecord.Status.CLEAN
    assert record.uploaded_by == customer
    assert record.scanned_at is not None
    assert record.sha256


def test_eicar_upload_rejected_and_quarantined(customer):
    with pytest.raises(ValidationError):
        screen_upload(EICAR_PDF, kind="support_attachment", actor=customer)
    record = FileScanRecord.objects.get()
    assert record.status == FileScanRecord.Status.INFECTED
    assert record.threat_name == "Eicar-Test-Signature"
    # The bytes are preserved in quarantine for forensics.
    assert record.quarantine_path.startswith("quarantine/")
    assert (Path(settings.MEDIA_ROOT) / record.quarantine_path).exists()
    assert AuditLog.objects.filter(action="upload.rejected_malware").exists()


def test_infected_upload_never_reaches_final_storage(customer):
    with pytest.raises(ValidationError):
        screen_upload(EICAR_PDF, kind="support_attachment", actor=customer)
    record = FileScanRecord.objects.get()
    # Nothing was bound to a final path: the model was never saved.
    assert record.file_path == ""


def test_screen_upload_requires_a_file(customer):
    with pytest.raises(ValidationError):
        screen_upload(None, kind="support_attachment", actor=customer)


# ---------------------------------------------------------------------------
# Scan failure handling (both policies)
# ---------------------------------------------------------------------------
class _FailingScanner:
    """Stand-in for an unavailable clamd backend."""

    @staticmethod
    def failing_scan(name, data):
        from apps.core.upload_security import ScanResult

        return ScanResult(False, "clamd", error="clamd unreachable: connection refused")


@override_settings(UPLOAD_SCAN_ENFORCEMENT="enforce")
def test_scan_failure_rejects_upload_under_enforce(customer, monkeypatch):
    monkeypatch.setattr("apps.core.upload_security.scan_bytes", _FailingScanner.failing_scan)
    with pytest.raises(ValidationError):
        screen_upload(
            SimpleUploadedFile("doc.pdf", b"%PDF-1.7 x"), kind="support_attachment", actor=customer
        )
    record = FileScanRecord.objects.get()
    assert record.status == FileScanRecord.Status.ERROR
    assert record.quarantine_path  # held for forensics, not stored as a document
    assert AuditLog.objects.filter(action="upload.scan_error").exists()


@override_settings(UPLOAD_SCAN_ENFORCEMENT="log")
def test_scan_failure_allows_upload_under_log_policy(customer, monkeypatch):
    monkeypatch.setattr("apps.core.upload_security.scan_bytes", _FailingScanner.failing_scan)
    record = screen_upload(
        SimpleUploadedFile("doc.pdf", b"%PDF-1.7 x"), kind="support_attachment", actor=customer
    )
    assert record.status == FileScanRecord.Status.ERROR
    assert AuditLog.objects.filter(action="upload.scan_error").exists()


# ---------------------------------------------------------------------------
# Download enforcement
# ---------------------------------------------------------------------------
def _bound_record(user, *, path="support_attachments/2026/01/doc.pdf", status):
    return FileScanRecord.objects.create(
        sha256="a" * 64,
        file_path=path,
        original_name="doc.pdf",
        kind="support_attachment",
        status=status,
        scanned_at=None,
        uploaded_by=user,
    )


class _FakeFieldFile:
    def __init__(self, name, data=b"%PDF-1.7 x"):
        self.name = name
        self._data = data

    def open(self, mode="rb"):
        import io

        self._buffer = io.BytesIO(self._data)
        return self

    def read(self, limit=-1):
        return self._buffer.read(limit)

    def close(self):
        pass


def test_download_blocked_for_infected_file(customer):
    _bound_record(customer, status=FileScanRecord.Status.INFECTED)
    with pytest.raises(PermissionDenied):
        enforce_downloadable(_FakeFieldFile("support_attachments/2026/01/doc.pdf"))
    assert AuditLog.objects.filter(action="upload.download_blocked").exists()


@override_settings(UPLOAD_SCAN_ENFORCEMENT="enforce")
def test_download_blocked_for_unscanned_file_under_enforce(customer):
    _bound_record(customer, status=FileScanRecord.Status.ERROR)
    with pytest.raises(PermissionDenied):
        enforce_downloadable(_FakeFieldFile("support_attachments/2026/01/doc.pdf"))


@override_settings(UPLOAD_SCAN_ENFORCEMENT="log")
def test_download_allowed_for_unscanned_file_under_log_policy(customer):
    _bound_record(customer, status=FileScanRecord.Status.ERROR)
    enforce_downloadable(_FakeFieldFile("support_attachments/2026/01/doc.pdf"))
    assert AuditLog.objects.filter(action="upload.download_unscanned").exists()


def test_download_allowed_for_clean_file(customer):
    _bound_record(customer, status=FileScanRecord.Status.CLEAN)
    enforce_downloadable(_FakeFieldFile("support_attachments/2026/01/doc.pdf"))


def test_unrecorded_file_is_scanned_lazily_and_served(customer):
    field = _FakeFieldFile("support_attachments/2026/01/legacy.pdf")
    enforce_downloadable(field, kind="support_attachment", actor=customer)
    record = FileScanRecord.objects.get(file_path=field.name)
    assert record.status == FileScanRecord.Status.CLEAN


def test_unrecorded_infected_file_is_blocked_on_download(customer):
    field = _FakeFieldFile("support_attachments/2026/01/evil.pdf", EICAR_SIGNATURE)
    with pytest.raises(PermissionDenied):
        enforce_downloadable(field, kind="support_attachment", actor=customer)
    record = FileScanRecord.objects.get(file_path=field.name)
    assert record.status == FileScanRecord.Status.INFECTED


def test_trusted_files_skip_the_gate(customer):
    # e.g. platform-generated invoices/reports: no user uploaded these bytes.
    enforce_downloadable(_FakeFieldFile("invoices/2026/01/x.pdf"), trusted=True)
    assert FileScanRecord.objects.count() == 0


def test_empty_field_file_is_allowed():
    enforce_downloadable(None)


# ---------------------------------------------------------------------------
# End-to-end: a support attachment upload is screened and its download gated
# ---------------------------------------------------------------------------
def test_support_ticket_upload_rejects_eicar(client, customer):
    client.force_login(customer)
    response = client.post(
        reverse("support:ticket_create"),
        {
            "subject": "Help with my order",
            "message": "Something is wrong",
            "category": "general",
            "priority": "normal",
            "attachments": EICAR_FILE,
        },
        follow=True,
    )
    # The ticket flow surfaces the rejection rather than storing the file.
    assert FileScanRecord.objects.filter(status=FileScanRecord.Status.INFECTED).exists()
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Authorised release
# ---------------------------------------------------------------------------
def test_release_requires_authentication(customer):
    record = _bound_record(customer, status=FileScanRecord.Status.ERROR)
    with pytest.raises(PermissionDenied):
        release_scan(record, actor=None)


def test_release_requires_media_capability(owner, staff_user, customer):
    record = _bound_record(customer, status=FileScanRecord.Status.ERROR)
    with pytest.raises(PermissionDenied):
        release_scan(record, actor=staff_user)


def test_infected_files_can_never_be_released(owner, customer):
    record = _bound_record(customer, status=FileScanRecord.Status.INFECTED)
    with pytest.raises(ValidationError):
        release_scan(record, actor=owner)
    record.refresh_from_db()
    assert record.status == FileScanRecord.Status.INFECTED


def test_superuser_releases_error_record(owner, customer):
    record = _bound_record(customer, status=FileScanRecord.Status.ERROR)
    released = release_scan(record, actor=owner, note="Reviewed manually.")
    assert released.status == FileScanRecord.Status.RELEASED
    assert released.released_by == owner
    assert released.released_at is not None
    assert AuditLog.objects.filter(action="upload.released").exists()
    # After release the file is downloadable again.
    enforce_downloadable(_FakeFieldFile(record.file_path))


def test_releasing_a_clean_record_is_a_noop(owner, customer):
    record = _bound_record(customer, status=FileScanRecord.Status.CLEAN)
    assert release_scan(record, actor=owner).status == FileScanRecord.Status.CLEAN


# ---------------------------------------------------------------------------
# Binding + integration helpers
# ---------------------------------------------------------------------------
def test_bind_scanned_file_sets_path(customer):
    upload = SimpleUploadedFile("doc.pdf", b"%PDF-1.7 x")
    record = screen_upload(upload, kind="export_document", actor=customer)

    class _Field:
        name = "export/documents/2026/01/doc.pdf"

    bind_scanned_file(record, _Field())
    record.refresh_from_db()
    assert record.file_path == _Field.name


# ---------------------------------------------------------------------------
# Staff dashboard: security review + authorised release
# ---------------------------------------------------------------------------
def test_upload_scan_dashboard_requires_media_capability(client, staff_user, customer):
    _bound_record(customer, status=FileScanRecord.Status.ERROR)
    client.force_login(staff_user)  # sales officer: no media.manage
    response = client.get(reverse("dashboard:upload_scans"))
    assert response.status_code in (302, 403)


def test_upload_scan_dashboard_lists_records(client, owner, customer):
    _bound_record(customer, status=FileScanRecord.Status.ERROR, path="support_attachments/x.pdf")
    client.force_login(owner)
    response = client.get(reverse("dashboard:upload_scans"))
    assert response.status_code == 200
    assert b"Upload security" in response.content


def test_upload_scan_release_requires_post(client, owner, customer):
    record = _bound_record(customer, status=FileScanRecord.Status.ERROR)
    client.force_login(owner)
    assert client.get(reverse("dashboard:upload_scan_release", args=[record.pk])).status_code == 405


def test_upload_scan_release_marks_record_released(client, owner, customer):
    record = _bound_record(customer, status=FileScanRecord.Status.ERROR)
    client.force_login(owner)
    response = client.post(
        reverse("dashboard:upload_scan_release", args=[record.pk]),
        {"note": "Reviewed manually."},
        follow=True,
    )
    assert response.status_code == 200
    record.refresh_from_db()
    assert record.status == FileScanRecord.Status.RELEASED
    assert record.released_by == owner


def test_upload_scan_release_refuses_infected(client, owner, customer):
    record = _bound_record(customer, status=FileScanRecord.Status.INFECTED)
    client.force_login(owner)
    client.post(reverse("dashboard:upload_scan_release", args=[record.pk]), follow=True)
    record.refresh_from_db()
    assert record.status == FileScanRecord.Status.INFECTED

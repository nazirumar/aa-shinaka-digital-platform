"""Upload scanning, quarantine and download enforcement (Phase 13, Step 4).

Every user-supplied document passes through :func:`screen_upload` before it is
stored, and every private download passes through :func:`enforce_downloadable`
before bytes are served. The scanner stack is pluggable:

* a dependency-free built-in signature scanner (the EICAR standard anti-virus
  test fixture plus executable-header detection) always runs;
* ClamAV's ``clamd`` is used as well when ``CLAMAV_SOCKET`` or ``CLAMAV_HOST``
  is configured, speaking the ``INSTREAM`` protocol over a raw socket.

Scan *failures* (clamd unreachable, oversized reads) are never treated as a
clean result: under ``UPLOAD_SCAN_ENFORCEMENT=enforce`` they fail closed, and
under ``log`` they are audited and allowed through. Positively identified
threats are always rejected and always blocked from download, in either mode.
"""

from __future__ import annotations

import hashlib
import logging
import socket
import struct
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.core.models import FileScanRecord

logger = logging.getLogger(__name__)

# The EICAR standard anti-malware test string. It is *not* malware: it is the
# industry-standard safe fixture used to prove a scanner is wired up correctly.
EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

# Leading bytes that mean "this is an executable", used to catch renamed
# binaries smuggled in with a document/image extension.
EXECUTABLE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"MZ", "DOS/PE executable"),
    (b"\x7fELF", "ELF executable"),
    (b"\xca\xfe\xba\xbe", "Mach-O/Java class file"),
    (b"\xfe\xed\xfa\xce", "Mach-O executable"),
    (b"\xfe\xed\xfa\xcf", "Mach-O executable"),
    (b"\xcf\xfa\xed\xfe", "Mach-O executable"),
)

# Text formats may legitimately begin with any bytes; never magic-check them.
TEXT_EXTENSIONS = frozenset({"txt", "csv", "md", "json", "log"})

CLAMD_CHUNK = 2048


@dataclass(frozen=True)
class ScanResult:
    """Outcome of one scan: exactly one of clean / threat / error is set."""

    clean: bool
    scanner: str
    threat: str = ""
    error: str = ""


def _builtin_scan(data: bytes, name: str) -> ScanResult:
    """Signature scan that always works offline (EICAR + executable magic)."""
    if EICAR_SIGNATURE in data:
        return ScanResult(False, "builtin", threat="Eicar-Test-Signature")
    extension = Path(name).suffix.lower().lstrip(".")
    if extension not in TEXT_EXTENSIONS:
        for magic, label in EXECUTABLE_MAGIC:
            if data.startswith(magic):
                return ScanResult(False, "builtin", threat=label)
    return ScanResult(True, "builtin")


def _clamd_scan(data: bytes) -> ScanResult:
    """Scan with clamd over its INSTREAM protocol (unix socket or TCP)."""
    socket_path = settings.CLAMAV_SOCKET
    timeout = settings.CLAMAV_TIMEOUT
    try:
        if socket_path:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(socket_path)
        else:
            sock = socket.create_connection(
                (settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=timeout
            )
    except OSError as exc:
        return ScanResult(False, "clamd", error=f"clamd unreachable: {exc}")

    try:
        sock.sendall(b"zINSTREAM\0")
        view = memoryview(data)
        for start in range(0, len(data), CLAMD_CHUNK):
            chunk = view[start : start + CLAMD_CHUNK]
            sock.sendall(struct.pack(">I", len(chunk)) + chunk)
        sock.sendall(struct.pack(">I", 0))
        response = b""
        while not response.endswith(b"\0"):
            piece = sock.recv(4096)
            if not piece:
                break
            response += piece
    except OSError as exc:
        return ScanResult(False, "clamd", error=f"clamd scan failed: {exc}")
    finally:
        sock.close()

    text = response.decode("utf-8", "replace").strip("\x00")
    if text.startswith("1:OK"):
        return ScanResult(True, "clamd")
    if text.startswith("1:FOUND"):
        parts = text.split(":", 2)
        return ScanResult(False, "clamd", threat=parts[2].strip() if len(parts) > 2 else "Threat")
    return ScanResult(False, "clamd", error=f"unexpected clamd response: {text[:200]}")


def scan_bytes(name: str, data: bytes) -> ScanResult:
    """Run the configured scanner stack. A threat short-circuits; a clamd
    *failure* degrades to an error verdict (never to clean)."""
    builtin = _builtin_scan(data, name)
    if not builtin.clean:
        return builtin
    if not (settings.CLAMAV_SOCKET or settings.CLAMAV_HOST):
        return builtin
    clamd = _clamd_scan(data)
    if not clamd.clean:
        return clamd
    return ScanResult(True, f"{builtin.scanner}+{clamd.scanner}")


def _read_upload(file, limit: int) -> bytes:
    """Read an upload's bytes without disturbing its seek position."""
    position = file.tell() if hasattr(file, "tell") else 0
    file.seek(0)
    try:
        return file.read(limit)
    finally:
        file.seek(position)


def _quarantine(data: bytes, name: str, sha256: str) -> str:
    """Persist a rejected upload's bytes for forensics. Returns the path."""
    root = Path(settings.MEDIA_ROOT) / "quarantine"
    stamp = timezone.now().strftime("%Y/%m")
    safe_name = "".join(c for c in Path(name).name if c.isalnum() or c in "._-")[:80] or "upload"
    target = root / stamp / f"{sha256[:16]}-{safe_name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    # Store a POSIX-style relative path so records are portable across OSes.
    return target.relative_to(settings.MEDIA_ROOT).as_posix()


def _enforcing() -> bool:
    return settings.UPLOAD_SCAN_ENFORCEMENT == "enforce"


def _read_limit() -> int:
    return settings.UPLOAD_SCAN_MAX_BYTES


def _scan_error(result: ScanResult, *, name, sha256, size, kind, data, actor, request):
    """Handle a scanner failure per the configured policy. Raises under
    ``enforce``; returns an error-record (upload proceeds) under ``log``."""
    quarantine_path = _quarantine(data, name, sha256)
    record = FileScanRecord.objects.create(
        sha256=sha256,
        original_name=name[:255],
        size_bytes=size,
        kind=kind,
        status=FileScanRecord.Status.ERROR,
        scanner=result.scanner,
        detail=result.error[:2000],
        quarantine_path=quarantine_path,
        uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
        scanned_at=timezone.now(),
    )
    record_audit(
        actor=actor,
        action="upload.scan_error",
        target=record,
        after={"kind": kind, "name": name[:120], "enforcement": settings.UPLOAD_SCAN_ENFORCEMENT},
        request=request,
        note=result.error[:300],
    )
    if _enforcing():
        raise ValidationError(
            "This file could not be scanned for viruses and was not accepted. "
            "Please try again later or contact support."
        )
    logger.warning("Upload %s passed unscanned (policy=log): %s", name, result.error)
    return record


# NB: deliberately *not* wrapped in @transaction.atomic — the forensic record
# and audit entry must survive the ValidationError raised below for threats;
# an atomic block would roll them back along with the exception.
def screen_upload(file, *, kind: str, actor=None, request=None) -> FileScanRecord:
    """Scan an inbound upload before it is stored.

    Returns a ``clean`` record the caller must bind with
    :func:`bind_scanned_file` once the model is saved. Raises
    ``ValidationError`` for threats, and for scan failures under the
    ``enforce`` policy.
    """
    if file is None:
        raise ValidationError("A file is required.")
    name = getattr(file, "name", "") or "upload"
    limit = _read_limit()
    data = _read_upload(file, limit)
    size = getattr(file, "size", len(data)) or len(data)
    sha256 = hashlib.sha256(data).hexdigest()

    result = scan_bytes(name, data)
    if result.error:
        return _scan_error(
            result,
            name=name,
            sha256=sha256,
            size=size,
            kind=kind,
            data=data,
            actor=actor,
            request=request,
        )

    if not result.clean:
        quarantine_path = _quarantine(data, name, sha256)
        record = FileScanRecord.objects.create(
            sha256=sha256,
            original_name=name[:255],
            size_bytes=size,
            kind=kind,
            status=FileScanRecord.Status.INFECTED,
            scanner=result.scanner,
            threat_name=result.threat[:255],
            quarantine_path=quarantine_path,
            uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
            scanned_at=timezone.now(),
        )
        record_audit(
            actor=actor,
            action="upload.rejected_malware",
            target=record,
            after={"kind": kind, "name": name[:120], "threat": result.threat},
            request=request,
        )
        raise ValidationError("This file was rejected because it contains malicious content.")

    return FileScanRecord.objects.create(
        sha256=sha256,
        original_name=name[:255],
        size_bytes=size,
        kind=kind,
        status=FileScanRecord.Status.CLEAN,
        scanner=result.scanner,
        uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
        scanned_at=timezone.now(),
    )


def screen_uploads(files, *, kind: str, actor=None, request=None):
    """Screen several uploads up-front and return ``(upload, record)`` pairs.

    Call this *before* opening the caller's write transaction: a rejected
    upload raises ``ValidationError``, and any surrounding ``atomic`` block
    would otherwise roll the forensic record and quarantine entry back with it.
    """
    return [
        (upload, screen_upload(upload, kind=kind, actor=actor, request=request))
        for upload in (files or [])
    ]


def bind_scanned_file(record: FileScanRecord, field_file) -> FileScanRecord:
    """Attach the stored path to a scan record after the model saved the file."""
    record.file_path = field_file.name[:500]
    record.save(update_fields=["file_path", "updated_at"])
    return record


def _latest_record(path: str) -> FileScanRecord | None:
    if not path:
        return None
    return FileScanRecord.objects.filter(file_path=path).order_by("-created_at").first()


def enforce_downloadable(field_file, *, kind: str = "", actor=None, request=None, trusted=False):
    """Gate a private download on the file's scan status.

    ``trusted`` marks platform-generated files (reports, invoices) that no user
    uploaded. Unrecorded files are scanned lazily on first access; anything
    infected is blocked always, and anything unscanned/errored is blocked under
    the ``enforce`` policy.
    """
    if trusted or not field_file:
        return
    path = field_file.name
    record = _latest_record(path)
    if record is None:
        record = _lazy_scan(field_file, kind=kind, actor=actor)

    if record.status == FileScanRecord.Status.INFECTED:
        record_audit(
            actor=actor,
            action="upload.download_blocked",
            target=record,
            after={"path": path[:200], "reason": "infected"},
            request=request,
        )
        raise PermissionDenied("This file is not available for download.")

    if record.status in (FileScanRecord.Status.CLEAN, FileScanRecord.Status.RELEASED):
        return

    # pending / error
    if _enforcing():
        record_audit(
            actor=actor,
            action="upload.download_blocked",
            target=record,
            after={"path": path[:200], "reason": record.status},
            request=request,
        )
        raise PermissionDenied("This file has not cleared security scanning yet.")
    record_audit(
        actor=actor,
        action="upload.download_unscanned",
        target=record,
        after={"path": path[:200], "status": record.status},
        request=request,
        note="Served under UPLOAD_SCAN_ENFORCEMENT=log.",
    )


def _lazy_scan(field_file, *, kind: str, actor) -> FileScanRecord:
    """Scan an already-stored file that has no record (legacy uploads)."""
    field_file.open("rb")
    try:
        data = field_file.read(_read_limit())
    finally:
        field_file.close()
    name = field_file.name.rsplit("/", 1)[-1]
    sha256 = hashlib.sha256(data).hexdigest()
    result = scan_bytes(name, data)
    if result.error:
        status = FileScanRecord.Status.ERROR
        detail = result.error[:2000]
        threat = ""
    elif result.clean:
        status, detail, threat = FileScanRecord.Status.CLEAN, "", ""
    else:
        status, detail, threat = (
            FileScanRecord.Status.INFECTED,
            "",
            result.threat[:255],
        )
    return FileScanRecord.objects.create(
        sha256=sha256,
        file_path=field_file.name[:500],
        original_name=name[:255],
        size_bytes=len(data),
        kind=kind,
        status=status,
        scanner=result.scanner,
        threat_name=threat,
        detail=detail,
        uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
        scanned_at=timezone.now(),
    )


@transaction.atomic
def release_scan(record: FileScanRecord, *, actor, request=None, note: str = "") -> FileScanRecord:
    """Authorised release of a quarantined/blocked file after review.

    Re-runs the scan first: a threat is never releasable, a recovered scanner
    yields a clean release, and a still-failing scanner requires the reviewer's
    explicit override. Every release is audited.
    """
    from apps.accounts.permissions import has_capability
    from apps.accounts.roles import Capability

    if not (actor and getattr(actor, "is_authenticated", False)):
        raise PermissionDenied("Only an authenticated reviewer may release a file.")
    if not (actor.is_superuser or has_capability(actor, Capability.MEDIA_MANAGE)):
        raise PermissionDenied("Releasing scanned files requires the media management capability.")
    if record.status == FileScanRecord.Status.INFECTED:
        raise ValidationError("Files identified as malware cannot be released.")
    if record.status in (FileScanRecord.Status.CLEAN, FileScanRecord.Status.RELEASED):
        return record

    result: ScanResult | None = None
    # Re-scan the quarantined bytes when we still have them.
    if record.quarantine_path:
        stored = Path(settings.MEDIA_ROOT) / record.quarantine_path
        if stored.exists():
            result = scan_bytes(record.original_name or "file", stored.read_bytes())
    if result is None:
        detail = "Manual release: no stored bytes available to re-scan."
    elif not result.clean and not result.error:
        raise ValidationError("The file still fails scanning and cannot be released.")
    elif result.error:
        # The scanner is down: releasing is an explicit human override.
        detail = f"Manual release while scanner unavailable: {result.error}"
    else:
        detail = f"Manual release by {actor}; re-scan verdict: clean"

    record.status = FileScanRecord.Status.RELEASED
    record.released_at = timezone.now()
    record.released_by = actor
    record.detail = (detail + (" " + note if note else ""))[:2000]
    record.save(update_fields=["status", "released_at", "released_by", "detail", "updated_at"])
    record_audit(
        actor=actor,
        action="upload.released",
        target=record,
        after={"path": (record.file_path or record.quarantine_path)[:200]},
        request=request,
        note=note[:400],
    )
    return record

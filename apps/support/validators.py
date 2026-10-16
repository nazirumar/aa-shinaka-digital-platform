"""Support attachment validation (secure uploads — Task 19)."""

from __future__ import annotations

import os

from django.core.exceptions import ValidationError

ALLOWED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".txt",
    ".csv",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_attachment(upload) -> None:
    """Reject disallowed extensions and oversized uploads."""
    name = getattr(upload, "name", "") or ""
    extension = os.path.splitext(name)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Files of type '{extension or 'unknown'}' are not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )
    size = getattr(upload, "size", 0) or 0
    if size > MAX_UPLOAD_BYTES:
        raise ValidationError("Attachments must be 10 MB or smaller.")

"""File-upload validation for export documents (Task 14).

Uploads are private trade documents. We validate the extension and size on the
server (never trusting the browser) and store them under a private media path
that is only ever served through an authorised view.
"""

from __future__ import annotations

import os

from django.core.exceptions import ValidationError

ALLOWED_EXTENSIONS = frozenset(
    {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt"}
)
MAX_UPLOAD_SIZE = 15 * 1024 * 1024  # 15 MB


def validate_export_document(file) -> None:
    """Validate an uploaded export document (extension + size)."""
    name = getattr(file, "name", "") or ""
    extension = os.path.splitext(name)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            "Unsupported file type. Allowed: " + ", ".join(sorted(ALLOWED_EXTENSIONS)) + "."
        )
    size = getattr(file, "size", 0) or 0
    if size > MAX_UPLOAD_SIZE:
        raise ValidationError("File is too large (maximum 15 MB).")

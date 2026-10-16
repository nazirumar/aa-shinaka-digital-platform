"""Validation helpers for the training domain.

Course/lesson resource uploads are private learning material; the extension and
size are validated on the server (never trusting the browser) and the file is
only ever served through an authorised view.
"""

from __future__ import annotations

import os

from django.core.exceptions import ValidationError

ALLOWED_RESOURCE_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".csv",
        ".txt",
        ".zip",
    }
)
MAX_RESOURCE_SIZE = 25 * 1024 * 1024  # 25 MB

ALLOWED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


def validate_resource_file(file) -> None:
    name = getattr(file, "name", "") or ""
    extension = os.path.splitext(name)[1].lower()
    if extension not in ALLOWED_RESOURCE_EXTENSIONS:
        raise ValidationError(
            "Unsupported file type. Allowed: "
            + ", ".join(sorted(ALLOWED_RESOURCE_EXTENSIONS))
            + "."
        )
    size = getattr(file, "size", 0) or 0
    if size > MAX_RESOURCE_SIZE:
        raise ValidationError("File is too large (maximum 25 MB).")


def validate_image_file(file) -> None:
    name = getattr(file, "name", "") or ""
    extension = os.path.splitext(name)[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError("Unsupported image type. Allowed: jpg, jpeg, png, webp, gif.")
    size = getattr(file, "size", 0) or 0
    if size > MAX_IMAGE_SIZE:
        raise ValidationError("Image is too large (maximum 5 MB).")

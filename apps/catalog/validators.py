"""Validators for catalog models and uploads."""

from __future__ import annotations

from django.core.exceptions import ValidationError


def validate_image_size(value) -> None:
    """Reject images larger than 5 MB."""
    max_bytes = 5 * 1024 * 1024
    if value.size > max_bytes:
        raise ValidationError("Image file is too large (maximum 5 MB).")

"""MFA models for privileged accounts."""

from __future__ import annotations

import secrets
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone

from .crypto import decrypt, encrypt


class MFADevice(models.Model):
    """TOTP-based MFA device for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa_device",
    )
    secret_encrypted = models.CharField(max_length=255, blank=True)
    is_confirmed = models.BooleanField(default=False)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]

    def __str__(self) -> str:
        return f"MFADevice(user={self.user_id}, confirmed={self.is_confirmed})"

    def set_secret(self, secret: str) -> None:
        self.secret_encrypted = encrypt(secret)

    def get_secret(self) -> str:
        try:
            return decrypt(self.secret_encrypted)
        except Exception:
            return ""


class MFARecoveryCode(models.Model):
    """Hashed recovery codes for MFA fallback."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa_recovery_codes",
    )
    code_hash = models.CharField(max_length=255)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["created_at"]

    def __str__(self) -> str:
        return f"MFARecoveryCode(user={self.user_id}, used={self.used_at is not None})"

    @staticmethod
    def generate_code() -> str:
        # Generate a short human-friendly recovery code
        return secrets.token_hex(8).upper()

    def mark_used(self) -> None:
        if self.used_at is None:
            self.used_at = timezone.now()
            self.save(update_fields=["used_at"])

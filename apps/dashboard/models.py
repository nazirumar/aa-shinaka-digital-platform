"""Dashboard and cross-cutting operational models.

``AuditLog`` is append-only from the application's perspective: it is written
only through ``apps.core.audit.record_audit`` and is not editable in the Django
admin. Reporting models arrive in later phases (see docs/DATABASE_DESIGN.md).
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only record of security- and business-sensitive actions."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=60, db_index=True)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    note = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        get_latest_by = "created_at"
        verbose_name = "Audit log entry"
        verbose_name_plural = "Audit log"
        indexes: ClassVar[list] = [
            models.Index(fields=["target_type", "target_id"], name="audit_target_idx"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_idx"),
        ]

    def __str__(self) -> str:
        who = self.actor or "system"
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} by {who}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Audit log entries are append-only and cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit log entries cannot be deleted from the application.")

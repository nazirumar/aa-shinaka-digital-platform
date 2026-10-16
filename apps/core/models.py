"""Core domain models.

This module holds the shared, cross-cutting building blocks used by every other
app (timestamps, soft deletion) plus the verified Nigeria location reference
data (36 states + FCT, and their LGAs / area councils).
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Abstract base adding immutable ``created_at`` and mutable ``updated_at``."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


class UUIDTimeStampedModel(models.Model):
    """Abstract base with a UUID primary key plus created/updated timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet that archives instead of physically deleting by default."""

    def alive(self) -> "SoftDeleteQuerySet":
        return self.filter(is_deleted=False)

    def archived(self) -> "SoftDeleteQuerySet":
        return self.filter(is_deleted=True)

    def delete(self):  # type: ignore[override]
        return self.update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Default manager that hides archived rows."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return super().get_queryset().filter(is_deleted=False)


class SoftDeleteModel(TimeStampedModel):
    """Abstract base providing soft deletion + archival audit fields.

    ``objects`` excludes archived rows; ``all_objects`` includes everything.
    """

    is_deleted = models.BooleanField(default=False, db_index=True, editable=False)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    all_objects = models.Manager()
    objects = SoftDeleteManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):  # type: ignore[override]
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["is_deleted", "deleted_at", "updated_at"])

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self) -> None:
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


class FileScanRecord(TimeStampedModel):
    """Audit record for an uploaded file's malware scan lifecycle (Phase 13).

    One row per scan attempt. ``file_path`` is the stored name once the file is
    bound to its model field; freshly rejected uploads keep only a quarantine
    copy. Downloads consult the latest record for a path: anything that is not
    ``clean``/``released`` is blocked when enforcement is on.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CLEAN = "clean", "Clean"
        INFECTED = "infected", "Infected"
        ERROR = "error", "Scan error"
        RELEASED = "released", "Released"

    sha256 = models.CharField(max_length=64, db_index=True)
    file_path = models.CharField(max_length=500, blank=True, db_index=True)
    original_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    kind = models.CharField(max_length=50, blank=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    scanner = models.CharField(max_length=50, blank=True)
    threat_name = models.CharField(max_length=255, blank=True)
    detail = models.TextField(blank=True)
    quarantine_path = models.CharField(max_length=500, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    scanned_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.original_name or self.sha256[:12]} [{self.status}]"

    @property
    def is_downloadable(self) -> bool:
        return self.status in (self.Status.CLEAN, self.Status.RELEASED)


# Backwards compatibility exports (placed after base classes)
try:  # pragma: no cover
    from apps.locations.models import (  # noqa: F401
        LGA,
        City,
        Country,
        GeopoliticalZone,
        NigeriaLocationImport,
        State,
    )
except Exception:  # pragma: no cover
    pass

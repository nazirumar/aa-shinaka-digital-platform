"""Core domain models.

This module holds the shared, cross-cutting building blocks used by every other
app (timestamps, soft deletion) plus the verified Nigeria location reference
data (36 states + FCT, and their LGAs / area councils).
"""

from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Abstract base adding immutable ``created_at`` and mutable ``updated_at``."""

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

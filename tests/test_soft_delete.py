"""Tests for the abstract soft-delete mixin.

The mixin is abstract and has no concrete table in Phase 1, so a throwaway
model is created and dropped using the schema editor for the duration of the
tests.
"""

import pytest
from django.db import connection, models

from apps.core.models import SoftDeleteModel


class Archivable(SoftDeleteModel):
    name = models.CharField(max_length=32)

    class Meta:
        app_label = "core"


@pytest.fixture
def archivable_table(db):
    with connection.schema_editor() as schema:
        schema.create_model(Archivable)
    yield
    with connection.schema_editor() as schema:
        schema.delete_model(Archivable)


def test_soft_delete_hides_row_from_default_manager(archivable_table):
    row = Archivable.objects.create(name="record")

    row.delete()

    assert Archivable.objects.filter(pk=row.pk).count() == 0
    assert Archivable.all_objects.filter(pk=row.pk).count() == 1
    assert row.is_deleted is True
    assert row.deleted_at is not None


def test_queryset_delete_archives_all_rows(archivable_table):
    Archivable.objects.create(name="a")
    Archivable.objects.create(name="b")

    Archivable.objects.all().delete()

    assert Archivable.objects.count() == 0
    assert Archivable.all_objects.count() == 2


def test_restore_brings_row_back(archivable_table):
    row = Archivable.objects.create(name="record")
    row.delete()

    row.restore()

    assert Archivable.objects.filter(pk=row.pk).count() == 1
    assert row.is_deleted is False


def test_hard_delete_removes_row(archivable_table):
    row = Archivable.objects.create(name="record")
    row.hard_delete()

    assert Archivable.all_objects.filter(pk=row.pk).count() == 0

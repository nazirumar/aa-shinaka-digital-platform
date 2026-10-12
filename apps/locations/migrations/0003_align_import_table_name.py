"""Align the legacy ``NigeriaLocationImport`` table with its declared name.

``core.0001`` created the table using Django's default name
(``core_nigerialocationimport``), while ``locations.0001`` re-declared the model
with ``db_table = "core_nigeria_location_import"``. Because that re-declaration
was state-only, the physical table kept the default name and every write failed
with "relation ... does not exist". This migration renames the physical table to
match the model so the importer's audit rows can be written again.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("locations", "0002_lga_slug_lga_uniq_lga_slug_per_state"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'ALTER TABLE IF EXISTS "core_nigerialocationimport" '
                'RENAME TO "core_nigeria_location_import";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

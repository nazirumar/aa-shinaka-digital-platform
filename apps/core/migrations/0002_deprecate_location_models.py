"""Deprecate core location models in favor of apps.locations.

Keep the db_table names pointing to the same tables (core_state/core_lga/
core_nigeria_location_import). The locations app now owns those tables via
SeparateDatabaseAndState. This migration no-ops on DB and removes model
definitions from core's state to avoid Django model db_table/name conflicts.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("locations", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="LGA"),
                migrations.DeleteModel(name="NigeriaLocationImport"),
                migrations.DeleteModel(name="State"),
            ],
        ),
    ]

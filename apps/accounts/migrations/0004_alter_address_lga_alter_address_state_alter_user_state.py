"""Retarget location FKs from core to locations app.

Phase 4 moves State/LGA into ``apps.locations``; the physical tables remain the
same (``core_state`` / ``core_lga``), so only the migration model references
change. These are state-only operations — no database alterations.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_map_roles_and_create_groups"),
        ("locations", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="state",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="users",
                to="locations.state",
            ),
        ),
        migrations.AlterField(
            model_name="address",
            name="state",
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name="addresses",
                to="locations.state",
            ),
        ),
        migrations.AlterField(
            model_name="address",
            name="lga",
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name="addresses",
                to="locations.lga",
            ),
        ),
    ]

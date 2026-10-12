"""Retarget SiteSetting.state from core.State to locations.State.

State-only; the underlying ``core_state`` table is unchanged.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0001_initial"),
        ("locations", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sitesetting",
            name="state",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="+",
                to="locations.state",
            ),
        ),
    ]

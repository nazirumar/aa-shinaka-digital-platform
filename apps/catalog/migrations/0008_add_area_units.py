# Generated for the AA Shinaka platform.

from django.db import migrations


def add_area_units(apps, schema_editor):
    """Add area units of measure used by farming services (hectare, acre)."""
    UnitOfMeasure = apps.get_model("catalog", "UnitOfMeasure")
    units = [
        ("Hectare", "hectare", "ha", 100),
        ("Acre", "acre", "ac", 110),
    ]
    for name, code, symbol, sort_order in units:
        UnitOfMeasure.objects.get_or_create(
            code=code, defaults={"name": name, "symbol": symbol, "sort_order": sort_order}
        )


def remove_area_units(apps, schema_editor):
    UnitOfMeasure = apps.get_model("catalog", "UnitOfMeasure")
    UnitOfMeasure.objects.filter(code__in=["hectare", "acre"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0007_stockmovement_variant_warehouse_stockbalance_and_more"),
    ]

    operations = [
        migrations.RunPython(add_area_units, remove_area_units),
    ]

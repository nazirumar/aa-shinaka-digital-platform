"""Move the legacy core location tables into the ``locations`` app.

``core.0001`` created ``core_state`` / ``core_lga`` /
``core_nigeria_location_import``. This migration re-declares those models under
``locations`` **without touching the database** (``SeparateDatabaseAndState``
with no database operations) and keeps their legacy ``db_table`` names, so no
row moves and every existing foreign key (users, addresses, site settings)
stays valid. It then adds the new ``Country`` reference table, links every
existing state to Nigeria, and adds the optional ``City``/town table.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


def assign_nigeria(apps, schema_editor):
    """Point every existing state at the Nigeria country row (idempotent)."""
    Country = apps.get_model("locations", "Country")
    State = apps.get_model("locations", "State")
    nigeria, _created = Country.objects.get_or_create(
        code="NG", defaults={"name": "Nigeria"}
    )
    State.objects.filter(country__isnull=True).update(country=nigeria)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        # 1. New Country table (real table).
        migrations.CreateModel(
            name="Country",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=64, unique=True)),
                (
                    "code",
                    models.CharField(
                        help_text="ISO 3166-1 alpha-2 code, e.g. 'NG' for Nigeria.",
                        max_length=3,
                        unique=True,
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=True)),
            ],
            options={
                "verbose_name": "Country",
                "verbose_name_plural": "Countries",
                "ordering": ["name"],
            },
        ),
        # 2. Take over the legacy tables — state only, no DB change. Fields
        #    mirror core.0001. State starts without ``country`` (added next).
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="State",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "created_at",
                            models.DateTimeField(
                                auto_now_add=True, db_index=True
                            ),
                        ),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("name", models.CharField(max_length=64, unique=True)),
                        (
                            "code",
                            models.CharField(
                                help_text="Short stable code, e.g. 'FC' for FCT, 'LA' for Lagos.",
                                max_length=8,
                                unique=True,
                            ),
                        ),
                        (
                            "slug",
                            models.SlugField(blank=True, max_length=80, unique=True),
                        ),
                        (
                            "zone",
                            models.CharField(
                                choices=[
                                    ("NC", "North Central"),
                                    ("NE", "North East"),
                                    ("NW", "North West"),
                                    ("SE", "South East"),
                                    ("SS", "South South"),
                                    ("SW", "South West"),
                                ],
                                db_index=True,
                                max_length=2,
                            ),
                        ),
                        ("is_active", models.BooleanField(db_index=True, default=True)),
                    ],
                    options={
                        "verbose_name": "State",
                        "verbose_name_plural": "States",
                        "ordering": ["name"],
                        "db_table": "core_state",
                    },
                ),
                migrations.CreateModel(
                    name="LGA",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "created_at",
                            models.DateTimeField(
                                auto_now_add=True, db_index=True
                            ),
                        ),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("name", models.CharField(max_length=96)),
                        (
                            "code",
                            models.CharField(
                                blank=True,
                                help_text="Optional source-specific code carried over from the imported dataset.",
                                max_length=16,
                            ),
                        ),
                        ("is_active", models.BooleanField(db_index=True, default=True)),
                        (
                            "state",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="lgas",
                                to="locations.state",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "LGA",
                        "verbose_name_plural": "LGAs",
                        "ordering": ["state__name", "name"],
                        "db_table": "core_lga",
                        "constraints": [
                            models.UniqueConstraint(
                                fields=("state", "name"),
                                name="uniq_lga_name_per_state",
                            )
                        ],
                        "indexes": [
                            models.Index(
                                fields=["state", "name"],
                                name="core_lga_state_name_idx",
                            )
                        ],
                    },
                ),
                migrations.CreateModel(
                    name="NigeriaLocationImport",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("source", models.CharField(max_length=512)),
                        ("source_checksum", models.CharField(blank=True, max_length=64)),
                        ("states_imported", models.PositiveIntegerField(default=0)),
                        ("lgas_imported", models.PositiveIntegerField(default=0)),
                        ("succeeded", models.BooleanField(default=False)),
                        ("message", models.TextField(blank=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                    ],
                    options={
                        "ordering": ["-created_at"],
                        "db_table": "core_nigeria_location_import",
                    },
                ),
            ],
        ),
        # 3. Add country column to core_state.
        migrations.AddField(
            model_name="state",
            name="country",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="states",
                to="locations.country",
            ),
        ),
        # 4. Backfill NG.
        migrations.RunPython(assign_nigeria, migrations.RunPython.noop),
        # 5. Make NOT NULL.
        migrations.AlterField(
            model_name="state",
            name="country",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="states",
                to="locations.country",
            ),
        ),
        # 6. New City table.
        migrations.CreateModel(
            name="City",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=96)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                (
                    "lga",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cities",
                        to="locations.lga",
                    ),
                ),
                (
                    "state",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cities",
                        to="locations.state",
                    ),
                ),
            ],
            options={
                "verbose_name": "City / Town",
                "verbose_name_plural": "Cities / Towns",
                "ordering": ["state__name", "name"],
                "indexes": [
                    models.Index(
                        fields=["state", "name"], name="loc_city_state_name_idx"
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("state", "name"), name="uniq_city_name_per_state"
                    )
                ],
            },
        ),
    ]

"""Nigeria location reference data: Country → State → LGA → City/Town.

``State``, ``LGA``, ``GeopoliticalZone`` and ``NigeriaLocationImport`` moved
here from ``apps.core`` in Phase 4 so geographic data lives in its own
application. Their physical table names (``core_state``, ``core_lga``,
``core_nigeria_location_import``) are intentionally preserved so every existing
foreign-key reference (users, addresses, site settings) keeps working without
moving a single row.

Reference data is loaded via ``manage.py import_nigeria_locations`` — never
hand-entered — so counts stay verifiable (36 states + FCT, 774 LGAs).
Locations are never deleted while referenced: they are deactivated
(``is_active=False``) so historical references remain intact.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import models
from django.urls import reverse
from django.utils.text import slugify

# Avoid circular import: TimeStampedModel lives in apps.core.models
# Import directly from core.models to avoid circular refs
from apps.core.models import TimeStampedModel  # pragma: no cover


class GeopoliticalZone(models.TextChoices):
    """Nigeria's six geopolitical zones."""

    NORTH_CENTRAL = "NC", "North Central"
    NORTH_EAST = "NE", "North East"
    NORTH_WEST = "NW", "North West"
    SOUTH_EAST = "SE", "South East"
    SOUTH_SOUTH = "SS", "South South"
    SOUTH_WEST = "SW", "South West"


class Country(TimeStampedModel):
    """A country. Nigeria (``NG``) is seeded by the importer and migrations."""

    name = models.CharField(max_length=64, unique=True)
    code = models.CharField(
        max_length=3,
        unique=True,
        help_text="ISO 3166-1 alpha-2 code, e.g. 'NG' for Nigeria.",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]
        verbose_name = "Country"
        verbose_name_plural = "Countries"

    def __str__(self) -> str:
        return self.name


class State(TimeStampedModel):  # Inherits from apps.core.models.TimeStampedModel
    """A Nigerian state or the Federal Capital Territory."""

    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        related_name="states",
    )
    name = models.CharField(max_length=64, unique=True)
    code = models.CharField(
        max_length=8,
        unique=True,
        help_text="Short stable code, e.g. 'FC' for FCT, 'LA' for Lagos.",
    )
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    zone = models.CharField(max_length=2, choices=GeopoliticalZone.choices, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]
        verbose_name = "State"
        verbose_name_plural = "States"
        # Legacy table name preserved so existing FK references stay valid.
        db_table = "core_state"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:state_detail", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class LGA(TimeStampedModel):
    """A Local Government Area or Area Council belonging to a state."""

    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="lgas")
    name = models.CharField(max_length=96)
    slug = models.SlugField(max_length=100, blank=True)
    code = models.CharField(
        max_length=16,
        blank=True,
        help_text="Optional source-specific code carried over from the imported dataset.",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["state__name", "name"]
        verbose_name = "LGA"
        verbose_name_plural = "LGAs"
        db_table = "core_lga"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(fields=["state", "name"], name="uniq_lga_name_per_state"),
            models.UniqueConstraint(fields=["state", "slug"], name="uniq_lga_slug_per_state"),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["state", "name"], name="core_lga_state_name_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.state.code})"

    def get_absolute_url(self) -> str:
        return reverse(
            "catalog:lga_detail",
            kwargs={"state": self.state.slug, "lga": self.slug},
        )

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or f"lga-{self.pk or 'x'}"
            slug = base
            counter = 2
            while (
                LGA.objects.filter(state_id=self.state_id, slug=slug).exclude(pk=self.pk).exists()
            ):
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


class City(TimeStampedModel):
    """An optional city/town inside a state, optionally tied to an LGA."""

    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="cities")
    lga = models.ForeignKey(
        LGA, null=True, blank=True, on_delete=models.PROTECT, related_name="cities"
    )
    name = models.CharField(max_length=96)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["state__name", "name"]
        verbose_name = "City / Town"
        verbose_name_plural = "Cities / Towns"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(fields=["state", "name"], name="uniq_city_name_per_state"),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["state", "name"], name="loc_city_state_name_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.state.code})"


class NigeriaLocationImport(models.Model):
    """Audit record for each run of the Nigeria location importer."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=512)
    source_checksum = models.CharField(max_length=64, blank=True)
    states_imported = models.PositiveIntegerField(default=0)
    lgas_imported = models.PositiveIntegerField(default=0)
    succeeded = models.BooleanField(default=False)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        db_table = "core_nigeria_location_import"

    def __str__(self) -> str:
        status = "ok" if self.succeeded else "failed"
        return f"{self.created_at:%Y-%m-%d %H:%M} {status} ({self.states_imported} states)"

"""Tests for core base models and Nigeria location reference data."""

import pytest
from django.db import IntegrityError, transaction

from apps.core.models import LGA, GeopoliticalZone, State, TimeStampedModel

pytestmark = pytest.mark.django_db


def test_state_slug_is_generated_automatically():
    from apps.locations.models import Country

    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria"})
    state = State.objects.create(
        name="Akwa Ibom", code="AK", zone=GeopoliticalZone.SOUTH_SOUTH, country=ng
    )
    assert state.slug == "akwa-ibom"


def test_timestamps_are_set():
    from apps.locations.models import Country

    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria"})
    state = State.objects.create(
        name="Enugu", code="EN", zone=GeopoliticalZone.SOUTH_EAST, country=ng
    )
    assert isinstance(state, TimeStampedModel)
    assert state.created_at is not None
    assert state.updated_at is not None


def test_lga_names_unique_per_state():
    from apps.locations.models import Country

    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria"})
    lagos = State.objects.create(
        name="Lagos", code="LA", zone=GeopoliticalZone.SOUTH_WEST, country=ng
    )
    kano = State.objects.create(
        name="Kano", code="KN", zone=GeopoliticalZone.NORTH_WEST, country=ng
    )

    LGA.objects.create(state=lagos, name="Ikeja")
    LGA.objects.create(state=kano, name="Ikeja")

    assert LGA.objects.filter(name="Ikeja").count() == 2

    with pytest.raises(IntegrityError), transaction.atomic():
        LGA.objects.create(state=lagos, name="Ikeja")


def test_state_code_is_unique():
    from apps.locations.models import Country

    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria"})
    State.objects.create(name="Kano", code="KN", zone=GeopoliticalZone.NORTH_WEST, country=ng)
    with pytest.raises(IntegrityError), transaction.atomic():
        State.objects.create(
            name="Kano State", code="KN", zone=GeopoliticalZone.NORTH_WEST, country=ng
        )

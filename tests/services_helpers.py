"""Reusable builders for the Phase 7 service tests.

Arranging fixtures may write directly to the ORM, but anything that is itself the
behaviour under test goes through ``apps.services.services`` so the tests cover
the real write path (validation, transitions, capacity accounting, auditing).
Money and quantities are always ``Decimal``/decimal strings.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.services import services
from apps.services.models import (
    ConsultancyService,
    Consultant,
    ConsultantAvailability,
    FarmingService,
    MarketingService,
    ProduceType,
    ServiceType,
    StorageFacility,
    StorageUnit,
)


def future_window(*, days=3, hour=10, duration_minutes=60):
    """A deterministic, timezone-aware [start, end) window in the future."""
    start = timezone.localtime(timezone.now()) + timedelta(days=days)
    start = start.replace(hour=hour, minute=0, second=0, microsecond=0)
    return start, start + timedelta(minutes=duration_minutes)


def make_consultancy_service(**kwargs) -> ConsultancyService:
    data = {
        "name": "Soil testing",
        "duration_minutes": 60,
        "supports_online": True,
        "supports_onsite": True,
    }
    data.update(kwargs)
    return ConsultancyService.objects.create(**data)


def make_consultant(user, *, start, end, weekday=None) -> Consultant:
    """Create a consultant with one availability slot covering [start, end]."""
    consultant = Consultant.objects.create(user=user)
    ConsultantAvailability.objects.create(
        consultant=consultant,
        weekday=weekday,
        specific_date=None if weekday is not None else start.date(),
        start_time=(start - timedelta(hours=1)).time(),
        end_time=(end + timedelta(hours=1)).time(),
    )
    return consultant


def make_farming_service(**kwargs) -> FarmingService:
    data = {"name": "Land preparation"}
    data.update(kwargs)
    return FarmingService.objects.create(**data)


def make_marketing_service(**kwargs) -> MarketingService:
    data = {"name": "Crop marketing"}
    data.update(kwargs)
    return MarketingService.objects.create(**data)


def make_produce_type(name="Maize") -> ProduceType:
    return ProduceType.objects.create(name=name)


def make_facility(*, name="Zaria warehouse", capacity="100.00", accepted=(), **kwargs):
    facility = StorageFacility.objects.create(name=name, capacity=Decimal(capacity), **kwargs)
    if accepted:
        facility.accepted_produce_types.set(accepted)
    return facility


def make_storage_unit(facility, *, name="Bay 1", capacity="40.00", **kwargs) -> StorageUnit:
    return StorageUnit.objects.create(
        facility=facility, name=name, capacity=Decimal(capacity), **kwargs
    )


def make_request(customer, *, service_type=ServiceType.CONSULTANCY, **kwargs):
    data = {"title": "Test request"}
    data.update(kwargs)
    return services.create_service_request(customer=customer, service_type=service_type, **data)


def make_storage_request(customer, *, produce_type=None, quantity="10.00", **kwargs):
    return services.submit_storage_request(
        customer=customer, produce_type=produce_type, quantity=quantity, **kwargs
    )


def make_quotation(customer, *, actor, service_request=None, items=None, **kwargs):
    items = items or [{"description": "Consultancy", "quantity": "1", "unit_price": "50000"}]
    return services.create_quotation(
        actor=actor,
        customer=customer,
        items=items,
        service_request=service_request,
        **kwargs,
    )


def issue_quotation(quotation, *, actor):
    services.submit_quotation_for_approval(quotation, actor=actor)
    services.approve_quotation(quotation, actor=actor)
    services.issue_quotation(quotation, actor=actor)
    return quotation

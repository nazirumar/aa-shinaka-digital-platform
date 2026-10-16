"""Reusable builders for the Phase 8 export tests.

Arranging fixtures may write directly to the ORM where a step is not itself
under test, but anything that *is* the behaviour under test goes through the
service layer (``apps.export.services`` / ``apps.orders.payments``) so the real
validation, transitions, compliance gates and permission checks are exercised.
Money and quantities are always ``Decimal``/decimal strings.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.export import services
from apps.export.models import (
    INCOTERMS_VERSION,
    ExportAvailability,
    ExportDestination,
    ExportOrder,
    ExportQuotation,
    Incoterm,
)
from apps.locations.models import Country


def make_export_country(code: str = "GH", name: str = "Ghana") -> Country:
    country, _ = Country.objects.get_or_create(code=code, defaults={"name": name})
    return country


def make_destination(*, actor, country=None, activate: bool = True, **fields) -> ExportDestination:
    """Create, approve and (by default) activate an export destination."""
    country = country or make_export_country()
    destination = services.upsert_destination(country=country, actor=actor, **fields)
    services.approve_destination(destination, actor=actor)
    if activate:
        services.set_destination_active(destination, actor=actor, active=True)
    destination.refresh_from_db()
    return destination


def make_export_product(product, *, actor, destinations=(), **fields):
    """Mark a catalogue product export-eligible and configure its profile."""
    defaults = {
        "is_export_eligible": True,
        "export_availability": ExportAvailability.AVAILABLE,
    }
    defaults.update(fields)
    return services.upsert_product_profile(
        product=product,
        actor=actor,
        allowed_destinations=list(destinations),
        **defaults,
    )


def make_enquiry(
    customer, *, destination, product, actor, quantity=Decimal("5000"), unit=None, **fields
):
    defaults = {"delivery_destination": "Tema, Ghana"}
    defaults.update(fields)
    return services.create_enquiry(
        customer=customer,
        destination=destination,
        items=[{"product": product, "quantity": quantity, "unit": unit}],
        actor=actor,
        **defaults,
    )


def make_quotation(
    enquiry,
    *,
    actor,
    product,
    quantity=Decimal("5000"),
    unit=None,
    unit_price=Decimal("500.00"),
    deposit_percentage=Decimal("30"),
    **fields,
) -> ExportQuotation:
    defaults = {
        "currency": "USD",
        "incoterm": Incoterm.FOB,
        "incoterm_version": INCOTERMS_VERSION,
        "named_place": "Apapa, Lagos",
        "payment_terms": "30% deposit on acceptance",
        "delivery_terms": "FOB Apapa",
        "valid_until": timezone.localdate() + timedelta(days=30),
    }
    defaults.update(fields)
    items = [
        {
            "charge_type": "product",
            "product": product,
            "description": product.name,
            "quantity": quantity,
            "unit": unit or product.unit,
            "unit_price": unit_price,
        }
    ]
    return services.create_quotation(
        enquiry=enquiry,
        actor=actor,
        items=items,
        deposit_percentage=deposit_percentage,
        **defaults,
    )


def make_issued_quotation(enquiry, *, actor, approver, **kwargs) -> ExportQuotation:
    quotation = make_quotation(enquiry, actor=actor, **kwargs)
    services.approve_quotation(quotation, actor=approver)
    quotation.refresh_from_db()
    return quotation


def make_export_order(enquiry, *, actor, approver, customer, **kwargs) -> ExportOrder:
    quotation = make_issued_quotation(enquiry, actor=actor, approver=approver, **kwargs)
    order = services.accept_quotation(quotation, actor=customer)
    order.refresh_from_db()
    return order


def upload_file(
    name: str = "document.txt", content: bytes = b"export document"
) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="text/plain")

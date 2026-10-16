"""Write layer for the export domain (Tasks 1–9).

Every state change is transaction-safe, validates its own preconditions and is
authorised server-side via capabilities. Views and the portal call these
functions; they never mutate export models directly.

Key invariants
--------------
* Only an **accepted** export quotation can produce an export order.
* Accepted quotations are frozen — revisions are recorded instead of edits.
* An order can only become *ready for shipment* once its compliance checklist is
  **approved** by an authorised approver.
* Only a **verified** payment (Phase 6) settles an export order; the browser
  callback never does.
* Shipment milestones are real, staff-entered events — never fabricated GPS.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability
from apps.core.audit import record_audit
from apps.core.upload_security import bind_scanned_file, screen_upload
from apps.notifications import events as notification_events

from . import notifications, selectors
from .models import (
    EXPORT_ENQUIRY_TRANSITIONS,
    EXPORT_ORDER_TRANSITIONS,
    SHIPMENT_TRANSITIONS,
    ApprovalStatus,
    ComplianceChecklistStatus,
    ComplianceItemStatus,
    ComplianceStatus,
    DocumentReviewDecision,
    DocumentVerificationStatus,
    ExportAvailability,
    ExportComplianceChecklist,
    ExportComplianceChecklistItem,
    ExportDestination,
    ExportDestinationRequirement,
    ExportDocument,
    ExportDocumentRequirement,
    ExportDocumentReview,
    ExportDocumentType,
    ExportEnquiry,
    ExportEnquiryItem,
    ExportEnquiryStatus,
    ExportEnquiryStatusHistory,
    ExportOrder,
    ExportOrderItem,
    ExportOrderStatus,
    ExportOrderStatusHistory,
    ExportProductProfile,
    ExportQuotation,
    ExportQuotationItem,
    ExportQuotationRevision,
    ExportQuotationStatus,
    ExportShipment,
    ExportShipmentItem,
    ExportTradeRestriction,
    LogisticsProvider,
    ShipmentMilestone,
    ShipmentStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require(value, message: str) -> None:
    if not value:
        raise ValidationError(message)


def _require_manage(actor) -> None:
    if not has_capability(actor, Capability.EXPORT_MANAGE, Capability.EXPORT_APPROVE, any_of=True):
        raise PermissionDenied("You do not have permission to manage export operations.")


def _require_approve(actor) -> None:
    if not has_capability(actor, Capability.EXPORT_APPROVE):
        raise PermissionDenied("You do not have permission to approve export operations.")


def _path(current: str, target: str, transitions: dict) -> list[str] | None:
    """Shortest legal path from ``current`` to ``target`` (inclusive of target)."""
    if current == target:
        return []
    seen = {current}
    queue: deque = deque([(current, [])])
    while queue:
        node, path = queue.popleft()
        for nxt in transitions.get(node, frozenset()):
            if nxt == target:
                return [*path, nxt]
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, [*path, nxt]))
    return None


def _audit_actor(actor):
    return actor if getattr(actor, "is_authenticated", False) else None


# ---------------------------------------------------------------------------
# Task 1 — destinations
# ---------------------------------------------------------------------------


@transaction.atomic
def upsert_destination(*, country, actor, **fields) -> ExportDestination:
    """Create or update the destination configuration for ``country``.

    A new destination is always pending and inactive until approved.
    """
    _require_manage(actor)
    destination, created = ExportDestination.objects.get_or_create(
        country=country,
        defaults={"country_code": getattr(country, "code", ""), **fields},
    )
    if not created:
        for key, value in fields.items():
            setattr(destination, key, value)
        if not destination.country_code:
            destination.country_code = country.code
        destination.save()
    record_audit(
        actor=actor,
        action="export.destination.upsert",
        target=destination,
        after={"country": destination.country_code, "active": destination.is_active},
    )
    return destination


@transaction.atomic
def approve_destination(destination: ExportDestination, *, actor) -> ExportDestination:
    """Record staff approval for a destination (does not by itself activate it)."""
    _require_approve(actor)
    destination.approval_status = ApprovalStatus.APPROVED
    destination.approved_by = _audit_actor(actor)
    destination.approved_at = timezone.now()
    destination.save(update_fields=["approval_status", "approved_by", "approved_at", "updated_at"])
    record_audit(actor=actor, action="export.destination.approve", target=destination)
    return destination


@transaction.atomic
def set_destination_active(destination: ExportDestination, *, actor, active: bool):
    """Activate/deactivate a destination; activation requires prior approval."""
    _require_approve(actor)
    if active:
        _require(
            destination.approval_status == ApprovalStatus.APPROVED,
            "A destination must be approved before it can be activated.",
        )
        if not destination.approved_at:
            destination.approved_at = timezone.now()
            destination.approved_by = _audit_actor(actor)
    destination.is_active = active
    destination.save(update_fields=["is_active", "approved_by", "approved_at", "updated_at"])
    record_audit(
        actor=actor,
        action="export.destination.set_active",
        target=destination,
        after={"active": active},
    )
    return destination


@transaction.atomic
def add_destination_requirement(
    destination: ExportDestination,
    *,
    actor,
    title: str,
    last_verified_at=None,
    **fields,
) -> ExportDestinationRequirement:
    _require_manage(actor)
    return ExportDestinationRequirement.objects.create(
        destination=destination,
        title=title,
        last_verified_at=last_verified_at,
        verified_by=_audit_actor(actor),
        **fields,
    )


@transaction.atomic
def add_trade_restriction(
    destination: ExportDestination, *, actor, description: str, **fields
) -> ExportTradeRestriction:
    _require_manage(actor)
    return ExportTradeRestriction.objects.create(
        destination=destination, description=description, **fields
    )


# ---------------------------------------------------------------------------
# Task 2 — product configuration
# ---------------------------------------------------------------------------


@transaction.atomic
def upsert_product_profile(*, product, actor, allowed_destinations=None, **fields):
    _require_manage(actor)
    profile, _created = ExportProductProfile.objects.get_or_create(product=product)
    for key, value in fields.items():
        setattr(profile, key, value)
    profile.save()
    if allowed_destinations is not None:
        profile.allowed_destinations.set(allowed_destinations)
    record_audit(actor=actor, action="export.product_profile.upsert", target=profile)
    return profile


# ---------------------------------------------------------------------------
# Task 3 — enquiries
# ---------------------------------------------------------------------------


def _validate_destination(destination: ExportDestination) -> None:
    _require(destination.is_active, "Export to this destination is not currently available.")
    _require(
        destination.approval_status == ApprovalStatus.APPROVED,
        "This destination has not been approved for export.",
    )


def _validate_item(product, destination: ExportDestination, quantity, *, unit=None) -> None:
    profile = getattr(product, "export_profile", None)
    _require(profile is not None, f"{product} is not configured for export.")
    _require(profile.is_export_eligible, f"{product} is not marked export-eligible.")
    _require(
        profile.export_availability != ExportAvailability.UNAVAILABLE,
        f"{product} is not currently available for export.",
    )
    _require(
        profile.allows_destination(destination),
        f"{product} may not be exported to {destination.country.name}.",
    )
    _require(
        Decimal(str(quantity)) > 0,
        "Export quantities must be positive.",
    )
    if profile.min_export_quantity and Decimal(str(quantity)) < profile.min_export_quantity:
        unit = profile.min_export_unit or ""
        message = f"{product} has a minimum export quantity of {profile.min_export_quantity} {unit}"
        raise ValidationError(message.strip())


@transaction.atomic
def create_enquiry(*, customer, destination: ExportDestination, items: list[dict], actor, **fields):
    """Validate and create an export enquiry with its items."""
    if customer != actor and not has_capability(
        actor, Capability.EXPORT_MANAGE, Capability.EXPORT_APPROVE, any_of=True
    ):
        raise PermissionDenied("You cannot create an enquiry for another customer.")
    _validate_destination(destination)
    _require(items, "At least one export item is required.")

    enquiry = ExportEnquiry.objects.create(customer=customer, destination=destination, **fields)
    for entry in items:
        product = entry["product"]
        quantity = Decimal(str(entry["quantity"]))
        unit = entry.get("unit") or getattr(product, "unit", None)
        _require(unit is not None, "A unit of measure is required for each item.")
        _validate_item(product, destination, quantity, unit=unit)
        ExportEnquiryItem.objects.create(
            enquiry=enquiry,
            product=product,
            listing=entry.get("listing"),
            quantity=quantity,
            unit=unit,
            packaging_requirements=entry.get("packaging_requirements", ""),
            notes=entry.get("notes", ""),
        )
    ExportEnquiryStatusHistory.objects.create(
        enquiry=enquiry, from_status="", to_status=enquiry.status, note="Enquiry submitted."
    )
    notifications.enquiry_received(enquiry)
    return enquiry


def _advance_enquiry(enquiry: ExportEnquiry, to_status: str, *, actor, note: str = ""):
    """Move the enquiry along a legal path, recording history (no capability gate).

    Used by staff-facing transitions (which gate on ``EXPORT_MANAGE``) *and* by
    system-driven steps inside customer actions such as accepting a quotation, so
    the enquiry is marked ``quoted``/``converted`` without requiring the customer
    to hold a staff capability.
    """
    path = _path(enquiry.status, to_status, EXPORT_ENQUIRY_TRANSITIONS)
    if path is None:
        raise ValidationError(f"Cannot move enquiry from {enquiry.status} to {to_status}.")
    for step in path:
        ExportEnquiryStatusHistory.objects.create(
            enquiry=enquiry,
            from_status=enquiry.status,
            to_status=step,
            actor=_audit_actor(actor),
            note=note,
        )
        enquiry.status = step
    if enquiry.status in {
        ExportEnquiryStatus.CONVERTED,
        ExportEnquiryStatus.REJECTED,
        ExportEnquiryStatus.CANCELLED,
    }:
        enquiry.closed_at = timezone.now()
    enquiry.save()
    return enquiry


@transaction.atomic
def transition_enquiry(enquiry: ExportEnquiry, to_status: str, *, actor, note: str = ""):
    """Advance the enquiry along a legal path; records status history per step."""
    _require_manage(actor)
    return _advance_enquiry(enquiry, to_status, actor=actor, note=note)


def review_enquiry(enquiry: ExportEnquiry, *, actor, note: str = "") -> ExportEnquiry:
    return transition_enquiry(
        enquiry, ExportEnquiryStatus.UNDER_REVIEW, actor=actor, note=note or "Under review."
    )


def request_enquiry_requirements(enquiry: ExportEnquiry, *, actor, note: str = "") -> ExportEnquiry:
    return transition_enquiry(
        enquiry, ExportEnquiryStatus.REQUIREMENTS_REQUESTED, actor=actor, note=note
    )


def reject_enquiry(enquiry: ExportEnquiry, *, actor, note: str = "") -> ExportEnquiry:
    return transition_enquiry(enquiry, ExportEnquiryStatus.REJECTED, actor=actor, note=note)


def cancel_enquiry(enquiry: ExportEnquiry, *, actor, note: str = "") -> ExportEnquiry:
    return transition_enquiry(enquiry, ExportEnquiryStatus.CANCELLED, actor=actor, note=note)


@transaction.atomic
def assign_enquiry(enquiry: ExportEnquiry, *, actor, assignee) -> ExportEnquiry:
    _require_manage(actor)
    enquiry.assigned_to = assignee
    enquiry.save(update_fields=["assigned_to", "updated_at"])
    return enquiry


@transaction.atomic
def _mark_enquiry_quoted(enquiry: ExportEnquiry | None, *, actor) -> None:
    if enquiry is None:
        return
    if enquiry.status in {
        ExportEnquiryStatus.CONVERTED,
        ExportEnquiryStatus.REJECTED,
        ExportEnquiryStatus.CANCELLED,
        ExportEnquiryStatus.QUOTED,
    }:
        return
    _advance_enquiry(enquiry, ExportEnquiryStatus.QUOTED, actor=actor, note="Quotation issued.")


# ---------------------------------------------------------------------------
# Task 4 — quotations
# ---------------------------------------------------------------------------


def _compute_totals(items: list[dict]) -> tuple[Decimal, Decimal]:
    subtotal = Decimal("0.00")
    total = Decimal("0.00")
    for item in items:
        amount = Decimal(str(item.get("quantity") or 0)) * Decimal(str(item.get("unit_price") or 0))
        amount = amount.quantize(Decimal("0.01"))
        total += amount
        if item.get("charge_type", "product") == "product":
            subtotal += amount
    return subtotal, total


@transaction.atomic
def create_quotation(
    *,
    enquiry: ExportEnquiry,
    actor,
    currency: str,
    incoterm: str,
    incoterm_version: str,
    named_place: str,
    payment_terms: str,
    delivery_terms: str,
    valid_until,
    items: list[dict],
    deposit_percentage=0,
    exchange_rate_reference: str = "",
    notes: str = "",
) -> ExportQuotation:
    _require_manage(actor)
    _require(enquiry is not None, "A quotation must belong to an export enquiry.")
    _require(items, "A quotation must contain at least one line.")

    subtotal, total = _compute_totals(items)
    quotation = ExportQuotation.objects.create(
        enquiry=enquiry,
        customer=enquiry.customer,
        destination=enquiry.destination,
        currency=(currency or "USD").upper(),
        incoterm=incoterm,
        incoterm_version=incoterm_version or "2020",
        named_place=named_place,
        payment_terms=payment_terms,
        delivery_terms=delivery_terms,
        valid_until=valid_until,
        deposit_percentage=deposit_percentage or 0,
        exchange_rate_reference=exchange_rate_reference,
        subtotal=subtotal,
        total=total,
        prepared_by=actor,
        notes=notes,
    )
    _create_quotation_items(quotation, items)
    if enquiry.status == ExportEnquiryStatus.SUBMITTED:
        review_enquiry(enquiry, actor=actor, note="Preparing quotation.")
    record_audit(actor=actor, action="export.quotation.create", target=quotation)
    return quotation


def _create_quotation_items(quotation: ExportQuotation, items: list[dict]) -> None:
    for index, item in enumerate(items):
        ExportQuotationItem.objects.create(
            quotation=quotation,
            charge_type=item.get("charge_type", "product"),
            product=item.get("product"),
            listing=item.get("listing"),
            description=item["description"],
            quantity=item.get("quantity") or 0,
            unit=item.get("unit"),
            unit_price=item.get("unit_price") or 0,
            sort_order=item.get("sort_order", index),
        )


@transaction.atomic
def submit_quotation_for_approval(quotation: ExportQuotation, *, actor) -> ExportQuotation:
    _require_manage(actor)
    _require(
        quotation.status in {ExportQuotationStatus.DRAFT, ExportQuotationStatus.PENDING_APPROVAL},
        "Only a draft quotation can be submitted for approval.",
    )
    quotation.status = ExportQuotationStatus.PENDING_APPROVAL
    quotation.save(update_fields=["status", "updated_at"])
    return quotation


def _validate_issuable(quotation: ExportQuotation) -> None:
    _require(quotation.items.exists(), "A quotation needs at least one line before issue.")
    _require(bool(quotation.incoterm), "An Incoterm is required before a quotation is issued.")
    _require(
        bool(quotation.incoterm_version),
        "An Incoterms version is required (e.g. 2020).",
    )
    _require(
        bool(quotation.named_place),
        "A named place is required for the chosen Incoterm before issue.",
    )
    _require(quotation.valid_until is not None, "A validity date is required before issue.")


@transaction.atomic
def approve_quotation(quotation: ExportQuotation, *, actor) -> ExportQuotation:
    """Approve and issue a quotation (separation of duties: requires approver)."""
    _require_approve(actor)
    _require(
        quotation.status in {ExportQuotationStatus.DRAFT, ExportQuotationStatus.PENDING_APPROVAL},
        "Only a draft or pending quotation can be approved.",
    )
    _validate_issuable(quotation)
    now = timezone.now()
    quotation.status = ExportQuotationStatus.ISSUED
    quotation.approved_by = actor
    quotation.approved_at = now
    quotation.issued_at = now
    quotation.save(
        update_fields=["status", "approved_by", "approved_at", "issued_at", "updated_at"]
    )
    _mark_enquiry_quoted(quotation.enquiry, actor=actor)
    notifications.quotation_issued(quotation)
    notification_events.export_quotation_issued(quotation)
    record_audit(actor=actor, action="export.quotation.approve", target=quotation)
    return quotation


@transaction.atomic
def reject_quotation(quotation: ExportQuotation, *, actor, reason: str = "") -> ExportQuotation:
    _require_approve(actor)
    _require(
        quotation.status not in {ExportQuotationStatus.ACCEPTED, ExportQuotationStatus.SUPERSEDED},
        "A decided quotation cannot be rejected.",
    )
    quotation.status = ExportQuotationStatus.REJECTED
    quotation.decided_at = timezone.now()
    if reason:
        quotation.notes = f"{quotation.notes}\n{reason}".strip()
    quotation.save(update_fields=["status", "decided_at", "notes", "updated_at"])
    return quotation


@transaction.atomic
def expire_quotation(quotation: ExportQuotation) -> ExportQuotation:
    """Expire a quotation whose validity date has passed (idempotent)."""
    if quotation.status not in {
        ExportQuotationStatus.DRAFT,
        ExportQuotationStatus.PENDING_APPROVAL,
        ExportQuotationStatus.ISSUED,
    }:
        return quotation
    if quotation.valid_until and quotation.valid_until < timezone.localdate():
        quotation.status = ExportQuotationStatus.EXPIRED
        quotation.decided_at = timezone.now()
        quotation.save(update_fields=["status", "decided_at", "updated_at"])
    return quotation


def expire_due_quotations() -> int:
    """Expire every due quotation; returns the number expired."""
    qs = ExportQuotation.objects.filter(
        status__in=[
            ExportQuotationStatus.DRAFT,
            ExportQuotationStatus.PENDING_APPROVAL,
            ExportQuotationStatus.ISSUED,
        ],
        valid_until__lt=timezone.localdate(),
    )
    count = 0
    for quotation in qs:
        expire_quotation(quotation)
        count += 1
    return count


def _quotation_snapshot(quotation: ExportQuotation) -> dict:
    return {
        "revision": quotation.revision,
        "status": quotation.status,
        "currency": str(quotation.currency),
        "incoterm": quotation.incoterm,
        "incoterm_version": quotation.incoterm_version,
        "named_place": quotation.named_place,
        "subtotal": str(quotation.subtotal),
        "total": str(quotation.total),
        "valid_until": quotation.valid_until.isoformat() if quotation.valid_until else None,
        "items": [
            {
                "description": item.description,
                "charge_type": item.charge_type,
                "quantity": str(item.quantity),
                "unit_price": str(item.unit_price),
                "amount": str(item.amount),
            }
            for item in quotation.items.all()
        ],
    }


@transaction.atomic
def revise_quotation(
    quotation: ExportQuotation,
    *,
    actor,
    changes: dict,
    items: list[dict] | None = None,
    summary: str = "",
) -> ExportQuotation:
    """Snapshot the current quotation and reopen it as a new revision."""
    _require_manage(actor)
    _require(
        quotation.status != ExportQuotationStatus.SUPERSEDED,
        "A superseded quotation cannot be revised.",
    )
    ExportQuotationRevision.objects.create(
        quotation=quotation,
        revision_number=quotation.revision,
        snapshot=_quotation_snapshot(quotation),
        changes_summary=summary,
        created_by=_audit_actor(actor),
    )
    quotation.status = ExportQuotationStatus.DRAFT
    quotation.approved_by = None
    quotation.approved_at = None
    quotation.issued_at = None
    quotation.decided_at = None
    quotation.revision = quotation.revision + 1
    for key, value in changes.items():
        setattr(quotation, key, value)
    quotation.save()
    if items is not None:
        quotation.items.all().delete()
        _create_quotation_items(quotation, items)
        subtotal, total = _compute_totals(items)
        quotation.subtotal, quotation.total = subtotal, total
        quotation.save(update_fields=["subtotal", "total", "updated_at"])
    record_audit(actor=actor, action="export.quotation.revise", target=quotation)
    return quotation


@transaction.atomic
def supersede_quotation(old: ExportQuotation, new: ExportQuotation, *, actor) -> ExportQuotation:
    _require_manage(actor)
    new.supersedes = old
    new.save(update_fields=["supersedes", "updated_at"])
    if old.status != ExportQuotationStatus.SUPERSEDED:
        old.status = ExportQuotationStatus.SUPERSEDED
        old.decided_at = timezone.now()
        old.save(update_fields=["status", "decided_at", "updated_at"])
    return new


@transaction.atomic
def accept_quotation(quotation: ExportQuotation, *, actor) -> ExportOrder:
    """Accept an issued quotation and create its export order (idempotent).

    The customer who owns the quotation may accept it; export staff may accept on
    their behalf. The internal enquiry transition to ``converted`` is a system
    step and therefore does not require ``EXPORT_MANAGE``.
    """
    is_staff = has_capability(
        actor, Capability.EXPORT_MANAGE, Capability.EXPORT_APPROVE, any_of=True
    )
    if not is_staff and getattr(actor, "pk", None) != quotation.customer_id:
        raise PermissionDenied("You cannot accept a quotation that is not yours.")
    _require(
        quotation.status == ExportQuotationStatus.ISSUED,
        "Only an issued quotation can be accepted.",
    )
    _require(
        quotation.valid_until is None or quotation.valid_until >= timezone.localdate(),
        "This quotation has expired; request a revision.",
    )
    quotation.status = ExportQuotationStatus.ACCEPTED
    quotation.decided_at = timezone.now()
    quotation.save(update_fields=["status", "decided_at", "updated_at"])
    if quotation.enquiry_id:
        _mark_enquiry_quoted(quotation.enquiry, actor=actor)
        _advance_enquiry(
            quotation.enquiry,
            ExportEnquiryStatus.CONVERTED,
            actor=actor,
            note="Quotation accepted.",
        )
    notifications.quotation_accepted(quotation)
    order = create_export_order_from_quotation(quotation, actor=actor)
    record_audit(actor=actor, action="export.quotation.accept", target=quotation)
    return order


# ---------------------------------------------------------------------------
# Task 5 — export orders
# ---------------------------------------------------------------------------


@transaction.atomic
def create_export_order_from_quotation(quotation: ExportQuotation, *, actor) -> ExportOrder:
    _require(
        quotation.status == ExportQuotationStatus.ACCEPTED,
        "An export order requires an accepted quotation.",
    )
    existing = ExportOrder.objects.filter(quotation=quotation).first()
    if existing is not None:
        return existing

    deposit = quotation.required_deposit()
    order = ExportOrder.objects.create(
        customer=quotation.customer,
        destination=quotation.destination,
        quotation=quotation,
        currency=quotation.currency,
        incoterm=quotation.incoterm,
        incoterm_version=quotation.incoterm_version,
        named_place=quotation.named_place,
        payment_terms=quotation.payment_terms,
        commercial_terms=_quotation_snapshot(quotation),
        total=quotation.total,
        deposit_amount=deposit,
        balance_amount=quotation.total - deposit,
    )
    for item in quotation.items.all():
        if item.charge_type != "product":
            continue
        ExportOrderItem.objects.create(
            order=order,
            product=item.product,
            listing=item.listing,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=item.unit_price,
            snapshot={"quotation_item": str(item.pk)},
        )
    ExportOrderStatusHistory.objects.create(
        order=order,
        from_status="",
        to_status=order.status,
        actor=_audit_actor(actor),
        note=f"Created from quotation {quotation.reference}.",
    )
    # System-generated at acceptance time; the accepting actor may be the
    # customer, so this is not capability-gated.
    build_compliance_checklist(order)
    return order


@transaction.atomic
def create_export_order(quotation: ExportQuotation, *, actor) -> ExportOrder:
    """Public alias used by views/tests: create an order from accepted terms."""
    return create_export_order_from_quotation(quotation, actor=actor)


@transaction.atomic
def _advance_export_order(
    order: ExportOrder, to_status: str, *, actor, note: str = ""
) -> ExportOrder:
    """Move an export order along a legal path, recording history (no capability gate).

    Used by staff-facing transitions (which gate on ``EXPORT_MANAGE``) and by the
    trusted, server-side payment settlement path (:func:`record_verified_payment`),
    which has no human actor.
    """
    path = _path(order.status, to_status, EXPORT_ORDER_TRANSITIONS)
    if path is None:
        raise ValidationError(f"Cannot move export order from {order.status} to {to_status}.")
    if not order.is_compliance_cleared and (
        ExportOrderStatus.READY_FOR_SHIPMENT in path or ExportOrderStatus.SHIPPED in path
    ):
        raise ValidationError(
            "Compliance must be cleared before the order can become ready to ship."
        )
    for step in path:
        ExportOrderStatusHistory.objects.create(
            order=order,
            from_status=order.status,
            to_status=step,
            actor=_audit_actor(actor),
            note=note,
        )
        order.status = step
    now = timezone.now()
    if order.status == ExportOrderStatus.SHIPPED and not order.dispatched_at:
        order.dispatched_at = now
    if order.status == ExportOrderStatus.DELIVERED and not order.delivered_at:
        order.delivered_at = now
    if order.status == ExportOrderStatus.COMPLETED and not order.completed_at:
        order.completed_at = now
    if order.status == ExportOrderStatus.CANCELLED and not order.cancelled_at:
        order.cancelled_at = now
    order.save()
    return order


@transaction.atomic
def transition_export_order(
    order: ExportOrder, to_status: str, *, actor, note: str = ""
) -> ExportOrder:
    _require_manage(actor)
    return _advance_export_order(order, to_status, actor=actor, note=note)


@transaction.atomic
def assign_export_order(order: ExportOrder, *, actor, assignee) -> ExportOrder:
    _require_manage(actor)
    order.assigned_to = assignee
    order.save(update_fields=["assigned_to", "updated_at"])
    return order


@transaction.atomic
def record_verified_payment(order: ExportOrder, *, amount, actor=None, payment=None) -> ExportOrder:
    """Apply a verified payment to an export order (called only by Phase 6)."""
    amount = Decimal(str(amount))
    _require(amount > 0, "A verified payment must be positive.")
    order = ExportOrder.objects.select_for_update().get(pk=order.pk)
    order.amount_paid = (order.amount_paid + amount).quantize(Decimal("0.01"))
    order.save(update_fields=["amount_paid", "updated_at"])

    threshold = order.deposit_amount or order.total
    if order.status == ExportOrderStatus.PENDING_PAYMENT and order.amount_paid >= threshold:
        _advance_export_order(
            order, ExportOrderStatus.PAYMENT_VERIFIED, actor=actor, note="Payment verified."
        )
    notifications.payment_verified(order, payment)
    return order


# ---------------------------------------------------------------------------
# Task 6 — documents
# ---------------------------------------------------------------------------


def add_document(
    order: ExportOrder,
    *,
    actor,
    document_type: ExportDocumentType,
    file,
    issuing_organization: str = "",
    document_reference: str = "",
    issue_date=None,
    expiration_date=None,
    is_customer_visible: bool = True,
    verification_status: str = DocumentVerificationStatus.SUBMITTED,
) -> ExportDocument:
    _require_manage(actor)
    _require(document_type is not None, "Choose a document type.")
    _require(file, "A file is required.")
    if document_type.requires_expiry:
        _require(expiration_date is not None, f"{document_type.name} requires an expiry date.")
    scan = screen_upload(file, kind="export_document", actor=actor)
    with transaction.atomic():
        document = ExportDocument.objects.create(
            order=order,
            document_type=document_type,
            file=file,
            issuing_organization=issuing_organization,
            document_reference=document_reference,
            issue_date=issue_date,
            expiration_date=expiration_date,
            is_customer_visible=is_customer_visible,
            verification_status=verification_status,
            uploaded_by=_audit_actor(actor),
        )
        bind_scanned_file(scan, document.file)
    return document


def upload_customer_document(
    order: ExportOrder,
    *,
    customer,
    document_type: ExportDocumentType,
    file,
    document_reference: str = "",
    expiration_date=None,
) -> ExportDocument:
    """A customer uploads a supporting document for their own order only."""
    if order.customer_id != getattr(customer, "id", None):
        raise PermissionDenied("You can only upload documents to your own export order.")
    _require(file, "A file is required.")
    scan = screen_upload(file, kind="export_document", actor=customer)
    with transaction.atomic():
        document = ExportDocument.objects.create(
            order=order,
            document_type=document_type,
            file=file,
            document_reference=document_reference,
            expiration_date=expiration_date,
            verification_status=DocumentVerificationStatus.SUBMITTED,
            uploaded_by=customer,
        )
        bind_scanned_file(scan, document.file)
    return document


@transaction.atomic
def review_document(
    document: ExportDocument, *, actor, decision: str, notes: str = "", expiration_date=None
) -> ExportDocument:
    _require_manage(actor)
    _require(decision in DocumentReviewDecision.values, "Unknown review decision.")
    mapping = {
        DocumentReviewDecision.APPROVED: DocumentVerificationStatus.VERIFIED,
        DocumentReviewDecision.REJECTED: DocumentVerificationStatus.REJECTED,
        DocumentReviewDecision.CHANGES_REQUESTED: DocumentVerificationStatus.PENDING,
    }
    document.verification_status = mapping[decision]
    document.reviewed_by = actor
    document.reviewed_at = timezone.now()
    document.review_notes = notes
    if expiration_date is not None:
        document.expiration_date = expiration_date
    document.save(
        update_fields=[
            "verification_status",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "expiration_date",
            "updated_at",
        ]
    )
    ExportDocumentReview.objects.create(
        document=document, reviewer=actor, decision=decision, notes=notes
    )
    notifications.document_reviewed(document)
    record_audit(actor=actor, action="export.document.review", target=document)
    return document


# ---------------------------------------------------------------------------
# Task 7 — compliance checklist
# ---------------------------------------------------------------------------


@transaction.atomic
def build_compliance_checklist(order: ExportOrder, *, actor=None) -> ExportComplianceChecklist:
    """Generate the checklist from the destination's requirements and products."""
    if actor is not None:
        _require_manage(actor)
    checklist, _created = ExportComplianceChecklist.objects.get_or_create(order=order)
    existing = set(checklist.items.values_list("title", flat=True))

    def _add(title, description="", source="", last_verified_at=None, document_requirement=None):
        if title in existing:
            return
        ExportComplianceChecklistItem.objects.create(
            checklist=checklist,
            document_requirement=document_requirement,
            title=title,
            description=description,
            status=ComplianceItemStatus.REQUIRED,
            source=source,
            last_reviewed_at=last_verified_at,
        )
        existing.add(title)

    for item in order.items.select_related("product", "product__category"):
        product = item.product
        category = product.category if product else None
        for requirement in selectors.destination_requirements_for(
            order.destination, product=product, category=category
        ):
            _add(
                requirement.title,
                requirement.description,
                requirement.source,
                requirement.last_verified_at,
            )
        for doc_req in selectors.document_requirements_for(
            order.destination, product=product, category=category
        ):
            _add(
                f"Provide {doc_req.document_type.name}",
                doc_req.document_type.description,
                doc_req.source,
                doc_req.last_verified_at,
                document_requirement=doc_req,
            )
        profile = getattr(product, "export_profile", None) if product else None
        if profile and profile.requires_inspection:
            _add(
                f"Inspection required for {product.name}",
                profile.inspection_notes or "Inspection is required for this product.",
            )

    has_items = checklist.items.exists()
    checklist.status = (
        ComplianceChecklistStatus.IN_PROGRESS if has_items else ComplianceChecklistStatus.PENDING
    )
    checklist.save(update_fields=["status", "updated_at"])
    order.compliance_status = (
        ComplianceStatus.IN_PROGRESS if has_items else ComplianceStatus.PENDING
    )
    order.save(update_fields=["compliance_status", "updated_at"])
    return checklist


@transaction.atomic
def update_compliance_item(
    item: ExportComplianceChecklistItem, *, actor, status: str, document=None, notes: str = ""
) -> ExportComplianceChecklistItem:
    _require_manage(actor)
    _require(status in ComplianceItemStatus.values, "Unknown compliance status.")
    item.status = status
    if notes:
        item.notes = notes
    if document is not None:
        item.document = document
    item.reviewed_by = actor
    item.reviewed_at = timezone.now()
    item.last_reviewed_at = timezone.localdate()
    item.save()

    checklist = item.checklist
    if checklist.status not in {ComplianceChecklistStatus.APPROVED}:
        checklist.status = ComplianceChecklistStatus.IN_PROGRESS
        checklist.save(update_fields=["status", "updated_at"])
    return item


@transaction.atomic
def approve_compliance_checklist(
    checklist: ExportComplianceChecklist, *, actor, notes: str = ""
) -> ExportComplianceChecklist:
    _require_approve(actor)
    _require(checklist.is_complete, "All mandatory compliance items must be verified first.")
    checklist.status = ComplianceChecklistStatus.APPROVED
    checklist.approved_by = actor
    checklist.approved_at = timezone.now()
    if notes:
        checklist.notes = f"{checklist.notes}\n{notes}".strip()
    checklist.save(update_fields=["status", "approved_by", "approved_at", "notes", "updated_at"])
    order = checklist.order
    order.compliance_status = ComplianceStatus.CLEARED
    order.save(update_fields=["compliance_status", "updated_at"])
    record_audit(actor=actor, action="export.compliance.approve", target=checklist)
    return checklist


# ---------------------------------------------------------------------------
# Task 8 — shipments
# ---------------------------------------------------------------------------


@transaction.atomic
def create_shipment(
    order: ExportOrder,
    *,
    actor,
    transport_mode: str,
    origin: str,
    destination: str,
    provider=None,
    departure_date=None,
    estimated_arrival=None,
    tracking_reference: str = "",
    notes: str = "",
) -> ExportShipment:
    _require_manage(actor)
    _require(
        order.status not in {ExportOrderStatus.COMPLETED, ExportOrderStatus.CANCELLED},
        "Cannot create a shipment for a closed order.",
    )
    shipment = ExportShipment.objects.create(
        order=order,
        provider=provider,
        transport_mode=transport_mode,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        estimated_arrival=estimated_arrival,
        tracking_reference=tracking_reference,
        notes=notes,
        created_by=_audit_actor(actor),
    )
    for order_item in order.items.all():
        ExportShipmentItem.objects.create(
            shipment=shipment, order_item=order_item, quantity=order_item.quantity
        )
    return shipment


@transaction.atomic
def transition_shipment(
    shipment: ExportShipment, to_status: str, *, actor, note: str = ""
) -> ExportShipment:
    _require_manage(actor)
    path = _path(shipment.status, to_status, SHIPMENT_TRANSITIONS)
    if path is None:
        raise ValidationError(f"Cannot move shipment from {shipment.status} to {to_status}.")
    order = shipment.order
    for step in path:
        if step == ShipmentStatus.DISPATCHED and not order.is_compliance_cleared:
            raise ValidationError("Compliance must be cleared before a shipment is dispatched.")
        shipment.status = step
        ShipmentMilestone.objects.create(
            shipment=shipment,
            status=step,
            occurred_at=timezone.now(),
            recorded_by=_audit_actor(actor),
            notes=note,
            is_staff_entered=True,
        )
    if shipment.status == ShipmentStatus.DELIVERED:
        shipment.actual_arrival = shipment.actual_arrival or timezone.localdate()
        if order.status == ExportOrderStatus.READY_FOR_SHIPMENT:
            transition_export_order(
                order, ExportOrderStatus.SHIPPED, actor=actor, note="Shipment dispatched."
            )
        if order.status == ExportOrderStatus.SHIPPED:
            transition_export_order(
                order, ExportOrderStatus.DELIVERED, actor=actor, note="Shipment delivered."
            )
    elif shipment.status == ShipmentStatus.DISPATCHED:
        if order.status == ExportOrderStatus.READY_FOR_SHIPMENT:
            transition_export_order(
                order, ExportOrderStatus.SHIPPED, actor=actor, note="Shipment dispatched."
            )
    shipment.save()
    if shipment.status == ShipmentStatus.DISPATCHED:
        notifications.shipment_dispatched(shipment)
    elif shipment.status == ShipmentStatus.DELIVERED:
        notifications.delivery_confirmed(shipment)
    else:
        notifications.shipment_status_updated(shipment)
    notification_events.export_shipment_updated(shipment)
    return shipment


@transaction.atomic
def add_shipment_milestone(
    shipment: ExportShipment,
    *,
    actor,
    status: str,
    occurred_at=None,
    location: str = "",
    notes: str = "",
) -> ShipmentMilestone:
    """Record a real, staff-entered milestone (never fabricated live tracking)."""
    _require_manage(actor)
    _require(status in ShipmentStatus.values, "Unknown shipment status.")
    return ShipmentMilestone.objects.create(
        shipment=shipment,
        status=status,
        occurred_at=occurred_at or timezone.now(),
        location=location,
        notes=notes,
        recorded_by=_audit_actor(actor),
        is_staff_entered=True,
    )


@transaction.atomic
def set_shipment_tracking(
    shipment: ExportShipment, *, actor, tracking_reference: str
) -> ExportShipment:
    _require_manage(actor)
    shipment.tracking_reference = tracking_reference
    shipment.save(update_fields=["tracking_reference", "updated_at"])
    return shipment


@transaction.atomic
def add_document_requirement(destination: ExportDestination, *, actor, document_type, **fields):
    """Record a destination document requirement (staff-entered, with source)."""
    _require_manage(actor)
    return ExportDocumentRequirement.objects.create(
        destination=destination, document_type=document_type, **fields
    )


@transaction.atomic
def upsert_logistics_provider(*, actor, provider: LogisticsProvider | None = None, **fields):
    """Create or update a logistics provider record."""
    _require_manage(actor)
    if provider is None:
        provider = LogisticsProvider.objects.create(**fields)
    else:
        for key, value in fields.items():
            setattr(provider, key, value)
        provider.save()
    return provider

"""Support-centre services (Task 10 + Task 12).

All writes go through here so status transitions, ownership validation,
notification creation and audit logging cannot be bypassed. Customer-facing and
staff-facing callers share the same state machine.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.notifications import events as notification_events
from apps.notifications.services import emit

from .links import resolve_related
from .models import (
    SupportAttachment,
    SupportCategory,
    SupportMessage,
    SupportPriority,
    SupportStatus,
    SupportStatusHistory,
    SupportTicket,
)
from .validators import validate_attachment

logger = logging.getLogger(__name__)


def _touch(ticket: SupportTicket) -> None:
    ticket.last_activity_at = timezone.now()
    ticket.save(update_fields=["last_activity_at", "updated_at"])


def _apply_transition(
    ticket: SupportTicket,
    new_status: str,
    *,
    actor,
    reason: str = "",
) -> None:
    if new_status == ticket.status:
        return
    if not ticket.can_transition_to(new_status):
        raise ValidationError(
            f"A ticket cannot move from '{ticket.get_status_display()}' to "
            f"'{SupportStatus(new_status).label}'."
        )
    previous = ticket.status
    ticket.status = new_status
    now = timezone.now()
    update_fields = ["status", "last_activity_at", "updated_at"]
    ticket.last_activity_at = now
    if new_status == SupportStatus.RESOLVED:
        ticket.resolved_at = now
        update_fields.append("resolved_at")
    if new_status == SupportStatus.CLOSED:
        ticket.closed_at = now
        update_fields.append("closed_at")
    if new_status == SupportStatus.REOPENED:
        ticket.reopened_at = now
        ticket.resolved_at = None
        ticket.closed_at = None
        update_fields += ["reopened_at", "resolved_at", "closed_at"]
    ticket.save(update_fields=update_fields)
    SupportStatusHistory.objects.create(
        ticket=ticket,
        previous_status=previous,
        new_status=new_status,
        changed_by=actor if getattr(actor, "is_authenticated", False) else None,
        reason=reason[:255],
    )


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
@transaction.atomic
def create_ticket(
    *,
    customer,
    subject: str,
    category: str = SupportCategory.GENERAL,
    priority: str = SupportPriority.NORMAL,
    message: str,
    files=None,
    related_type: str = "",
    related_id: str = "",
    request=None,
) -> SupportTicket:
    """Create a ticket with its opening message, attachments and history row."""
    subject = (subject or "").strip()
    if not subject:
        raise ValidationError("A subject is required.")
    if not message:
        raise ValidationError("Please describe your enquiry.")
    # Ownership check (raises ValidationError for another customer's record).
    resolve_related(customer, related_type, related_id)

    ticket = SupportTicket.objects.create(
        customer=customer,
        subject=subject[:200],
        category=category,
        priority=priority,
        status=SupportStatus.OPEN,
        related_type=related_type or "",
        related_id=str(related_id or "")[:64],
    )
    opener = SupportMessage.objects.create(ticket=ticket, sender=customer, message=message)
    _create_attachments(ticket=ticket, message=opener, files=files, uploaded_by=customer)
    SupportStatusHistory.objects.create(
        ticket=ticket,
        previous_status="",
        new_status=SupportStatus.OPEN,
        changed_by=customer,
        reason="Ticket created.",
    )
    record_audit(
        actor=customer,
        action="support.ticket.created",
        target=ticket,
        after={"reference": ticket.reference, "category": ticket.category},
    )
    return ticket


def _create_attachments(*, ticket, message, files, uploaded_by) -> None:
    for upload in files or []:
        validate_attachment(upload)
        SupportAttachment.objects.create(
            ticket=ticket,
            message=message,
            file=upload,
            original_filename=getattr(upload, "name", "")[:255],
            uploaded_by=uploaded_by,
        )


def add_customer_message(
    ticket: SupportTicket,
    *,
    sender,
    message: str,
    files=None,
    request=None,
) -> SupportMessage:
    """Customer reply. Moves a waiting ticket back into progress."""
    if sender.pk != ticket.customer_id:
        raise ValidationError("You cannot reply to this ticket.")
    if not message:
        raise ValidationError("A message is required.")
    if ticket.status == SupportStatus.CLOSED:
        raise ValidationError("This ticket is closed. Reopen it to reply.")

    with transaction.atomic():
        support_message = SupportMessage.objects.create(
            ticket=ticket, sender=sender, message=message
        )
        _create_attachments(ticket=ticket, message=support_message, files=files, uploaded_by=sender)
        if ticket.status == SupportStatus.WAITING_FOR_CUSTOMER:
            _apply_transition(
                ticket, SupportStatus.IN_PROGRESS, actor=sender, reason="Customer replied."
            )
        else:
            _touch(ticket)
    return support_message


def add_staff_message(
    ticket: SupportTicket,
    *,
    sender,
    message: str,
    is_internal: bool = False,
    files=None,
    request=None,
) -> SupportMessage:
    """Staff reply or internal note. Public replies notify the customer."""
    if not message:
        raise ValidationError("A message is required.")
    with transaction.atomic():
        support_message = SupportMessage.objects.create(
            ticket=ticket,
            sender=sender,
            message=message,
            is_internal=is_internal,
        )
        _create_attachments(ticket=ticket, message=support_message, files=files, uploaded_by=sender)
        if not is_internal:
            if ticket.status in {
                SupportStatus.OPEN,
                SupportStatus.REOPENED,
                SupportStatus.ASSIGNED,
            }:
                _apply_transition(
                    ticket, SupportStatus.IN_PROGRESS, actor=sender, reason="Staff replied."
                )
            if ticket.status == SupportStatus.IN_PROGRESS:
                _apply_transition(
                    ticket,
                    SupportStatus.WAITING_FOR_CUSTOMER,
                    actor=sender,
                    reason="Awaiting customer response.",
                )
            _touch(ticket)
        else:
            _touch(ticket)
    if not is_internal:
        # Create the in-app notification (delivery is scheduled after commit).
        try:
            notification_events.support_ticket_reply(support_message)
        except Exception:  # pragma: no cover - notifications never break support
            logger.exception("Failed to create support reply notification.")
    return support_message


def assign_ticket(
    ticket: SupportTicket,
    *,
    assignee,
    actor,
    request=None,
) -> SupportTicket:
    """Assign (or reassign) a ticket to a staff member."""
    with transaction.atomic():
        ticket.assigned_to = assignee
        ticket.save(update_fields=["assigned_to", "updated_at"])
        if ticket.status in {SupportStatus.OPEN, SupportStatus.REOPENED}:
            _apply_transition(ticket, SupportStatus.ASSIGNED, actor=actor, reason="Assigned.")
        else:
            _touch(ticket)
    record_audit(
        actor=actor,
        action="support.ticket.assigned",
        target=ticket,
        after={"assigned_to": str(getattr(assignee, "pk", ""))},
        request=request,
    )
    return ticket


def change_status(
    ticket: SupportTicket,
    *,
    new_status: str,
    actor,
    reason: str = "",
    request=None,
) -> SupportTicket:
    """Staff status transition, recorded in the history trail."""
    with transaction.atomic():
        _apply_transition(ticket, new_status, actor=actor, reason=reason)
    record_audit(
        actor=actor,
        action="support.ticket.status_changed",
        target=ticket,
        after={"status": new_status, "reason": reason[:255]},
        request=request,
    )
    return ticket


def change_priority(
    ticket: SupportTicket,
    *,
    priority: str,
    actor,
    request=None,
) -> SupportTicket:
    """Manager-only priority change, recorded in the audit trail."""
    valid = {choice.value for choice in SupportPriority}
    if priority not in valid:
        raise ValidationError("Invalid priority.")
    ticket.priority = priority
    ticket.save(update_fields=["priority", "updated_at"])
    record_audit(
        actor=actor,
        action="support.ticket.priority_changed",
        target=ticket,
        after={"priority": priority},
        request=request,
    )
    return ticket


def reopen_ticket(
    ticket: SupportTicket,
    *,
    actor,
    reason: str = "",
    request=None,
) -> SupportTicket:
    """Customer or staff reopen, honouring the configured reopen window."""
    if not ticket.can_reopen():
        raise ValidationError("This ticket is beyond the reopening window.")
    with transaction.atomic():
        if ticket.status not in {SupportStatus.RESOLVED, SupportStatus.CLOSED}:
            raise ValidationError("Only resolved or closed tickets can be reopened.")
        _apply_transition(ticket, SupportStatus.REOPENED, actor=actor, reason=reason or "Reopened.")
    record_audit(
        actor=actor,
        action="support.ticket.reopened",
        target=ticket,
        request=request,
    )
    return ticket


def close_ticket(ticket: SupportTicket, *, actor, reason: str = "", request=None):
    """Customer-facing close shortcut."""
    return change_status(
        ticket,
        new_status=SupportStatus.CLOSED,
        actor=actor,
        reason=reason or "Closed by customer.",
        request=request,
    )


__all__ = [
    "SupportCategory",
    "SupportPriority",
    "add_customer_message",
    "add_staff_message",
    "assign_ticket",
    "change_status",
    "close_ticket",
    "create_ticket",
    "emit",
    "reopen_ticket",
]

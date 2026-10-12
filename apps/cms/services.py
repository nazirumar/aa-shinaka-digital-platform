"""Write operations for website content and enquiries.

Following the project convention, every state-changing operation lives in the
service layer, runs inside a transaction where it touches multiple rows,
enforces authorisation on the server, and writes an audit entry. Views stay
thin. Audit records never contain secrets (see ``apps.core.audit``).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.core.constants import BusinessDivision as BusinessDivisionChoice

from .models import ContactEnquiry, PublishStatus, Testimonial


@transaction.atomic
def submit_contact_enquiry(
    *,
    name: str,
    email: str,
    message: str,
    phone: str = "",
    subject: str = "",
    division: str = "",
    request=None,
) -> ContactEnquiry:
    """Store a public contact enquiry and write an audit record.

    The stored ``division`` is validated against the canonical business
    divisions; anything else is discarded rather than persisted.
    """
    valid_divisions = {choice.value for choice in BusinessDivisionChoice}
    safe_division = division if division in valid_divisions else ""

    ip_address = None
    user_agent = ""
    if request is not None:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        ip_address = (
            forwarded.split(",")[0].strip()
            if forwarded
            else request.META.get("REMOTE_ADDR") or None
        )
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]

    enquiry = ContactEnquiry.objects.create(
        name=name.strip(),
        email=email.strip().lower(),
        phone=phone.strip(),
        subject=subject.strip(),
        division=safe_division,
        message=message.strip(),
        ip_address=ip_address or None,
        user_agent=user_agent,
    )
    record_audit(
        actor=None,
        action="cms.enquiry.submitted",
        target=enquiry,
        after={"email": enquiry.email, "division": enquiry.division},
        request=request,
    )
    return enquiry


@transaction.atomic
def mark_enquiry_handled(enquiry: ContactEnquiry, *, actor, request=None) -> ContactEnquiry:
    if not enquiry.is_handled:
        enquiry.mark_handled(actor)
        enquiry.save(update_fields=["is_handled", "handled_by", "handled_at", "updated_at"])
        record_audit(
            actor=actor,
            action="cms.enquiry.handled",
            target=enquiry,
            after={"is_handled": True},
            request=request,
        )
    return enquiry


@transaction.atomic
def set_publish_status(obj, *, status: str, actor, request=None):
    """Publish, unpublish (draft) or archive a publishable content object."""
    if status not in PublishStatus.values:
        raise ValueError(f"Unknown publish status: {status!r}")

    before = {"status": obj.status, "published_at": obj.published_at}
    obj.status = status
    if status == PublishStatus.PUBLISHED:
        if obj.published_at is None:
            obj.published_at = timezone.now()
    obj.save(update_fields=["status", "published_at", "updated_at"])
    record_audit(
        actor=actor,
        action=f"cms.{obj._meta.model_name}.{status}",
        target=obj,
        before=before,
        after={"status": obj.status},
        request=request,
    )
    return obj


@transaction.atomic
def approve_testimonial(testimonial: Testimonial, *, actor, request=None) -> Testimonial:
    before = {"is_approved": testimonial.is_approved}
    testimonial.is_approved = True
    testimonial.approved_by = actor if getattr(actor, "is_authenticated", False) else None
    testimonial.approved_at = timezone.now()
    testimonial.save(update_fields=["is_approved", "approved_by", "approved_at", "updated_at"])
    record_audit(
        actor=actor,
        action="cms.testimonial.approved",
        target=testimonial,
        before=before,
        after={"is_approved": True},
        request=request,
    )
    return testimonial


@transaction.atomic
def unapprove_testimonial(testimonial: Testimonial, *, actor, request=None) -> Testimonial:
    before = {"is_approved": testimonial.is_approved}
    testimonial.is_approved = False
    testimonial.approved_by = None
    testimonial.approved_at = None
    testimonial.save(update_fields=["is_approved", "approved_by", "approved_at", "updated_at"])
    record_audit(
        actor=actor,
        action="cms.testimonial.unapproved",
        target=testimonial,
        before=before,
        after={"is_approved": False},
        request=request,
    )
    return testimonial

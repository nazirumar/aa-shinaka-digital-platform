"""Write layer for the service domain (consultancy, farming, marketing, storage).

Every mutation is validated server-side, transactional where it must be
(appointment overlap, storage capacity), capability-checked and audited where
sensitive. Money is always ``Decimal``; totals are recomputed from line items
and never trusted from the client.

Shared vocabulary
-----------------
* A :class:`~apps.services.models.ServiceRequest` is the common request record.
* Each division attaches exactly one explicit detail record to it
  (``consultation_appointment``, ``farm_request``, ``marketing_request``,
  ``storage_request``).
* Prices flow through :class:`~apps.services.models.ServiceQuotation`; a paid
  quotation is activated by the Phase 6 payment pipeline calling
  :func:`apps.services.payments.settle_quotation_payment`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability
from apps.core.audit import record_audit
from apps.core.upload_security import bind_scanned_file, screen_upload
from apps.notifications import events as notification_events

from . import notifications
from .models import (
    ACTIVE_APPOINTMENT_STATES,
    AppointmentStatus,
    ConsultancyService,
    Consultant,
    ConsultantAvailability,
    ConsultationAppointment,
    ConsultationMode,
    ConsultationReport,
    FarmAreaUnit,
    FarmingSeason,
    FarmingService,
    FarmProgressReport,
    FarmProject,
    FarmProjectMilestone,
    FarmProjectStatus,
    FarmServiceRequest,
    FarmVisit,
    InspectionCondition,
    MarketingActivity,
    MarketingCampaign,
    MarketingCampaignStatus,
    MarketingEnquiry,
    MarketingProposal,
    MarketingProposalStatus,
    MarketingService,
    MilestoneStatus,
    ProduceType,
    QuotationPaymentStatus,
    QuotationStatus,
    ServiceActivityLog,
    ServiceAssignment,
    ServiceAttachment,
    ServiceComment,
    ServicePriority,
    ServiceQuotation,
    ServiceQuotationItem,
    ServiceRequest,
    ServiceRequestStatus,
    ServiceRequestStatusHistory,
    ServiceType,
    StorageBooking,
    StorageBookingStatus,
    StorageCapacityAllocation,
    StorageCheckIn,
    StorageCheckOut,
    StorageFacility,
    StorageInspection,
    StorageServiceRequest,
    StorageUnit,
    VisitStatus,
)

ZERO = Decimal("0.00")

#: Uploads are restricted to safe document/image types and a bounded size.
ALLOWED_ATTACHMENT_EXTENSIONS = frozenset(
    {"pdf", "png", "jpg", "jpeg", "gif", "webp", "doc", "docx", "xls", "xlsx", "csv", "txt"}
)
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB

DIVISION_CAPABILITY = {
    ServiceType.CONSULTANCY: Capability.REQUESTS_CONSULTANCY,
    ServiceType.FARMING: Capability.REQUESTS_FARMING,
    ServiceType.MARKETING: Capability.REQUESTS_MARKETING,
    ServiceType.STORAGE: Capability.REQUESTS_STORAGE,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_capability(actor, *capabilities) -> None:
    if not any(has_capability(actor, cap) for cap in capabilities):
        raise PermissionDenied("You do not have permission to perform this action.")


def division_capability(service_type: str) -> str:
    return {
        ServiceType.CONSULTANCY: Capability.REQUESTS_CONSULTANCY,
        ServiceType.FARMING: Capability.REQUESTS_FARMING,
        ServiceType.MARKETING: Capability.REQUESTS_MARKETING,
        ServiceType.STORAGE: Capability.REQUESTS_STORAGE,
    }[service_type]


def require_staff_for_request(actor, service_request) -> None:
    """Staff may act on a division only with its capability (admins have all)."""
    if actor is None:
        # System-initiated action (e.g. verified payment settlement).
        return
    if not has_capability(actor, division_capability(service_request.service_type)):
        raise PermissionDenied("You are not authorised for this service division.")


def _require_customer(actor, customer) -> None:
    if getattr(actor, "id", None) != getattr(customer, "id", None) and not has_capability(
        actor, Capability.FINANCE_MANAGE
    ):
        raise PermissionDenied("You cannot act on this record.")


def _log(service_request, *, actor, action: str, detail: str = "") -> ServiceActivityLog:
    return ServiceActivityLog.objects.create(
        request=service_request, actor=actor, action=action, summary=detail[:240]
    )


def _as_decimal(value, *, field: str = "value") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a valid number.") from exc


def _money(value) -> Decimal:
    return _as_decimal(value).quantize(Decimal("0.01"))


def _transition(service_request, *, to_status: str, actor, note: str = "") -> ServiceRequest:
    """Move a request along the shared pipeline, recording history + activity.

    A request acted on straight from ``submitted`` (a staff confirmation or an
    activation) is implicitly reviewed first, so the recorded history still
    reflects the declared pipeline rather than skipping a stage.
    """
    if to_status == service_request.status:
        return service_request
    if not service_request.can_transition_to(to_status):
        if service_request.status == ServiceRequestStatus.SUBMITTED:
            _transition(
                service_request,
                to_status=ServiceRequestStatus.UNDER_REVIEW,
                actor=actor,
                note="",
            )
        if not service_request.can_transition_to(to_status):
            raise ValidationError(
                f"Cannot move this request from {service_request.get_status_display()} "
                f"to {dict(ServiceRequestStatus.choices).get(to_status, to_status)}."
            )
    previous = service_request.status
    previous = service_request.status
    service_request.status = to_status
    if to_status in {
        ServiceRequestStatus.COMPLETED,
        ServiceRequestStatus.REJECTED,
        ServiceRequestStatus.CANCELLED,
    }:
        service_request.closed_at = timezone.now()
    service_request.save(update_fields=["status", "closed_at", "updated_at"])
    ServiceRequestStatusHistory.objects.create(
        request=service_request,
        from_status=previous,
        to_status=to_status,
        actor=actor,
        note=note,
    )
    _log(service_request, actor=actor, action=f"status.{to_status}", detail=note)
    return service_request


# ---------------------------------------------------------------------------
# Shared foundation
# ---------------------------------------------------------------------------


def create_service_request(
    *,
    customer,
    service_type: str,
    title: str,
    description: str = "",
    priority: str = ServicePriority.NORMAL,
    state=None,
    lga=None,
    preferred_date=None,
    notify: bool = True,
) -> ServiceRequest:
    if service_type not in ServiceType.values:
        raise ValidationError("Unknown service type.")
    if not title.strip():
        raise ValidationError("A title is required.")
    service_request = ServiceRequest.objects.create(
        customer=customer,
        service_type=service_type,
        title=title.strip()[:160],
        description=description,
        priority=priority,
        state=state,
        lga=lga,
        preferred_date=preferred_date,
    )
    ServiceRequestStatusHistory.objects.create(
        request=service_request,
        from_status="",
        to_status=ServiceRequestStatus.SUBMITTED,
        note="Created",
    )
    _log(service_request, actor=customer, action="request.created")
    if notify:
        notifications.service_request_submitted(service_request)
    return service_request


def review_service_request(
    service_request, *, actor, note: str = "", priority: str | None = None
) -> ServiceRequest:
    require_staff_for_request(actor, service_request)
    if priority:
        service_request.priority = priority
        service_request.save(update_fields=["priority", "updated_at"])
    if service_request.status == ServiceRequestStatus.SUBMITTED:
        _transition(
            service_request, to_status=ServiceRequestStatus.UNDER_REVIEW, actor=actor, note=note
        )
        notifications.staff_review_completed(
            service_request, message=note or "Our team has reviewed your request."
        )
    record_audit(
        actor=actor,
        action="services.request.reviewed",
        target=service_request,
        after={"reference": service_request.reference, "status": service_request.status},
    )
    return service_request


def assign_staff(
    service_request, *, staff, actor, role: str = "", note: str = ""
) -> ServiceAssignment:
    require_staff_for_request(actor, service_request)
    assignment, created = ServiceAssignment.objects.get_or_create(
        request=service_request,
        staff=staff,
        role=role,
        defaults={"assigned_by": actor, "note": note[:200]},
    )
    if not created:
        assignment.is_active = True
        assignment.save(update_fields=["is_active", "updated_at"])
    if service_request.assigned_to_id is None:
        service_request.assigned_to = staff
        service_request.save(update_fields=["assigned_to", "updated_at"])
    _log(service_request, actor=actor, action="assignment.added", detail=f"{staff} ({role})")
    record_audit(
        actor=actor,
        action="services.request.assigned",
        target=service_request,
        after={"staff": str(staff.pk), "role": role},
    )
    return assignment


def add_comment(
    service_request, *, author, body: str, visibility: str = "customer"
) -> ServiceComment:
    if not body.strip():
        raise ValidationError("A comment cannot be empty.")
    comment = ServiceComment.objects.create(
        request=service_request, author=author, body=body.strip(), visibility=visibility
    )
    _log(service_request, actor=author, action="comment.added")
    return comment


def add_attachment(
    service_request,
    *,
    uploaded_by,
    file,
    label: str = "",
    is_customer_visible: bool = True,
) -> ServiceAttachment:
    size = getattr(file, "size", 0) or 0
    if size > MAX_ATTACHMENT_BYTES:
        raise ValidationError("Attachments must be 10MB or smaller.")
    name = getattr(file, "name", "") or ""
    if "." not in name or name.rsplit(".", 1)[-1].lower() not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValidationError("Unsupported file type.")
    scan = screen_upload(file, kind="service_attachment", actor=uploaded_by)
    attachment = ServiceAttachment.objects.create(
        request=service_request,
        uploaded_by=uploaded_by,
        file=file,
        label=label[:120] or name[:120],
        content_type=getattr(file, "content_type", "") or "",
        size=size,
        is_customer_visible=is_customer_visible,
    )
    bind_scanned_file(scan, attachment.file)
    _log(service_request, actor=uploaded_by, action="attachment.added", detail=attachment.label)
    return attachment


# ---------------------------------------------------------------------------
# Consultancy (Task 2)
# ---------------------------------------------------------------------------


def create_consultancy_service(*, actor, name: str, **fields) -> ConsultancyService:
    if not has_capability(actor, Capability.REQUESTS_CONSULTANCY):
        raise PermissionDenied("You cannot manage consultancy services.")
    return ConsultancyService.objects.create(name=name, **fields)


def create_consultant(*, actor, user, **fields) -> Consultant:
    if not has_capability(actor, Capability.REQUESTS_CONSULTANCY):
        raise PermissionDenied("You cannot manage consultants.")
    consultant, _ = Consultant.objects.update_or_create(user=user, defaults=fields)
    return consultant


def set_consultant_availability(
    consultant, *, actor, start_time, end_time, weekday=None, specific_date=None
) -> ConsultantAvailability:
    if not has_capability(actor, Capability.REQUESTS_CONSULTANCY):
        raise PermissionDenied("You cannot manage availability.")
    if (weekday is None) == (specific_date is None):
        raise ValidationError("Provide exactly one of weekday or specific_date.")
    if end_time <= start_time:
        raise ValidationError("The end time must be after the start time.")
    return ConsultantAvailability.objects.create(
        consultant=consultant,
        weekday=weekday,
        specific_date=specific_date,
        start_time=start_time,
        end_time=end_time,
    )


def _appointment_window(service, start, duration_minutes=None):
    if start is None:
        raise ValidationError("A preferred start time is required.")
    minutes = duration_minutes or (service.duration_minutes if service else 60)
    return start, start + timedelta(minutes=minutes)


def _assert_consultant_available(consultant, start, end, *, exclude_pk=None) -> None:
    windows = list(consultant.availability.filter(is_active=True))
    if windows and not any(window.covers(start, end) for window in windows):
        raise ValidationError("The consultant is not available at the requested time.")
    if not windows:
        raise ValidationError("The consultant has no availability configured.")
    conflict = (
        consultant.appointments.filter(
            status__in=ACTIVE_APPOINTMENT_STATES,
            scheduled_start__lt=end,
            scheduled_end__gt=start,
        )
        .exclude(pk=exclude_pk)
        .exists()
    )
    if conflict:
        raise ValidationError("The consultant already has an appointment in that window.")


def book_consultation(
    *,
    customer,
    service: ConsultancyService,
    mode: str,
    preferred_start: datetime,
    description: str = "",
    state=None,
    lga=None,
    address: str = "",
) -> ConsultationAppointment:
    """Create a consultancy request + a *requested* appointment (not confirmed)."""
    if mode == ConsultationMode.ONLINE and not service.supports_online:
        raise ValidationError("This consultation is not offered online.")
    if mode == ConsultationMode.ONSITE and not service.supports_onsite:
        raise ValidationError("This consultation is not offered on-site.")
    start, end = _appointment_window(service, preferred_start)
    if start < timezone.now():
        raise ValidationError("The preferred date must be in the future.")

    with transaction.atomic():
        service_request = create_service_request(
            customer=customer,
            service_type=ServiceType.CONSULTANCY,
            title=f"Consultation: {service.name}",
            description=description,
            state=state,
            lga=lga,
            preferred_date=start.date(),
        )
        appointment = ConsultationAppointment.objects.create(
            request=service_request,
            service=service,
            mode=mode,
            scheduled_start=start,
            scheduled_end=end,
            status=AppointmentStatus.REQUESTED,
            location=address,
        )
    return appointment


@transaction.atomic
def confirm_appointment(appointment, *, actor, consultant=None, start=None, end=None):
    """Confirm (and optionally assign/reschedule) an appointment.

    Locks the consultant row and rejects overlapping confirmed appointments.
    """
    require_staff_for_request(actor, appointment.request)
    appointment = ConsultationAppointment.objects.select_for_update().get(pk=appointment.pk)
    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
        raise ValidationError("This appointment can no longer be changed.")

    consultant = consultant or appointment.consultant
    if consultant is None:
        raise ValidationError("Assign a consultant before confirming.")
    Consultant.objects.select_for_update().get(pk=consultant.pk)

    window_start = start or appointment.scheduled_start
    window_end = end or appointment.scheduled_end
    if window_end <= window_start:
        raise ValidationError("The end time must be after the start time.")

    _assert_consultant_available(consultant, window_start, window_end, exclude_pk=appointment.pk)

    appointment.consultant = consultant
    appointment.scheduled_start = window_start
    appointment.scheduled_end = window_end
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.confirmed_by = actor
    appointment.confirmed_at = timezone.now()
    appointment.save()

    _transition(
        appointment.request,
        to_status=ServiceRequestStatus.CONFIRMED,
        actor=actor,
        note="Consultation confirmed.",
    )
    notifications.appointment_confirmed(appointment)
    notification_events.consultancy_appointment_confirmed(appointment)
    record_audit(
        actor=actor, action="services.appointment.confirmed", target=appointment, request=None
    )
    return appointment


@transaction.atomic
def reschedule_appointment(appointment, *, actor, start, end=None, consultant=None):
    if appointment.status not in {AppointmentStatus.CONFIRMED, AppointmentStatus.REQUESTED}:
        raise ValidationError("Only a requested or confirmed appointment can be rescheduled.")
    consultant = consultant or appointment.consultant
    if consultant is None:
        raise ValidationError("Assign a consultant first.")
    end = end or (start + timedelta(minutes=appointment.service.duration_minutes))
    if end <= start:
        raise ValidationError("The end time must be after the start time.")
    Consultant.objects.select_for_update().get(pk=consultant.pk)
    _assert_consultant_available(consultant, start, end, exclude_pk=appointment.pk)
    appointment.consultant = consultant
    appointment.rescheduled_from = appointment.scheduled_start
    appointment.scheduled_start = start
    appointment.scheduled_end = end
    appointment.status = AppointmentStatus.RESCHEDULED
    appointment.save()
    notifications.appointment_rescheduled(appointment)
    record_audit(actor=actor, action="services.appointment.rescheduled", target=appointment)
    return appointment


def reject_appointment(appointment, *, actor, reason: str = ""):
    require_staff_for_request(actor, appointment.request)
    appointment.status = AppointmentStatus.REJECTED
    appointment.save(update_fields=["status", "updated_at"])
    _transition(
        appointment.request,
        to_status=ServiceRequestStatus.REJECTED,
        actor=actor,
        note=reason or "Appointment rejected.",
    )
    return appointment


def complete_appointment(appointment, *, actor, summary: str = "") -> ConsultationAppointment:
    require_staff_for_request(actor, appointment.request)
    if appointment.status not in {AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED}:
        raise ValidationError("Only a confirmed appointment can be completed.")
    appointment.status = AppointmentStatus.COMPLETED
    appointment.completed_at = timezone.now()
    appointment.save(update_fields=["status", "completed_at", "updated_at"])
    if appointment.request.status != ServiceRequestStatus.IN_PROGRESS:
        _transition(
            appointment.request,
            to_status=ServiceRequestStatus.IN_PROGRESS,
            actor=actor,
            note=summary or "Consultation delivered.",
        )
    _transition(
        appointment.request,
        to_status=ServiceRequestStatus.COMPLETED,
        actor=actor,
        note="Consultation completed.",
    )
    notifications.service_completed(appointment.request)
    record_audit(actor=actor, action="services.appointment.completed", target=appointment)
    return appointment


def record_consultation_report(
    appointment,
    *,
    actor,
    summary: str,
    findings: str = "",
    recommendations: str = "",
    file=None,
    is_customer_visible: bool = True,
) -> ConsultationReport:
    require_staff_for_request(actor, appointment.request)
    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.REJECTED}:
        raise ValidationError("Cannot report on a cancelled or rejected appointment.")
    return ConsultationReport.objects.create(
        appointment=appointment,
        summary=summary,
        findings=findings,
        recommendations=recommendations,
        file=file,
        issued_by=actor,
        is_customer_visible=is_customer_visible,
    )


# ---------------------------------------------------------------------------
# Farming (Task 3)
# ---------------------------------------------------------------------------


def create_farming_service(*, actor, name: str, **fields) -> FarmingService:
    if not has_capability(actor, Capability.REQUESTS_FARMING):
        raise PermissionDenied("You cannot manage farming services.")
    return FarmingService.objects.create(name=name, **fields)


def submit_farm_service_request(
    *,
    customer,
    farm_location: str,
    requested_service: FarmingService | None = None,
    state=None,
    lga=None,
    farm_size=None,
    area_unit: str = FarmAreaUnit.HECTARE,
    crop_type: str = "",
    season: str = FarmingSeason.ALL_YEAR,
    expected_start_date=None,
    budget_min=None,
    budget_max=None,
    additional_requirements: str = "",
    description: str = "",
) -> FarmServiceRequest:
    if not farm_location.strip():
        raise ValidationError("A farm location is required.")
    if (
        budget_min is not None
        and budget_max is not None
        and _money(budget_min) > _money(budget_max)
    ):
        raise ValidationError("The minimum budget cannot exceed the maximum budget.")
    with transaction.atomic():
        service_request = create_service_request(
            customer=customer,
            service_type=ServiceType.FARMING,
            title=f"Farming service request · {crop_type or farm_location}"[:160],
            description=description,
            state=state,
            lga=lga,
            preferred_date=expected_start_date,
        )
        farm_request = FarmServiceRequest.objects.create(
            request=service_request,
            farm_location=farm_location.strip()[:240],
            requested_service=requested_service,
            state=state,
            lga=lga,
            farm_size=farm_size,
            area_unit=area_unit,
            crop_type=crop_type[:120],
            season=season,
            expected_start_date=expected_start_date,
            budget_min=budget_min,
            budget_max=budget_max,
            additional_requirements=additional_requirements,
        )
    return farm_request


def create_farm_project(
    farm_request,
    *,
    actor,
    name: str,
    manager=None,
    start_date=None,
    end_date=None,
    notes: str = "",
) -> FarmProject:
    require_staff_for_request(actor, farm_request.request)
    if hasattr(farm_request, "project"):
        raise ValidationError("This farm request already has a project.")
    if start_date and end_date and start_date > end_date:
        raise ValidationError("The end date must be after the start date.")
    project = FarmProject.objects.create(
        request=farm_request,
        name=name[:180],
        manager=manager,
        start_date=start_date,
        end_date=end_date,
        status=FarmProjectStatus.DRAFT,
        notes=notes,
    )
    _log(farm_request.request, actor=actor, action="farm.project.created", detail=project.reference)
    return project


def approve_farm_project(project, *, actor, agreement_reference: str = "") -> FarmProject:
    require_staff_for_request(actor, project.request.request)
    if project.status != FarmProjectStatus.DRAFT:
        raise ValidationError("Only a draft project can be approved.")
    project.status = FarmProjectStatus.APPROVED
    project.approved_by = actor
    project.approved_at = timezone.now()
    if agreement_reference:
        project.agreement_reference = agreement_reference[:80]
    project.save(
        update_fields=["status", "approved_by", "approved_at", "agreement_reference", "updated_at"]
    )
    record_audit(actor=actor, action="services.farm_project.approved", target=project)
    return project


def activate_farm_project(project, *, actor) -> FarmProject:
    """Activate only after approval and a recorded agreement (Task 3)."""
    require_staff_for_request(actor, project.request.request)
    if project.status != FarmProjectStatus.APPROVED or project.approved_at is None:
        raise ValidationError("The project must be approved before it can be activated.")
    if not project.agreement_reference:
        raise ValidationError("Record the signed agreement before activating the project.")
    project.status = FarmProjectStatus.ACTIVE
    project.activated_at = timezone.now()
    project.save(update_fields=["status", "activated_at", "updated_at"])
    _transition(
        project.request.request,
        to_status=ServiceRequestStatus.IN_PROGRESS,
        actor=actor,
        note="Project activated.",
    )
    record_audit(actor=actor, action="services.farm_project.activated", target=project)
    return project


def add_farm_milestone(
    project, *, actor, title: str, description: str = "", sequence=None, due_date=None
) -> FarmProjectMilestone:
    require_staff_for_request(actor, project.request.request)
    if project.status not in {FarmProjectStatus.APPROVED, FarmProjectStatus.ACTIVE}:
        raise ValidationError("Milestones can only be added to an approved project.")
    if sequence is None:
        last = project.milestones.order_by("-sequence").first()
        sequence = (last.sequence + 1) if last else 1
    return FarmProjectMilestone.objects.create(
        project=project,
        title=title[:180],
        description=description,
        sequence=sequence,
        due_date=due_date,
    )


def update_farm_milestone(milestone, *, actor, status: str, note: str = "") -> FarmProjectMilestone:
    require_staff_for_request(actor, milestone.project.request.request)
    if status not in MilestoneStatus.values:
        raise ValidationError("Unknown milestone status.")
    milestone.status = status
    if status == MilestoneStatus.COMPLETED:
        milestone.completed_at = timezone.now()
        milestone.completed_by = actor
    milestone.save()
    notifications.milestone_updated(milestone)
    notification_events.farming_milestone_updated(milestone)
    record_audit(actor=actor, action="services.milestone.updated", target=milestone)
    return milestone


def record_farm_visit(
    project,
    *,
    actor,
    officer=None,
    scheduled_date=None,
    visit_date=None,
    purpose: str = "",
    notes: str = "",
    status: str = VisitStatus.PLANNED,
) -> FarmVisit:
    require_staff_for_request(actor, project.request.request)
    return FarmVisit.objects.create(
        project=project,
        officer=officer or actor,
        scheduled_date=scheduled_date,
        visit_date=visit_date,
        purpose=purpose[:200],
        notes=notes,
        status=status,
    )


def add_farm_progress_report(
    project,
    *,
    actor,
    title: str,
    summary: str,
    progress_percent: int,
    visit=None,
    file=None,
    is_customer_visible: bool = True,
) -> FarmProgressReport:
    require_staff_for_request(actor, project.request.request)
    if not 0 <= int(progress_percent) <= 100:
        raise ValidationError("Progress must be between 0 and 100.")
    return FarmProgressReport.objects.create(
        project=project,
        visit=visit,
        title=title[:180],
        summary=summary,
        progress_percent=int(progress_percent),
        file=file,
        reported_by=actor,
        is_customer_visible=is_customer_visible,
    )


def complete_farm_project(project, *, actor, note: str = "") -> FarmProject:
    require_staff_for_request(actor, project.request.request)
    if project.status not in {FarmProjectStatus.ACTIVE, FarmProjectStatus.ON_HOLD}:
        raise ValidationError("Only an active project can be completed.")
    project.status = FarmProjectStatus.COMPLETED
    project.completed_at = timezone.now()
    project.save(update_fields=["status", "completed_at", "updated_at"])
    _transition(
        project.request.request,
        to_status=ServiceRequestStatus.COMPLETED,
        actor=actor,
        note=note or "Project completed.",
    )
    notifications.service_completed(project.request.request)
    return project


# ---------------------------------------------------------------------------
# Marketing (Task 4)
# ---------------------------------------------------------------------------


def create_marketing_service(*, actor, name: str, **fields) -> MarketingService:
    if not has_capability(actor, Capability.REQUESTS_MARKETING):
        raise PermissionDenied("You cannot manage marketing services.")
    return MarketingService.objects.create(name=name, **fields)


def submit_marketing_enquiry(
    *,
    customer,
    product_type: str,
    service: MarketingService | None = None,
    available_quantity=0,
    unit=None,
    product_location: str = "",
    target_market: str = "",
    marketing_requirements: str = "",
    preferred_timeline: str = "",
    additional_information: str = "",
    description: str = "",
) -> MarketingEnquiry:
    if not product_type.strip():
        raise ValidationError("A product type is required.")
    with transaction.atomic():
        service_request = create_service_request(
            customer=customer,
            service_type=ServiceType.MARKETING,
            title=f"Marketing enquiry · {product_type}"[:160],
            description=description or marketing_requirements,
        )
        enquiry = MarketingEnquiry.objects.create(
            request=service_request,
            service=service,
            product_type=product_type.strip()[:150],
            available_quantity=_as_decimal(available_quantity),
            unit=unit,
            product_location=product_location[:240],
            target_market=target_market[:200],
            marketing_requirements=marketing_requirements,
            preferred_timeline=preferred_timeline[:120],
            additional_information=additional_information,
        )
    return enquiry


def create_marketing_proposal(
    enquiry, *, actor, title: str, scope: str = "", approach: str = "", quotation=None
) -> MarketingProposal:
    require_staff_for_request(actor, enquiry.request)
    if quotation is not None and quotation.customer_id != enquiry.request.customer_id:
        raise ValidationError("The quotation belongs to a different customer.")
    return MarketingProposal.objects.create(
        enquiry=enquiry, title=title[:180], scope=scope, approach=approach, quotation=quotation
    )


def issue_marketing_proposal(proposal, *, actor) -> MarketingProposal:
    require_staff_for_request(actor, proposal.enquiry.request)
    if proposal.status != MarketingProposalStatus.DRAFT:
        raise ValidationError("Only a draft proposal can be issued.")
    proposal.status = MarketingProposalStatus.ISSUED
    proposal.issued_by = actor
    proposal.issued_at = timezone.now()
    proposal.save(update_fields=["status", "issued_by", "issued_at", "updated_at"])
    if quotation := proposal.quotation:
        issue_quotation(quotation, actor=actor)
    return proposal


def decide_marketing_proposal(
    proposal, *, actor, accepted: bool, note: str = ""
) -> MarketingProposal:
    _require_customer(actor, proposal.enquiry.request.customer)
    if proposal.status != MarketingProposalStatus.ISSUED:
        raise ValidationError("Only an issued proposal can be decided.")
    proposal.status = (
        MarketingProposalStatus.ACCEPTED if accepted else MarketingProposalStatus.REJECTED
    )
    proposal.decided_at = timezone.now()
    if proposal.quotation and accepted and proposal.quotation.can_be_accepted:
        proposal.quotation.decision_note = note[:200]
        proposal.quotation.save(update_fields=["decision_note", "updated_at"])
    proposal.save(update_fields=["status", "decided_at", "updated_at"])
    return proposal


def create_marketing_campaign(
    enquiry, *, actor, name: str, officer=None, start_date=None, end_date=None, targets: str = ""
) -> MarketingCampaign:
    require_staff_for_request(actor, enquiry.request)
    if not enquiry.proposals.filter(status=MarketingProposalStatus.ACCEPTED).exists():
        raise ValidationError("A proposal must be accepted before a campaign is created.")
    if start_date and end_date and start_date > end_date:
        raise ValidationError("The end date must be after the start date.")
    campaign = MarketingCampaign.objects.create(
        enquiry=enquiry,
        name=name[:180],
        officer=officer,
        start_date=start_date,
        end_date=end_date,
        targets=targets,
        status=MarketingCampaignStatus.PLANNED,
    )
    if enquiry.request.can_transition_to(ServiceRequestStatus.IN_PROGRESS) or (
        enquiry.request.status == ServiceRequestStatus.SUBMITTED
    ):
        _transition(
            enquiry.request,
            to_status=ServiceRequestStatus.IN_PROGRESS,
            actor=actor,
            note="Marketing campaign created.",
        )
    return campaign


def record_marketing_activity(
    campaign,
    *,
    actor,
    occurred_on,
    title: str,
    description: str = "",
    outcome: str = "",
    file=None,
) -> MarketingActivity:
    require_staff_for_request(actor, campaign.enquiry.request)
    if campaign.status == MarketingCampaignStatus.CANCELLED:
        raise ValidationError("Cannot record activity on a cancelled campaign.")
    if campaign.status == MarketingCampaignStatus.PLANNED:
        campaign.status = MarketingCampaignStatus.ACTIVE
        campaign.save(update_fields=["status", "updated_at"])
    return MarketingActivity.objects.create(
        campaign=campaign,
        occurred_on=occurred_on,
        title=title[:180],
        description=description,
        outcome=outcome,
        file=file,
        recorded_by=actor,
    )


def complete_marketing_campaign(campaign, *, actor) -> MarketingCampaign:
    require_staff_for_request(actor, campaign.enquiry.request)
    campaign.status = MarketingCampaignStatus.COMPLETED
    campaign.save(update_fields=["status", "updated_at"])
    if campaign.enquiry.request.can_transition_to(ServiceRequestStatus.COMPLETED):
        _transition(
            campaign.enquiry.request,
            to_status=ServiceRequestStatus.COMPLETED,
            actor=actor,
            note="Marketing activity completed.",
        )
        notifications.service_completed(campaign.enquiry.request)
    return campaign


# ---------------------------------------------------------------------------
# Storage (Task 5)
# ---------------------------------------------------------------------------


def create_storage_facility(*, actor, name: str, **fields) -> StorageFacility:
    if not has_capability(actor, Capability.REQUESTS_STORAGE):
        raise PermissionDenied("You cannot manage storage facilities.")
    produce_types = fields.pop("accepted_produce_types", None)
    facility = StorageFacility.objects.create(name=name, **fields)
    if produce_types:
        facility.accepted_produce_types.set(produce_types)
    return facility


def create_storage_unit(*, actor, facility: StorageFacility, name: str, **fields) -> StorageUnit:
    if not has_capability(actor, Capability.REQUESTS_STORAGE):
        raise PermissionDenied("You cannot manage storage units.")
    return StorageUnit.objects.create(facility=facility, name=name, **fields)


def submit_storage_request(
    *,
    customer,
    produce_type: ProduceType | None = None,
    quantity=0,
    unit=None,
    preferred_facility: StorageFacility | None = None,
    preferred_location: str = "",
    requested_start_date=None,
    requested_end_date=None,
    special_handling: str = "",
    description: str = "",
) -> StorageServiceRequest:
    quantity = _as_decimal(quantity)
    if quantity <= 0:
        raise ValidationError("A positive quantity is required.")
    if requested_start_date and requested_end_date and requested_end_date <= requested_start_date:
        raise ValidationError("The end date must be after the start date.")
    with transaction.atomic():
        service_request = create_service_request(
            customer=customer,
            service_type=ServiceType.STORAGE,
            title=f"Storage request · {produce_type.name if produce_type else 'produce'}"[:160],
            description=description or special_handling,
            preferred_date=requested_start_date,
        )
        storage_request = StorageServiceRequest.objects.create(
            request=service_request,
            produce_type=produce_type,
            quantity=quantity,
            unit=unit,
            preferred_facility=preferred_facility,
            preferred_location=preferred_location[:240],
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            special_handling=special_handling,
        )
    return storage_request


def facility_used_capacity(facility, *, start, end, unit=None) -> Decimal:
    """Capacity currently allocated for an overlapping window (active only)."""
    query = StorageCapacityAllocation.objects.filter(
        facility=facility,
        released_at__isnull=True,
        start_date__lt=end,
        end_date__gt=start,
    )
    if unit is not None:
        query = query.filter(unit=unit)
    else:
        query = query.filter(unit__isnull=True)
    return query.aggregate(total=Sum("quantity"))["total"] or ZERO


def facility_available_capacity(facility, *, start, end, unit=None) -> Decimal:
    ceiling = _as_decimal(unit.capacity if unit is not None else facility.capacity)
    used = facility_used_capacity(facility, start=start, end=end, unit=unit)
    return max(ceiling - used, ZERO)


def create_storage_booking(
    storage_request,
    *,
    actor,
    facility: StorageFacility,
    start_date,
    end_date,
    unit: StorageUnit | None = None,
    quantity=None,
    quotation=None,
) -> StorageBooking:
    """Create a booking and reserve capacity transactionally (overbooking-safe)."""
    require_staff_for_request(actor, storage_request.request)
    if start_date is None or end_date is None or end_date <= start_date:
        raise ValidationError("Provide a valid start and end date.")
    quantity = _as_decimal(quantity if quantity is not None else storage_request.quantity)
    if quantity <= 0:
        raise ValidationError("A positive quantity is required.")
    if not facility.is_active:
        raise ValidationError("This facility is not active.")
    if unit is not None and unit.facility_id != facility.pk:
        raise ValidationError("The unit does not belong to the facility.")
    if not facility.accepts(storage_request.produce_type):
        raise ValidationError("This facility does not accept that produce type.")
    if hasattr(storage_request, "booking"):
        raise ValidationError("This storage request already has a booking.")

    with transaction.atomic():
        locked_facility = StorageFacility.objects.select_for_update().get(pk=facility.pk)
        available = facility_available_capacity(
            locked_facility, start=start_date, end=end_date, unit=unit
        )
        if quantity > available:
            raise ValidationError(f"Only {available} capacity is available for that window.")
        booking = StorageBooking.objects.create(
            request=storage_request,
            facility=locked_facility,
            unit=unit,
            quotation=quotation,
            produce_type=storage_request.produce_type,
            quantity=quantity,
            unit_of_measure=storage_request.unit,
            start_date=start_date,
            end_date=end_date,
            status=StorageBookingStatus.REQUESTED,
        )
        StorageCapacityAllocation.objects.create(
            booking=booking,
            facility=locked_facility,
            unit=unit,
            quantity=quantity,
            start_date=start_date,
            end_date=end_date,
        )
    _log(
        storage_request.request,
        actor=actor,
        action="storage.booking.created",
        detail=booking.reference,
    )
    return booking


@transaction.atomic
def confirm_storage_booking(booking, *, actor, require_payment: bool = True) -> StorageBooking:
    require_staff_for_request(actor, booking.request.request)
    booking = StorageBooking.objects.select_for_update().get(pk=booking.pk)
    if booking.status not in {StorageBookingStatus.REQUESTED}:
        raise ValidationError("This booking cannot be confirmed from its current status.")
    if require_payment and booking.quotation is not None and booking.quotation.total > 0:
        if booking.quotation.payment_status != QuotationPaymentStatus.PAID:
            raise ValidationError("Verified payment is required before confirmation.")
    # Ensure capacity is still held; re-validate under lock.
    locked_facility = StorageFacility.objects.select_for_update().get(pk=booking.facility_id)
    active = booking.allocations.filter(released_at__isnull=True).exists()
    if not active:
        available = facility_available_capacity(
            locked_facility, start=booking.start_date, end=booking.end_date, unit=booking.unit
        )
        if booking.quantity > available:
            raise ValidationError("Capacity is no longer available for this booking.")
        StorageCapacityAllocation.objects.create(
            booking=booking,
            facility=locked_facility,
            unit=booking.unit,
            quantity=booking.quantity,
            start_date=booking.start_date,
            end_date=booking.end_date,
        )
    booking.status = StorageBookingStatus.CONFIRMED
    booking.confirmed_by = actor
    booking.confirmed_at = timezone.now()
    booking.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
    _transition(
        booking.request.request,
        to_status=ServiceRequestStatus.CONFIRMED,
        actor=actor,
        note="Storage booking confirmed.",
    )
    notifications.storage_booking_confirmed(booking)
    notification_events.storage_booking_confirmed(booking)
    record_audit(actor=actor, action="services.storage.booking_confirmed", target=booking)
    return booking


@transaction.atomic
def cancel_storage_booking(booking, *, actor, reason: str = "") -> StorageBooking:
    booking = StorageBooking.objects.select_for_update().get(pk=booking.pk)
    if booking.status in {StorageBookingStatus.CHECKED_OUT, StorageBookingStatus.CANCELLED}:
        raise ValidationError("This booking is already closed.")
    booking.allocations.filter(released_at__isnull=True).update(released_at=timezone.now())
    booking.status = StorageBookingStatus.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancellation_reason = reason[:200]
    booking.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    if booking.request.request.status not in {
        ServiceRequestStatus.COMPLETED,
        ServiceRequestStatus.CANCELLED,
    }:
        _transition(
            booking.request.request,
            to_status=ServiceRequestStatus.CANCELLED,
            actor=actor,
            note=reason or "Storage booking cancelled.",
        )
    return booking


def storage_check_in(booking, *, actor, quantity, condition_notes: str = "") -> StorageCheckIn:
    require_staff_for_request(actor, booking.request.request)
    quantity = _as_decimal(quantity)
    if quantity <= 0:
        raise ValidationError("A positive quantity is required.")
    with transaction.atomic():
        booking = StorageBooking.objects.select_for_update().get(pk=booking.pk)
        if booking.status not in {
            StorageBookingStatus.CONFIRMED,
            StorageBookingStatus.CHECKED_IN,
        }:
            raise ValidationError("The booking must be confirmed before check-in.")
        already = _checked_in_total(booking)
        if already + quantity > booking.quantity:
            raise ValidationError("Check-in quantity exceeds the booked quantity.")
        check_in = StorageCheckIn.objects.create(
            booking=booking,
            quantity=quantity,
            condition_notes=condition_notes,
            recorded_by=actor,
        )
        if booking.status != StorageBookingStatus.CHECKED_IN:
            booking.status = StorageBookingStatus.CHECKED_IN
            booking.save(update_fields=["status", "updated_at"])
    return StorageCheckIn.objects.get(pk=check_in.pk)


def _checked_in_total(booking) -> Decimal:
    return booking.check_ins.aggregate(total=Sum("quantity"))["total"] or ZERO


def _checked_out_total(booking) -> Decimal:
    return booking.check_outs.aggregate(total=Sum("quantity"))["total"] or ZERO


@transaction.atomic
def storage_check_out(booking, *, actor, quantity, condition_notes: str = "") -> StorageCheckOut:
    require_staff_for_request(actor, booking.request.request)
    booking = StorageBooking.objects.select_for_update().get(pk=booking.pk)
    if booking.status not in {
        StorageBookingStatus.CHECKED_IN,
        StorageBookingStatus.CHECKED_OUT,
    }:
        raise ValidationError("Only checked-in produce can be checked out.")
    quantity = _as_decimal(quantity)
    if quantity <= 0:
        raise ValidationError("A positive quantity is required.")
    outstanding = _checked_in_total(booking) - _checked_out_total(booking)
    if quantity > outstanding:
        raise ValidationError("You cannot release more produce than is in storage.")
    checkout = StorageCheckOut.objects.create(
        booking=booking,
        quantity=quantity,
        condition_notes=condition_notes,
        recorded_by=actor,
    )
    remaining = outstanding - quantity
    if remaining <= 0:
        booking.allocations.filter(released_at__isnull=True).update(released_at=timezone.now())
        booking.status = StorageBookingStatus.CHECKED_OUT
        booking.save(update_fields=["status", "updated_at"])
        if booking.request.request.status not in {
            ServiceRequestStatus.COMPLETED,
            ServiceRequestStatus.CANCELLED,
        }:
            _transition(
                booking.request.request,
                to_status=ServiceRequestStatus.COMPLETED,
                actor=actor,
                note="Produce released.",
            )
            notifications.service_completed(booking.request.request)
    record_audit(actor=actor, action="services.storage.check_out", target=booking)
    return checkout


def record_storage_inspection(
    facility,
    *,
    actor,
    condition: str = InspectionCondition.GOOD,
    findings: str = "",
    booking=None,
    file=None,
) -> StorageInspection:
    if not has_capability(actor, Capability.REQUESTS_STORAGE):
        raise PermissionDenied("You cannot record inspections.")
    if condition not in InspectionCondition.values:
        raise ValidationError("Unknown condition.")
    return StorageInspection.objects.create(
        facility=facility,
        booking=booking,
        inspected_by=actor,
        condition=condition,
        findings=findings,
        file=file,
    )


# ---------------------------------------------------------------------------
# Quotations (Task 6)
# ---------------------------------------------------------------------------


def _make_quotation_items(quotation, items) -> None:
    if not items:
        raise ValidationError("A quotation needs at least one line item.")
    for index, item in enumerate(items):
        description = str(item.get("description") or "").strip()
        if not description:
            raise ValidationError("Each line item needs a description.")
        quantity = _as_decimal(item.get("quantity", 1), field="quantity")
        unit_price = _money(item.get("unit_price", 0))
        if quantity <= 0:
            raise ValidationError("Line item quantities must be positive.")
        if unit_price < 0:
            raise ValidationError("Line item prices cannot be negative.")
        line_total = (quantity * unit_price).quantize(Decimal("0.01"))
        ServiceQuotationItem.objects.create(
            quotation=quotation,
            description=description[:200],
            quantity=quantity,
            unit=item.get("unit"),
            unit_price=unit_price,
            line_total=line_total,
            sort_order=item.get("sort_order", index),
        )


def create_quotation(
    *,
    actor,
    customer,
    items,
    service_request: ServiceRequest | None = None,
    currency: str = "NGN",
    valid_until=None,
    terms: str = "",
) -> ServiceQuotation:
    """Create a draft quotation; totals are always recomputed from the items."""
    if service_request is not None:
        require_staff_for_request(actor, service_request)
        if service_request.customer_id != getattr(customer, "id", None):
            raise ValidationError("The quotation customer must own the request.")
    with transaction.atomic():
        quotation = ServiceQuotation.objects.create(
            customer=customer,
            request=service_request,
            currency=currency,
            valid_until=valid_until,
            terms=terms,
            status=QuotationStatus.DRAFT,
        )
        _make_quotation_items(quotation, items)
        quotation.recompute_totals()
        quotation.save(update_fields=["subtotal", "tax_amount", "total", "updated_at"])
    if service_request is not None:
        _log(service_request, actor=actor, action="quotation.created", detail=quotation.reference)
    return quotation


def update_quotation(
    quotation, *, actor, items=None, valid_until=None, terms=None
) -> ServiceQuotation:
    if quotation.status not in {QuotationStatus.DRAFT, QuotationStatus.PENDING_APPROVAL}:
        raise ValidationError("Only draft quotations can be edited.")
    with transaction.atomic():
        quotation = ServiceQuotation.objects.select_for_update().get(pk=quotation.pk)
        if items is not None:
            quotation.items.all().delete()
            _make_quotation_items(quotation, items)
        if valid_until is not None:
            quotation.valid_until = valid_until
        if terms is not None:
            quotation.terms = terms
        quotation.recompute_totals()
        quotation.save(
            update_fields=["subtotal", "tax_amount", "total", "valid_until", "terms", "updated_at"]
        )
    return quotation


def submit_quotation_for_approval(quotation, *, actor) -> ServiceQuotation:
    require_staff_for_request(actor, quotation.request) if quotation.request else None
    if quotation.status != QuotationStatus.DRAFT:
        raise ValidationError("Only a draft quotation can be submitted for approval.")
    quotation.status = QuotationStatus.PENDING_APPROVAL
    quotation.save(update_fields=["status", "updated_at"])
    return quotation


def approve_quotation(quotation, *, actor) -> ServiceQuotation:
    """Internal approval step (requires the quotations capability)."""
    if not has_capability(actor, Capability.QUOTATIONS_MANAGE):
        raise PermissionDenied("You are not authorised to approve quotations.")
    if quotation.status != QuotationStatus.PENDING_APPROVAL:
        raise ValidationError("Only a quotation pending approval can be approved.")
    quotation.approved_by = actor
    quotation.approved_at = timezone.now()
    quotation.save(update_fields=["approved_by", "approved_at", "updated_at"])
    record_audit(actor=actor, action="services.quotation.approved", target=quotation)
    return quotation


def issue_quotation(quotation, *, actor) -> ServiceQuotation:
    if not has_capability(actor, Capability.QUOTATIONS_MANAGE):
        raise PermissionDenied("You are not authorised to issue quotations.")
    if quotation.status not in {QuotationStatus.PENDING_APPROVAL, QuotationStatus.DRAFT}:
        raise ValidationError("This quotation cannot be issued from its current status.")
    if quotation.approved_at is None:
        raise ValidationError("The quotation must be approved before it is issued.")
    quotation.status = QuotationStatus.ISSUED
    quotation.issued_by = actor
    quotation.issued_at = timezone.now()
    quotation.save(update_fields=["status", "issued_by", "issued_at", "updated_at"])
    if quotation.request is not None:
        if quotation.request.status in {
            ServiceRequestStatus.SUBMITTED,
            ServiceRequestStatus.UNDER_REVIEW,
        }:
            _transition(
                quotation.request,
                to_status=ServiceRequestStatus.QUOTED,
                actor=actor,
                note=f"Quotation {quotation.reference} issued.",
            )
        _log(quotation.request, actor=actor, action="quotation.issued", detail=quotation.reference)
    notifications.quotation_issued(quotation)
    record_audit(actor=actor, action="services.quotation.issued", target=quotation)
    return quotation


def activate_paid_service(quotation) -> None:
    """Activate the downstream service once a quotation is accepted/paid.

    Called after a *verified* payment settles (or immediately for a zero-total
    quotation). A paid-only service is never activated before the payment is
    verified — the Phase 6 pipeline calls this only after verification.
    """
    service_request = quotation.request
    if service_request is None:
        return
    if service_request.service_type == ServiceType.STORAGE:
        storage_request = getattr(service_request, "storage_request", None)
        booking = getattr(storage_request, "booking", None) if storage_request else None
        if booking is not None and booking.status == StorageBookingStatus.REQUESTED:
            confirm_storage_booking(booking, actor=None, require_payment=False)
    elif service_request.service_type == ServiceType.FARMING:
        farm_request = getattr(service_request, "farm_request", None)
        project = getattr(farm_request, "project", None) if farm_request else None
        if project is not None and project.status == FarmProjectStatus.APPROVED:
            try:
                activate_farm_project(project, actor=None)
            except ValidationError:
                # Missing agreement/approval — staff must complete it manually.
                pass
    # Consultancy appointments and marketing campaigns stay explicit staff
    # actions; a verified payment does not silently confirm them.


def accept_quotation(quotation, *, actor, note: str = "") -> ServiceQuotation:
    if getattr(actor, "id", None) != quotation.customer_id:
        raise PermissionDenied("Only the customer can accept this quotation.")
    if not quotation.can_be_accepted:
        raise ValidationError("This quotation is not open for acceptance.")
    with transaction.atomic():
        quotation = ServiceQuotation.objects.select_for_update().get(pk=quotation.pk)
        quotation.status = QuotationStatus.ACCEPTED
        quotation.decided_at = timezone.now()
        quotation.decision_note = note[:200]
        quotation.save(update_fields=["status", "decided_at", "decision_note", "updated_at"])
        if quotation.request is not None:
            _transition(
                quotation.request,
                to_status=ServiceRequestStatus.CONFIRMED,
                actor=actor,
                note="Quotation accepted.",
            )
    notifications.quotation_accepted(quotation)
    # A free service can proceed immediately; paid services wait for settlement.
    if quotation.total <= 0:
        activate_paid_service(quotation)
    return quotation


def reject_quotation(quotation, *, actor, note: str = "") -> ServiceQuotation:
    if getattr(actor, "id", None) != quotation.customer_id:
        raise PermissionDenied("Only the customer can reject this quotation.")
    if quotation.status != QuotationStatus.ISSUED:
        raise ValidationError("Only an issued quotation can be rejected.")
    quotation.status = QuotationStatus.REJECTED
    quotation.decided_at = timezone.now()
    quotation.decision_note = note[:200]
    quotation.save(update_fields=["status", "decided_at", "decision_note", "updated_at"])
    if quotation.request is not None:
        _transition(
            quotation.request,
            to_status=ServiceRequestStatus.REJECTED,
            actor=actor,
            note="Quotation rejected.",
        )
    return quotation


def expire_quotation(quotation) -> ServiceQuotation:
    if quotation.status == QuotationStatus.ISSUED and quotation.valid_until:
        if quotation.valid_until < timezone.localdate():
            quotation.status = QuotationStatus.EXPIRED
            quotation.save(update_fields=["status", "updated_at"])
    return quotation


def expire_due_quotations() -> int:
    """Mark every lapsed issued quotation as expired (scheduled task)."""
    today = timezone.localdate()
    return ServiceQuotation.objects.filter(
        status=QuotationStatus.ISSUED, valid_until__lt=today
    ).update(status=QuotationStatus.EXPIRED, updated_at=timezone.now())


def revise_quotation(quotation, *, actor) -> ServiceQuotation:
    """Create a new draft revision superseding ``quotation``."""
    if not has_capability(actor, Capability.QUOTATIONS_MANAGE):
        raise PermissionDenied("You are not authorised to revise quotations.")
    if quotation.status not in {
        QuotationStatus.ISSUED,
        QuotationStatus.REJECTED,
        QuotationStatus.EXPIRED,
    }:
        raise ValidationError("Only an issued, rejected or expired quotation can be revised.")
    with transaction.atomic():
        revision = ServiceQuotation.objects.create(
            customer=quotation.customer,
            request=quotation.request,
            currency=quotation.currency,
            valid_until=quotation.valid_until,
            terms=quotation.terms,
            status=QuotationStatus.DRAFT,
            revision=quotation.revision + 1,
            supersedes=quotation,
        )
        for item in quotation.items.all():
            ServiceQuotationItem.objects.create(
                quotation=revision,
                description=item.description,
                quantity=item.quantity,
                unit=item.unit,
                unit_price=item.unit_price,
                line_total=item.line_total,
                sort_order=item.sort_order,
            )
        revision.recompute_totals()
        revision.save(update_fields=["subtotal", "tax_amount", "total", "updated_at"])
    return revision


__all__ = [
    "accept_quotation",
    "activate_paid_service",
    "activate_farm_project",
    "add_attachment",
    "add_comment",
    "add_farm_milestone",
    "add_farm_progress_report",
    "approve_farm_project",
    "approve_quotation",
    "book_consultation",
    "cancel_storage_booking",
    "complete_appointment",
    "complete_farm_project",
    "complete_marketing_campaign",
    "confirm_appointment",
    "confirm_storage_booking",
    "create_consultancy_service",
    "create_consultant",
    "create_farm_project",
    "create_farming_service",
    "create_marketing_campaign",
    "create_marketing_proposal",
    "create_marketing_service",
    "create_quotation",
    "create_service_request",
    "create_storage_booking",
    "create_storage_facility",
    "create_storage_unit",
    "expire_due_quotations",
    "facility_available_capacity",
    "facility_used_capacity",
    "issue_quotation",
    "reject_appointment",
    "reject_quotation",
    "record_consultation_report",
    "record_marketing_activity",
    "record_storage_inspection",
    "reschedule_appointment",
    "review_service_request",
    "revise_quotation",
    "set_consultant_availability",
    "storage_check_in",
    "storage_check_out",
    "submit_farm_service_request",
    "submit_marketing_enquiry",
    "submit_quotation_for_approval",
    "submit_storage_request",
    "update_farm_milestone",
    "update_quotation",
]

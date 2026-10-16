"""Staff dashboard views for the service divisions (``/dashboard/services/``).

Every view enforces a capability server-side (``SERVICES_MANAGE`` for the
division screens, ``QUOTATIONS_MANAGE`` for quotation approval/issue). Writes go
through :mod:`apps.services.services` so they are validated, transactional and
audited.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability

from . import selectors, services
from .forms import (
    FarmMilestoneForm,
    FarmProgressReportForm,
    FarmProjectForm,
    MarketingCampaignForm,
    MarketingProposalForm,
    StorageBookingForm,
    StorageCheckForm,
    StorageFacilityForm,
    StorageUnitForm,
)
from .models import (
    Consultant,
    ConsultationAppointment,
    FarmProject,
    FarmServiceRequest,
    MarketingEnquiry,
    MarketingProposal,
    QuotationStatus,
    ServiceQuotation,
    ServiceRequest,
    ServiceRequestStatus,
    ServiceType,
    StorageBooking,
    StorageServiceRequest,
)


def _errors(exc) -> str:
    return "; ".join(getattr(exc, "messages", [str(exc)]))


def services_required(view):
    """Require authentication and the ``SERVICES_MANAGE`` capability."""

    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        if not has_capability(request.user, Capability.SERVICES_MANAGE):
            raise PermissionDenied("You do not have permission to manage services.")
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def _base_context(request, **extra):
    context = {
        "active_nav": "services",
        "breadcrumbs": [
            {"label": "Dashboard", "url": "dashboard:home"},
            {"label": "Services", "url": "services_dashboard:home"},
        ],
    }
    context.update(extra)
    return context


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@services_required
def dashboard_home(request):
    days = 30
    metrics = selectors.service_overview_metrics(days=days)
    by_division = [
        {
            "label": ServiceType(row["service_type"]).label
            if row["service_type"] in ServiceType.values
            else row["service_type"],
            "total": row["total"],
        }
        for row in metrics["by_division"]
    ]
    return render(
        request,
        "dashboard/services/home.html",
        _base_context(
            request,
            page_title="Services",
            metrics=selectors.service_overview_metrics(),
            division_chart=by_division,
            recent_requests=selectors.staff_service_requests()[:8],
            pending_quotations=selectors.staff_quotations(status="pending_approval")[:5],
            active_projects=selectors.staff_farm_projects(status="active")[:5],
            service_types=ServiceType.choices,
        ),
    )


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


@services_required
def request_list(request):
    service_type = request.GET.get("type", "")
    status = request.GET.get("status", "")
    query = request.GET.get("q", "")
    return render(
        request,
        "dashboard/services/request_list.html",
        {
            "page_title": "Service requests",
            "requests": selectors.staff_service_requests(
                service_type=service_type, status=status, query=query
            ),
            "service_type": service_type,
            "status": status,
            "query": query,
            "service_types": ServiceType.choices,
            "statuses": ServiceRequestStatus.choices,
        },
    )


@services_required
def request_detail(request, reference):
    service_request = get_object_or_404(
        ServiceRequest.objects.select_related("customer", "assigned_to"), reference=reference
    )
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "review":
                services.review_service_request(
                    service_request,
                    actor=request.user,
                    note=request.POST.get("note", ""),
                    priority=request.POST.get("priority") or None,
                )
                messages.success(request, "Request reviewed.")
            elif action == "assign":
                staff = get_user_model().objects.filter(pk=request.POST.get("staff")).first()
                if staff is None:
                    raise ValidationError("Select a staff member to assign.")
                services.assign_staff(
                    service_request,
                    staff=staff,
                    actor=request.user,
                    role=request.POST.get("role", ""),
                    note=request.POST.get("note", ""),
                )
                messages.success(request, "Staff assigned.")
            elif action == "comment":
                services.add_comment(
                    service_request,
                    author=request.user,
                    body=request.POST.get("body", ""),
                    visibility=request.POST.get("visibility", "internal"),
                )
                messages.success(request, "Comment added.")
            elif action == "attachment":
                services.add_attachment(
                    service_request,
                    uploaded_by=request.user,
                    file=request.FILES.get("file"),
                    label=request.POST.get("label", ""),
                    is_customer_visible=request.POST.get("is_customer_visible") == "on",
                )
                messages.success(request, "Attachment uploaded.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        return redirect("services_dashboard:request_detail", reference=reference)

    return render(
        request,
        "dashboard/services/request_detail.html",
        {
            "page_title": service_request.title,
            "request_obj": service_request,
            "timeline": selectors.request_status_timeline(service_request),
            "consultants": selectors.staff_consultants(),
            "staff_users": get_user_model().objects.filter(is_staff=True).order_by("email"),
            "service_types": ServiceType.choices,
            "quotation_form": None,
        },
    )


@services_required
def request_review(request, reference):
    service_request = get_object_or_404(ServiceRequest, reference=reference)
    try:
        services.review_service_request(
            service_request,
            actor=request.user,
            note=request.POST.get("note", ""),
            priority=request.POST.get("priority") or None,
        )
        messages.success(request, "Request reviewed.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    return redirect("services:request_detail", reference=reference)


# ---------------------------------------------------------------------------
# Consultancy
# ---------------------------------------------------------------------------


@services_required
def appointment_confirm(request, pk):
    appointment = get_object_or_404(ConsultationAppointment, pk=pk)
    reference = appointment.request.reference
    if request.method != "POST":
        return redirect(
            "services_dashboard:request_detail", reference=appointment.request.reference
        )
    consultant = appointment.consultant
    consultant_id = request.POST.get("consultant")
    if consultant_id:
        consultant = get_object_or_404(Consultant, pk=consultant_id)
    try:
        services.confirm_appointment(
            appointment,
            actor=request.user,
            consultant=consultant,
            start=appointment.scheduled_start,
            end=appointment.scheduled_end,
        )
        messages.success(request, "Appointment confirmed.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    return redirect("services_dashboard:request_detail", reference=reference)


@services_required
def appointment_complete(request, pk):
    appointment = get_object_or_404(ConsultationAppointment, pk=pk)
    if request.method == "POST":
        try:
            services.complete_appointment(
                appointment, actor=request.user, summary=request.POST.get("summary", "")
            )
            messages.success(request, "Appointment completed.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
    return redirect("services_dashboard:request_detail", reference=appointment.request.reference)


# ---------------------------------------------------------------------------
# Farming
# ---------------------------------------------------------------------------


@services_required
def farm_project_list(request):
    status = request.GET.get("status", "")
    return render(
        request,
        "dashboard/services/farm_project_list.html",
        {
            "page_title": "Farm projects",
            "projects": selectors.staff_farm_projects(status=status),
            "status": status,
        },
    )


@services_required
def farm_project_create(request, pk):
    farm_request = get_object_or_404(FarmServiceRequest, pk=pk)
    if request.method == "POST":
        form = FarmProjectForm(request.POST)
        if form.is_valid():
            try:
                project = services.create_farm_project(
                    farm_request,
                    actor=request.user,
                    name=form.cleaned_data["name"],
                    manager=form.cleaned_data.get("manager"),
                    start_date=form.cleaned_data.get("start_date"),
                    end_date=form.cleaned_data.get("end_date"),
                    notes=form.cleaned_data.get("notes", ""),
                )
                messages.success(request, "Project created. Approve and record the agreement.")
                return redirect("services_dashboard:farm_project_detail", pk=project.pk)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _errors(exc))
    else:
        form = FarmProjectForm(initial={"name": farm_request.request.title})
    return render(
        request,
        "dashboard/services/farm_project_form.html",
        {"page_title": "New farm project", "form": form, "farm_request": farm_request},
    )


@services_required
def farm_project_detail(request, pk):
    project = get_object_or_404(
        FarmProject.objects.select_related("request__request__customer", "manager"), pk=pk
    )
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "approve":
                services.approve_farm_project(
                    project,
                    actor=request.user,
                    agreement_reference=request.POST.get("agreement_reference", ""),
                )
                messages.success(request, "Project approved.")
            elif action == "activate":
                services.activate_farm_project(project, actor=request.user)
                messages.success(request, "Project activated.")
            elif action == "milestone":
                services.add_farm_milestone(
                    project,
                    actor=request.user,
                    title=request.POST.get("title", ""),
                    description=request.POST.get("description", ""),
                    due_date=request.POST.get("due_date") or None,
                )
                messages.success(request, "Milestone added.")
            elif action == "progress":
                services.add_farm_progress_report(
                    project,
                    actor=request.user,
                    title=request.POST.get("title", ""),
                    summary=request.POST.get("summary", ""),
                    progress_percent=int(request.POST.get("progress_percent") or 0),
                )
                messages.success(request, "Progress report recorded.")
        except (ValidationError, PermissionDenied, ValueError) as exc:
            messages.error(request, _errors(exc) if hasattr(exc, "messages") else str(exc))
        return redirect("services_dashboard:farm_project_detail", pk=pk)
    return render(
        request,
        "dashboard/services/farm_project_detail.html",
        {
            "page_title": project.name,
            "project": project,
            "milestone_form": FarmMilestoneForm(),
            "progress_form": FarmProgressReportForm(project=project),
        },
    )


# ---------------------------------------------------------------------------
# Marketing
# ---------------------------------------------------------------------------


@services_required
def marketing_list(request):
    query = request.GET.get("q", "")
    return render(
        request,
        "dashboard/services/marketing_list.html",
        {
            "page_title": "Marketing enquiries",
            "enquiries": selectors.staff_marketing_enquiries(query=query),
            "query": query,
        },
    )


@services_required
def marketing_enquiry_detail(request, pk):
    enquiry = get_object_or_404(MarketingEnquiry.objects.select_related("request__customer"), pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "proposal":
                form = MarketingProposalForm(request.POST)
                if form.is_valid():
                    services.create_marketing_proposal(
                        enquiry,
                        actor=request.user,
                        title=form.cleaned_data["title"],
                        scope=form.cleaned_data.get("scope", ""),
                        approach=form.cleaned_data.get("approach", ""),
                    )
                    messages.success(request, "Proposal drafted.")
            elif action == "issue":
                proposal = get_object_or_404(
                    MarketingProposal, pk=request.POST.get("proposal_id"), enquiry=enquiry
                )
                services.issue_marketing_proposal(proposal, actor=request.user)
                messages.success(request, "Proposal issued.")
            elif action == "campaign":
                form = MarketingCampaignForm(request.POST)
                if form.is_valid():
                    services.create_marketing_campaign(
                        enquiry,
                        actor=request.user,
                        name=form.cleaned_data["name"],
                        officer=form.cleaned_data.get("officer"),
                        start_date=form.cleaned_data.get("start_date"),
                        end_date=form.cleaned_data.get("end_date"),
                        targets=form.cleaned_data.get("targets", ""),
                    )
                    messages.success(request, "Campaign created.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        return redirect("services_dashboard:marketing_enquiry_detail", pk=pk)
    return render(
        request,
        "dashboard/services/marketing_enquiry_detail.html",
        {
            "page_title": f"Marketing · {enquiry.product_type}",
            "enquiry": enquiry,
            "proposal_form": MarketingProposalForm(),
            "campaign_form": MarketingCampaignForm(),
        },
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


@services_required
def facility_list(request):
    return render(
        request,
        "dashboard/services/facility_list.html",
        {
            "page_title": "Storage facilities",
            "facilities": selectors.staff_storage_facilities(active_only=False),
        },
    )


@services_required
def facility_create(request):
    if request.method == "POST":
        form = StorageFacilityForm(request.POST)
        if form.is_valid():
            try:
                facility = services.create_storage_facility(
                    actor=request.user,
                    name=form.cleaned_data["name"],
                    location=form.cleaned_data.get("location", ""),
                    state=form.cleaned_data.get("state"),
                    lga=form.cleaned_data.get("lga"),
                    capacity=form.cleaned_data.get("capacity") or Decimal("0"),
                    capacity_unit=form.cleaned_data["capacity_unit"],
                    storage_conditions=form.cleaned_data.get("storage_conditions", ""),
                    is_active=form.cleaned_data.get("is_active", True),
                    notes=form.cleaned_data.get("notes", ""),
                    accepted_produce_types=form.cleaned_data.get("accepted_produce_types"),
                )
                messages.success(request, "Facility created.")
                return redirect("services_dashboard:facility_detail", pk=facility.pk)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _errors(exc))
    else:
        form = StorageFacilityForm()
    return render(
        request,
        "dashboard/services/facility_form.html",
        {"page_title": "New storage facility", "form": form},
    )


@services_required
def facility_detail(request, pk):
    from .models import StorageFacility

    facility = get_object_or_404(StorageFacility, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "unit":
                form = StorageUnitForm(request.POST)
                if form.is_valid():
                    services.create_storage_unit(
                        actor=request.user,
                        facility=facility,
                        name=form.cleaned_data["name"],
                        capacity=form.cleaned_data["capacity"],
                        capacity_unit=form.cleaned_data["capacity_unit"],
                        storage_conditions=form.cleaned_data.get("storage_conditions", ""),
                        is_active=form.cleaned_data.get("is_active", True),
                    )
                    messages.success(request, "Unit added.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        return redirect("services_dashboard:facility_detail", pk=pk)
    return render(
        request,
        "dashboard/services/facility_detail.html",
        {
            "page_title": facility.name,
            "facility": facility,
            "unit_form": StorageUnitForm(),
            "utilization": selectors.facility_utilization(facility),
        },
    )


@services_required
def booking_list(request):
    status = request.GET.get("status", "")
    return render(
        request,
        "dashboard/services/booking_list.html",
        {
            "page_title": "Storage bookings",
            "bookings": selectors.staff_storage_bookings(status=status),
            "status": status,
        },
    )


@services_required
def booking_create(request, pk):
    storage_request = get_object_or_404(StorageServiceRequest, pk=pk)
    if request.method == "POST":
        form = StorageBookingForm(request.POST, storage_request=storage_request)
        if form.is_valid():
            try:
                booking = services.create_storage_booking(
                    storage_request,
                    actor=request.user,
                    facility=form.cleaned_data["facility"],
                    unit=form.cleaned_data.get("unit"),
                    start_date=form.cleaned_data["start_date"],
                    end_date=form.cleaned_data["end_date"],
                    quantity=form.cleaned_data["quantity"],
                )
                messages.success(request, "Booking reserved.")
                return redirect("services_dashboard:booking_detail", pk=booking.pk)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _errors(exc))
    else:
        form = StorageBookingForm(storage_request=storage_request)
    return render(
        request,
        "dashboard/services/booking_form.html",
        {"page_title": "New storage booking", "form": form, "storage_request": storage_request},
    )


@services_required
def booking_detail(request, pk):
    booking = get_object_or_404(
        StorageBooking.objects.select_related("facility", "unit", "request__request__customer"),
        pk=pk,
    )
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "confirm":
                services.confirm_storage_booking(booking, actor=request.user)
                messages.success(request, "Booking confirmed.")
            elif action == "cancel":
                services.cancel_storage_booking(
                    booking, actor=request.user, reason=request.POST.get("reason", "")
                )
                messages.success(request, "Booking cancelled.")
            elif action == "check_in":
                services.storage_check_in(
                    booking,
                    actor=request.user,
                    quantity=Decimal(request.POST.get("quantity") or "0"),
                    condition_notes=request.POST.get("condition_notes", ""),
                )
                messages.success(request, "Check-in recorded.")
            elif action == "check_out":
                services.storage_check_out(
                    booking,
                    actor=request.user,
                    quantity=Decimal(request.POST.get("quantity") or "0"),
                    condition_notes=request.POST.get("condition_notes", ""),
                )
                messages.success(request, "Check-out recorded.")
        except (ValidationError, PermissionDenied, InvalidOperation) as exc:
            messages.error(request, _errors(exc) if hasattr(exc, "messages") else str(exc))
        return redirect("services_dashboard:booking_detail", pk=pk)
    return render(
        request,
        "dashboard/services/booking_detail.html",
        {
            "page_title": booking.reference,
            "booking": booking,
            "check_form": StorageCheckForm(),
        },
    )


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------


def _quotation_items_from_post(request):
    descriptions = request.POST.getlist("item_description")
    quantities = request.POST.getlist("item_quantity")
    prices = request.POST.getlist("item_unit_price")
    items = []
    for description, quantity, price in zip(descriptions, quantities, prices, strict=False):
        if not description.strip():
            continue
        items.append(
            {
                "description": description,
                "quantity": quantity or "1",
                "unit_price": price or "0",
            }
        )
    return items


@services_required
def quotation_list(request):
    status = request.GET.get("status", "")
    query = request.GET.get("q", "")
    return render(
        request,
        "dashboard/services/quotation_list.html",
        {
            "page_title": "Service quotations",
            "quotations": selectors.staff_quotations(status=status, query=query),
            "status": status,
            "query": query,
            "statuses": QuotationStatus.choices,
        },
    )


@services_required
def quotation_create(request, reference):
    service_request = get_object_or_404(ServiceRequest, reference=reference)
    require_approval = has_capability(request.user, Capability.QUOTATIONS_MANAGE)
    if request.method == "POST":
        items = _quotation_items_from_post(request)
        try:
            quotation = services.create_quotation(
                actor=request.user,
                customer=service_request.customer,
                items=items,
                service_request=service_request,
                valid_until=request.POST.get("valid_until") or None,
                terms=request.POST.get("terms", ""),
            )
            messages.success(request, f"Quotation {quotation.reference} created.")
            return redirect("services_dashboard:quotation_detail", pk=quotation.pk)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
    return render(
        request,
        "dashboard/services/quotation_form.html",
        {
            "page_title": "New quotation",
            "service_request": service_request,
            "can_approve": require_approval,
        },
    )


@services_required
def quotation_detail(request, pk):
    quotation = get_object_or_404(
        ServiceQuotation.objects.select_related("customer", "request").prefetch_related("items"),
        pk=pk,
    )
    can_approve = has_capability(request.user, Capability.QUOTATIONS_MANAGE)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "submit":
                services.submit_quotation_for_approval(quotation, actor=request.user)
                messages.success(request, "Submitted for approval.")
            elif action == "approve":
                services.approve_quotation(quotation, actor=request.user)
                messages.success(request, "Quotation approved.")
            elif action == "issue":
                services.issue_quotation(quotation, actor=request.user)
                messages.success(request, "Quotation issued to the customer.")
            elif action == "revise":
                new_quotation = services.revise_quotation(quotation, actor=request.user)
                messages.success(request, f"Revision {new_quotation.reference} created.")
                return redirect("services_dashboard:quotation_detail", pk=new_quotation.pk)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        return redirect("services_dashboard:quotation_detail", pk=pk)
    return render(
        request,
        "dashboard/services/quotation_detail.html",
        {
            "page_title": quotation.reference,
            "quotation": quotation,
            "can_approve": can_approve,
        },
    )

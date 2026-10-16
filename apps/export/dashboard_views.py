"""Staff dashboard views for export management (``/dashboard/export/``).

Every view enforces a capability server-side. ``EXPORT_MANAGE`` (or
``EXPORT_APPROVE``) unlocks operational screens; approval actions (destination
activation, quotation approval, compliance sign-off) require ``EXPORT_APPROVE``.
Writes go through :mod:`apps.export.services` so they are validated,
transactional and audited.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability
from apps.catalog.models import Product

from . import selectors, services
from .forms import (
    AssignmentForm,
    ComplianceApprovalForm,
    ComplianceItemForm,
    DestinationForm,
    DestinationRequirementForm,
    DocumentForm,
    DocumentRequirementForm,
    DocumentReviewForm,
    EnquiryNoteForm,
    ExportProductProfileForm,
    LogisticsProviderForm,
    QuotationForm,
    QuotationItemFormSet,
    ReviseQuotationForm,
    ShipmentForm,
    ShipmentStatusForm,
    TradeRestrictionForm,
)
from .models import (
    ComplianceChecklistStatus,
    ComplianceItemStatus,
    ExportComplianceChecklist,
    ExportDestination,
    ExportDocument,
    ExportEnquiry,
    ExportEnquiryStatus,
    ExportOrder,
    ExportOrderStatus,
    ExportQuotation,
    ExportShipment,
    LogisticsProvider,
    ShipmentStatus,
)


def _errors(exc) -> str:
    return "; ".join(getattr(exc, "messages", [str(exc)]))


def export_staff_required(view):
    """Require authentication plus ``EXPORT_MANAGE`` or ``EXPORT_APPROVE``."""

    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not has_capability(
            request.user, Capability.EXPORT_MANAGE, Capability.EXPORT_APPROVE, any_of=True
        ):
            raise PermissionDenied("You do not have permission to manage exports.")
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def export_approve_required(view):
    """Require the ``EXPORT_APPROVE`` capability."""

    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not has_capability(request.user, Capability.EXPORT_APPROVE):
            raise PermissionDenied("You do not have permission to approve exports.")
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def _base_context(request, **extra):
    context = {
        "active_nav": "export",
        "breadcrumbs": [
            {"label": "Dashboard", "url": "dashboard:home"},
            {"label": "Export", "url": "export_dashboard:home"},
        ],
    }
    context.update(extra)
    return context


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@export_staff_required
def dashboard_home(request):
    context = _base_context(
        request,
        page_title="Export overview",
        metrics=selectors.overview_metrics(),
        recent_enquiries=selectors.staff_enquiries()[:6],
        recent_orders=selectors.staff_orders()[:6],
        pending_compliance=selectors.compliance_queues(status="pending")[:6],
        recent_shipments=selectors.shipments_queue()[:6],
    )
    return render(request, "dashboard/export/home.html", context)


# ---------------------------------------------------------------------------
# Task 1 — destinations
# ---------------------------------------------------------------------------


@export_staff_required
def destination_list(request):
    q = request.GET.get("q", "").strip()
    qs = ExportDestination.objects.select_related("country").order_by("country__name")
    if q:
        qs = qs.filter(country__name__icontains=q)
    return render(
        request,
        "dashboard/export/destination_list.html",
        _base_context(request, destinations=qs, q=q),
    )


@export_staff_required
def destination_create(request):
    if request.method == "POST":
        form = DestinationForm(request.POST)
        if form.is_valid():
            try:
                destination = services.upsert_destination(
                    country=form.cleaned_data.pop("country"),
                    actor=request.user,
                    **form.cleaned_data,
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _errors(exc))
            else:
                messages.success(request, "Destination saved. Approve it before activation.")
                return redirect("export_dashboard:destination_detail", pk=destination.pk)
    else:
        form = DestinationForm()
    return render(
        request, "dashboard/export/destination_form.html", _base_context(request, form=form)
    )


@export_staff_required
def destination_detail(request, pk):
    destination = get_object_or_404(
        ExportDestination.objects.select_related("country", "approved_by"), pk=pk
    )
    return render(
        request,
        "dashboard/export/destination_detail.html",
        _base_context(
            request,
            destination=destination,
            requirements=destination.requirements.select_related("document_type"),
            restrictions=destination.restrictions.select_related("product", "category"),
            document_requirements=destination.document_requirements.select_related("document_type"),
            requirement_form=DestinationRequirementForm(),
            restriction_form=TradeRestrictionForm(),
            document_requirement_form=DocumentRequirementForm(),
        ),
    )


@export_approve_required
@require_POST
def destination_approve(request, pk):
    destination = get_object_or_404(ExportDestination, pk=pk)
    try:
        services.approve_destination(destination, actor=request.user)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Destination approved.")
    return redirect("export_dashboard:destination_detail", pk=pk)


@export_approve_required
@require_POST
def destination_toggle_active(request, pk):
    destination = get_object_or_404(ExportDestination, pk=pk)
    try:
        services.set_destination_active(
            destination, actor=request.user, active=not destination.is_active
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    else:
        state = "activated" if destination.is_active else "deactivated"
        messages.success(request, f"Destination {state}.")
    return redirect("export_dashboard:destination_detail", pk=pk)


@export_staff_required
def requirement_create(request, pk):
    destination = get_object_or_404(ExportDestination, pk=pk)
    form = DestinationRequirementForm(request.POST)
    if form.is_valid():
        data = dict(form.cleaned_data)
        try:
            services.add_destination_requirement(
                destination, actor=request.user, title=data.pop("title"), **data
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Requirement added.")
    else:
        messages.error(request, "Please correct the requirement form.")
    return redirect("export_dashboard:destination_detail", pk=pk)


@export_staff_required
def restriction_create(request, pk):
    destination = get_object_or_404(ExportDestination, pk=pk)
    form = TradeRestrictionForm(request.POST)
    if form.is_valid():
        data = dict(form.cleaned_data)
        try:
            services.add_trade_restriction(
                destination, actor=request.user, description=data.pop("description"), **data
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Trade restriction added.")
    else:
        messages.error(request, "Please correct the restriction form.")
    return redirect("export_dashboard:destination_detail", pk=pk)


@export_staff_required
def document_requirement_create(request, pk):
    destination = get_object_or_404(ExportDestination, pk=pk)
    form = DocumentRequirementForm(request.POST)
    if form.is_valid():
        data = dict(form.cleaned_data)
        try:
            services.add_document_requirement(
                destination, actor=request.user, document_type=data.pop("document_type"), **data
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Document requirement added.")
    else:
        messages.error(request, "Please correct the document requirement form.")
    return redirect("export_dashboard:destination_detail", pk=pk)


# ---------------------------------------------------------------------------
# Task 2 — product configuration
# ---------------------------------------------------------------------------


@export_staff_required
def product_list(request):
    q = request.GET.get("q", "").strip()
    products = Product.objects.select_related("category").prefetch_related("export_profile")
    if q:
        products = products.filter(name__icontains=q)
    return render(
        request,
        "dashboard/export/product_list.html",
        _base_context(request, products=products[:200], q=q),
    )


@export_staff_required
def product_edit(request, pk):
    product = get_object_or_404(Product.objects.select_related("category"), pk=pk)
    profile = getattr(product, "export_profile", None)
    if request.method == "POST":
        form = ExportProductProfileForm(request.POST, instance=profile)
        if form.is_valid():
            try:
                services.upsert_product_profile(
                    product=product, actor=request.user, **form.cleaned_data
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _errors(exc))
            else:
                messages.success(request, "Export configuration saved.")
                return redirect("export_dashboard:product_edit", pk=product.pk)
    else:
        form = ExportProductProfileForm(instance=profile)
    return render(
        request,
        "dashboard/export/product_form.html",
        _base_context(request, product=product, form=form, profile=profile),
    )


# ---------------------------------------------------------------------------
# Task 3 — enquiries
# ---------------------------------------------------------------------------


@export_staff_required
def enquiry_list(request):
    status = request.GET.get("status", "")
    destination = request.GET.get("destination", "")
    q = request.GET.get("q", "").strip()
    return render(
        request,
        "dashboard/export/enquiry_list.html",
        _base_context(
            request,
            enquiries=selectors.staff_enquiries(status=status, destination=destination, q=q),
            status=status,
            selected_destination=destination,
            q=q,
            statuses=ExportEnquiryStatus.choices,
            destinations=ExportDestination.objects.select_related("country"),
        ),
    )


@export_staff_required
def enquiry_detail(request, reference):
    enquiry = get_object_or_404(
        ExportEnquiry.objects.select_related(
            "customer", "destination", "destination__country", "assigned_to"
        ),
        reference=reference,
    )
    return render(
        request,
        "dashboard/export/enquiry_detail.html",
        _base_context(
            request,
            enquiry=enquiry,
            items=enquiry.items.select_related("product", "unit"),
            history=enquiry.status_history.select_related("actor"),
            quotations=enquiry.quotations.all(),
            attachments=enquiry.attachments.all(),
            note_form=EnquiryNoteForm(),
            assignment_form=AssignmentForm(initial={"assignee": enquiry.assigned_to}),
            action_choices=[
                ("review", "Mark under review"),
                ("requirements", "Request requirements"),
                ("reject", "Reject"),
                ("cancel", "Cancel"),
            ],
        ),
    )


@export_staff_required
def enquiry_action(request, reference):
    enquiry = get_object_or_404(ExportEnquiry, reference=reference)
    action = request.POST.get("action", "")
    note = request.POST.get("note", "")
    try:
        if action == "review":
            services.review_enquiry(enquiry, actor=request.user, note=note)
        elif action == "requirements":
            services.request_enquiry_requirements(enquiry, actor=request.user, note=note)
        elif action == "reject":
            services.reject_enquiry(enquiry, actor=request.user, note=note)
        elif action == "cancel":
            services.cancel_enquiry(enquiry, actor=request.user, note=note)
        elif action == "assign":
            assignee_id = request.POST.get("assignee") or None
            assignee = None
            if assignee_id:
                from django.contrib.auth import get_user_model

                assignee = get_user_model().objects.filter(pk=assignee_id).first()
            services.assign_enquiry(enquiry, actor=request.user, assignee=assignee)
        else:
            messages.error(request, "Unknown action.")
            return redirect("export_dashboard:enquiry_detail", reference=reference)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Enquiry updated.")
    return redirect("export_dashboard:enquiry_detail", reference=reference)


# ---------------------------------------------------------------------------
# Task 4 — quotations
# ---------------------------------------------------------------------------


@export_staff_required
def quotation_list(request):
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    return render(
        request,
        "dashboard/export/quotation_list.html",
        _base_context(
            request,
            quotations=selectors.staff_quotations(status=status, q=q),
            status=status,
            q=q,
            statuses=ExportQuotation._meta.get_field("status").choices,
        ),
    )


@export_staff_required
def quotation_create(request, reference):
    enquiry = get_object_or_404(
        ExportEnquiry.objects.select_related("customer", "destination", "destination__country"),
        reference=reference,
    )
    if request.method == "POST":
        form = QuotationForm(request.POST)
        formset = QuotationItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            items = []
            for item_form in formset:
                cleaned = getattr(item_form, "cleaned_data", None)
                if not cleaned or not cleaned.get("description"):
                    continue
                items.append(cleaned)
            try:
                quotation = services.create_quotation(
                    enquiry=enquiry, actor=request.user, items=items, **form.cleaned_data
                )
                if request.POST.get("submit_for_approval"):
                    services.submit_quotation_for_approval(quotation, actor=request.user)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _errors(exc))
            else:
                messages.success(request, f"Quotation {quotation.reference} drafted.")
                return redirect("export_dashboard:quotation_detail", pk=quotation.pk)
        else:
            messages.error(request, "Please correct the quotation form.")
    else:
        form = QuotationForm(
            initial={
                "currency": "USD",
                "incoterm": "FOB",
                "incoterm_version": "2020",
                "payment_terms": "30% deposit, balance before shipment",
                "delivery_terms": "To be confirmed",
            }
        )
        formset = QuotationItemFormSet()
    return render(
        request,
        "dashboard/export/quotation_form.html",
        _base_context(request, enquiry=enquiry, form=form, formset=formset),
    )


@export_staff_required
def quotation_detail(request, pk):
    quotation = get_object_or_404(
        ExportQuotation.objects.select_related(
            "customer", "destination", "destination__country", "enquiry", "approved_by"
        ),
        pk=pk,
    )
    return render(
        request,
        "dashboard/export/quotation_detail.html",
        _base_context(
            request,
            quotation=quotation,
            items=quotation.items.select_related("product", "unit"),
            revisions=quotation.revisions.select_related("created_by"),
            revise_form=ReviseQuotationForm(),
            order=getattr(quotation, "order", None),
        ),
    )


@export_approve_required
@require_POST
def quotation_approve(request, pk):
    quotation = get_object_or_404(ExportQuotation, pk=pk)
    try:
        services.approve_quotation(quotation, actor=request.user)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Quotation approved and issued.")
    return redirect("export_dashboard:quotation_detail", pk=pk)


@export_staff_required
def quotation_revise(request, pk):
    quotation = get_object_or_404(ExportQuotation, pk=pk)
    form = ReviseQuotationForm(request.POST)
    if form.is_valid():
        changes = {}
        if form.cleaned_data.get("valid_until"):
            changes["valid_until"] = form.cleaned_data["valid_until"]
        try:
            services.revise_quotation(
                quotation,
                actor=request.user,
                changes=changes,
                summary=form.cleaned_data.get("summary", ""),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, f"Quotation revised to revision {quotation.revision}.")
    else:
        messages.error(request, "Please correct the revision form.")
    return redirect("export_dashboard:quotation_detail", pk=pk)


# ---------------------------------------------------------------------------
# Task 5 — export orders
# ---------------------------------------------------------------------------


@export_staff_required
def order_list(request):
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    return render(
        request,
        "dashboard/export/order_list.html",
        _base_context(
            request,
            orders=selectors.staff_orders(status=status, q=q),
            status=status,
            q=q,
            statuses=ExportOrderStatus.choices,
        ),
    )


@export_staff_required
def order_detail(request, reference):
    order = get_object_or_404(
        ExportOrder.objects.select_related(
            "customer", "destination", "destination__country", "quotation", "assigned_to"
        ),
        reference=reference,
    )
    checklist = getattr(order, "compliance_checklist", None)
    return render(
        request,
        "dashboard/export/order_detail.html",
        _base_context(
            request,
            order=order,
            items=order.items.select_related("product", "unit"),
            documents=selectors.visible_documents(order, staff=True),
            shipments=order.shipments.select_related("provider").prefetch_related("milestones"),
            checklist=checklist,
            history=order.status_history.select_related("actor"),
            payments=order.payments.order_by("-created_at"),
            document_form=DocumentForm(),
            status_choices=ExportOrderStatus.choices,
        ),
    )


@export_staff_required
def order_transition(request, reference):
    order = get_object_or_404(ExportOrder, reference=reference)
    to_status = request.POST.get("status", "")
    note = request.POST.get("note", "")
    try:
        services.transition_export_order(order, to_status, actor=request.user, note=note)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    else:
        messages.success(request, f"Order moved to {order.get_status_display()}.")
    return redirect("export_dashboard:order_detail", reference=reference)


# ---------------------------------------------------------------------------
# Task 6 — documents
# ---------------------------------------------------------------------------


@export_staff_required
def document_list(request):
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    return render(
        request,
        "dashboard/export/document_list.html",
        _base_context(
            request, documents=selectors.staff_documents(status=status, q=q), status=status, q=q
        ),
    )


@export_staff_required
def document_detail(request, pk):
    document = get_object_or_404(
        ExportDocument.objects.select_related("order", "document_type", "reviewed_by"), pk=pk
    )
    return render(
        request,
        "dashboard/export/document_detail.html",
        _base_context(
            request,
            document=document,
            reviews=document.reviews.select_related("reviewer"),
            review_form=DocumentReviewForm(),
        ),
    )


@export_staff_required
def document_review(request, pk):
    document = get_object_or_404(ExportDocument, pk=pk)
    form = DocumentReviewForm(request.POST)
    if form.is_valid():
        try:
            services.review_document(
                document,
                actor=request.user,
                decision=form.cleaned_data["decision"],
                notes=form.cleaned_data.get("notes", ""),
                expiration_date=form.cleaned_data.get("expiration_date"),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Document reviewed.")
    else:
        messages.error(request, "Please correct the review form.")
    return redirect("export_dashboard:document_detail", pk=document.pk)


@export_staff_required
def document_create(request, reference):
    order = get_object_or_404(ExportOrder, reference=reference)
    form = DocumentForm(request.POST, request.FILES)
    if form.is_valid():
        data = form.cleaned_data
        try:
            services.add_document(
                order,
                actor=request.user,
                document_type=data["document_type"],
                file=data["file"],
                issuing_organization=data.get("issuing_organization", ""),
                document_reference=data.get("document_reference", ""),
                issue_date=data.get("issue_date"),
                expiration_date=data.get("expiration_date"),
                is_customer_visible=data.get("is_customer_visible", True),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Document uploaded.")
    else:
        messages.error(request, "Please correct the upload form.")
    return redirect("export_dashboard:order_detail", reference=reference)


# ---------------------------------------------------------------------------
# Task 6/7 — documents & compliance
# ---------------------------------------------------------------------------


@export_staff_required
def compliance_list(request):
    return render(
        request,
        "dashboard/export/compliance_list.html",
        _base_context(request, checklists=_compliance_qs()),
    )


def _compliance_qs():
    return (
        ExportComplianceChecklist.objects.select_related(
            "order", "order__destination", "approved_by"
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )


@export_staff_required
def compliance_detail(request, pk):
    checklist = get_object_or_404(
        ExportComplianceChecklist.objects.select_related("order", "order__customer", "approved_by"),
        pk=pk,
    )
    return render(
        request,
        "dashboard/export/compliance_detail.html",
        _base_context(
            request,
            checklist=checklist,
            items=checklist.items.select_related("document"),
            approval_form=ComplianceApprovalForm(),
            item_form=ComplianceItemForm(),
            item_statuses=ComplianceItemStatus.choices,
            completed=checklist.status == ComplianceChecklistStatus.APPROVED,
        ),
    )


@export_staff_required
def compliance_item_update(request, pk):
    from .models import ExportComplianceChecklistItem

    item = get_object_or_404(ExportComplianceChecklistItem, pk=pk)
    form = ComplianceItemForm(request.POST)
    if form.is_valid():
        try:
            services.update_compliance_item(
                item,
                actor=request.user,
                status=form.cleaned_data["status"],
                notes=form.cleaned_data.get("notes", ""),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Compliance item updated.")
    else:
        messages.error(request, "Please correct the compliance form.")
    return redirect("export_dashboard:compliance_detail", pk=item.checklist_id)


@export_approve_required
@require_POST
def compliance_approve(request, pk):
    checklist = get_object_or_404(ExportComplianceChecklist, pk=pk)
    form = ComplianceApprovalForm(request.POST)
    notes = form.cleaned_data.get("notes", "") if form.is_valid() else ""
    try:
        services.approve_compliance_checklist(checklist, actor=request.user, notes=notes)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Compliance checklist approved.")
    return redirect("export_dashboard:compliance_detail", pk=pk)


# ---------------------------------------------------------------------------
# Task 8 — shipments
# ---------------------------------------------------------------------------


@export_staff_required
def shipment_list(request):
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    return render(
        request,
        "dashboard/export/shipment_list.html",
        _base_context(
            request,
            shipments=selectors.shipments_queue(status=status, q=q),
            status=status,
            q=q,
            statuses=ShipmentStatus.choices,
        ),
    )


@export_staff_required
def shipment_create(request):
    order_reference = request.POST.get("order") or request.GET.get("order") or ""
    order = get_object_or_404(ExportOrder, reference=order_reference) if order_reference else None
    if order is None:
        messages.error(request, "Choose an export order to create a shipment for.")
        return redirect("export_dashboard:order_list")
    if request.method == "POST":
        form = ShipmentForm(request.POST)
        if form.is_valid():
            try:
                shipment = services.create_shipment(order, actor=request.user, **form.cleaned_data)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _errors(exc))
            else:
                messages.success(request, f"Shipment {shipment.reference} created.")
                return redirect("export_dashboard:shipment_detail", reference=shipment.reference)
    else:
        form = ShipmentForm(initial={"origin": "Nigeria"})
    return render(
        request,
        "dashboard/export/shipment_form.html",
        _base_context(request, order=order, form=form),
    )


@export_staff_required
def shipment_detail(request, reference):
    shipment = get_object_or_404(
        ExportShipment.objects.select_related("order", "order__customer", "provider"),
        reference=reference,
    )
    return render(
        request,
        "dashboard/export/shipment_detail.html",
        _base_context(
            request,
            shipment=shipment,
            milestones=shipment.milestones.select_related("recorded_by"),
            documents=shipment.documents.select_related("document__document_type"),
            status_form=ShipmentStatusForm(),
            item_choices=[(s.value, s.label) for s in ShipmentStatus],
        ),
    )


@export_staff_required
def shipment_transition(request, reference):
    shipment = get_object_or_404(ExportShipment, reference=reference)
    form = ShipmentStatusForm(request.POST)
    if form.is_valid():
        try:
            services.transition_shipment(
                shipment,
                form.cleaned_data["status"],
                actor=request.user,
                note=form.cleaned_data.get("note", ""),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Shipment updated.")
    else:
        messages.error(request, "Please correct the shipment form.")
    return redirect("export_dashboard:shipment_detail", reference=reference)


@export_staff_required
def shipment_milestone(request, reference):
    shipment = get_object_or_404(ExportShipment, reference=reference)
    status = request.POST.get("status", "")
    occurred_at = request.POST.get("occurred_at") or None
    try:
        services.add_shipment_milestone(
            shipment,
            actor=request.user,
            status=status,
            occurred_at=occurred_at,
            location=request.POST.get("location", ""),
            notes=request.POST.get("notes", ""),
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Milestone recorded.")
    return redirect("export_dashboard:shipment_detail", reference=reference)


# ---------------------------------------------------------------------------
# Logistics providers
# ---------------------------------------------------------------------------


@export_staff_required
def provider_list(request):
    providers = LogisticsProvider.objects.order_by("name")
    return render(
        request,
        "dashboard/export/provider_list.html",
        _base_context(request, providers=providers, form=LogisticsProviderForm()),
    )


@export_staff_required
def provider_create(request):
    if request.method == "POST":
        form = LogisticsProviderForm(request.POST)
        if form.is_valid():
            try:
                provider = services.upsert_logistics_provider(
                    actor=request.user, **form.cleaned_data
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _errors(exc))
            else:
                messages.success(request, f"Provider {provider.name} saved.")
        else:
            messages.error(request, "Please correct the provider form.")
    return redirect("export_dashboard:provider_list")


# ---------------------------------------------------------------------------
# Task 12 — reporting
# ---------------------------------------------------------------------------


@export_staff_required
def reports(request):
    context = _base_context(
        request,
        page_title="Export reports",
        metrics=selectors.overview_metrics(),
        enquiries_by_destination=selectors.enquiries_by_destination(),
        quotations_by_status=selectors.quotations_by_status(),
        orders_by_status=selectors.orders_by_status(),
        shipment_status_breakdown=selectors.shipment_status_breakdown(),
        product_quantities=selectors.product_quantities(),
        revenue_by_currency=selectors.verified_revenue_by_currency(),
        compliance_delays=selectors.compliance_delays(),
        stale_requirements=selectors.stale_requirements(limit=10),
    )
    return render(request, "dashboard/export/reports.html", context)

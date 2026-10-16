"""Customer service-portal views (``/account/services/...``).

Reads come from :mod:`apps.services.selectors`; every write goes through
:mod:`apps.services.services` and is ownership-checked. Nothing here trusts the
browser for money: the payment callback re-verifies server-side via the Phase 6
pipeline.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.orders import payments as order_payments
from apps.orders.payment_models import PaymentProvider, PaymentState

from . import selectors, services
from .forms import (
    ConsultationBookingForm,
    FarmServiceRequestForm,
    MarketingEnquiryForm,
    StorageRequestForm,
)
from .models import QuotationStatus, ServiceQuotation, ServiceType


def _errors(exc) -> str:
    return "; ".join(getattr(exc, "messages", [str(exc)]))


def _owned_quotation(request, pk):
    quotation = selectors.customer_quotation(request.user, pk)
    if quotation is None:
        raise Http404("Quotation not found.")
    return quotation


# ---------------------------------------------------------------------------
# Portal home & lists
# ---------------------------------------------------------------------------


@login_required
def service_home(request):
    return render(
        request,
        "services/customer/home.html",
        {
            "page_title": "Services",
            "requests": selectors.customer_service_requests(request.user)[:10],
            "quotations": selectors.customer_quotations(request.user)[:10],
            "appointments": selectors.customer_appointments(request.user)[:5],
            "bookings": selectors.customer_storage_bookings(request.user)[:5],
        },
    )


@login_required
def request_list(request):
    service_type = request.GET.get("type", "")
    status = request.GET.get("status", "")
    return render(
        request,
        "services/customer/request_list.html",
        {
            "page_title": "My service requests",
            "requests": selectors.customer_service_requests(
                request.user, service_type=service_type, status=status
            ),
            "service_type": service_type,
            "status": status,
            "service_types": ServiceType.choices,
        },
    )


@login_required
def request_detail(request, reference):
    service_request = selectors.customer_service_request(request.user, reference)
    if service_request is None:
        raise Http404("Service request not found.")
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "comment":
                services.add_comment(
                    service_request,
                    author=request.user,
                    body=request.POST.get("body", ""),
                    visibility="customer",
                )
                messages.success(request, "Comment added.")
            elif action == "attachment":
                services.add_attachment(
                    service_request,
                    uploaded_by=request.user,
                    file=request.FILES.get("file"),
                    label=request.POST.get("label", ""),
                )
                messages.success(request, "Attachment uploaded.")
        except ValidationError as exc:
            messages.error(request, _errors(exc))
        return redirect("services:request_detail", reference=reference)
    return render(
        request,
        "services/customer/request_detail.html",
        {
            "page_title": service_request.title,
            "request_obj": service_request,
            "timeline": selectors.request_status_timeline(service_request),
        },
    )


# ---------------------------------------------------------------------------
# New requests (one per division)
# ---------------------------------------------------------------------------


@login_required
def consultation_create(request):
    form = ConsultationBookingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.book_consultation(
                customer=request.user,
                service=data["service"],
                mode=data["mode"],
                preferred_start=data["preferred_start"],
                description=data["description"],
                state=data.get("state"),
                lga=data.get("lga"),
                address=data["address"],
            )
        except ValidationError as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Consultation requested.")
            return redirect("services:service_home")
    return render(
        request,
        "services/customer/consultation_form.html",
        {"page_title": "Book a consultation", "form": form},
    )


@login_required
def farming_create(request):
    form = FarmServiceRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.submit_farm_service_request(
                customer=request.user,
                farm_location=data["farm_location"],
                requested_service=data.get("requested_service"),
                state=data.get("state"),
                lga=data.get("lga"),
                farm_size=data.get("farm_size"),
                area_unit=data["area_unit"],
                crop_type=data["crop_type"],
                season=data["season"],
                expected_start_date=data.get("expected_start_date"),
                budget_min=data.get("budget_min"),
                budget_max=data.get("budget_max"),
                additional_requirements=data["additional_requirements"],
            )
        except ValidationError as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Farming service request submitted.")
            return redirect("services:service_home")
    return render(
        request,
        "services/customer/farming_form.html",
        {"page_title": "Request farming services", "form": form},
    )


@login_required
def marketing_create(request):
    form = MarketingEnquiryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.submit_marketing_enquiry(
                customer=request.user,
                service=data.get("service"),
                product_type=data["product_type"],
                available_quantity=data["available_quantity"],
                unit=data.get("unit"),
                product_location=data["product_location"],
                target_market=data["target_market"],
                marketing_requirements=data["marketing_requirements"],
                preferred_timeline=data["preferred_timeline"],
            )
        except ValidationError as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Marketing enquiry submitted.")
            return redirect("services:service_home")
    return render(
        request,
        "services/customer/marketing_form.html",
        {"page_title": "Marketing enquiry", "form": form},
    )


@login_required
def storage_create(request):
    form = StorageRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.submit_storage_request(
                customer=request.user,
                produce_type=data.get("produce_type"),
                quantity=data["quantity"],
                unit=data.get("unit"),
                preferred_facility=data.get("preferred_facility"),
                preferred_location=data["preferred_location"],
                requested_start_date=data.get("requested_start_date"),
                requested_end_date=data.get("requested_end_date"),
                special_handling=data["special_handling"],
            )
        except ValidationError as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Storage request submitted.")
            return redirect("services:service_home")
    return render(
        request,
        "services/customer/storage_form.html",
        {"page_title": "Storage request", "form": form},
    )


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------


@login_required
def quotation_list(request):
    status = request.GET.get("status", "")
    return render(
        request,
        "services/customer/quotation_list.html",
        {
            "page_title": "Service quotations",
            "quotations": selectors.customer_quotations(request.user, status=status),
            "status": status,
            "statuses": QuotationStatus.choices,
        },
    )


@login_required
def quotation_detail(request, pk):
    quotation = _owned_quotation(request, pk)
    if request.method == "POST":
        action = request.POST.get("action")
        note = request.POST.get("note", "")
        try:
            if action == "accept":
                services.accept_quotation(quotation, actor=request.user, note=note)
                messages.success(request, "Quotation accepted.")
            elif action == "reject":
                services.reject_quotation(quotation, actor=request.user, note=note)
                messages.success(request, "Quotation rejected.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        return redirect("services:quotation_detail", pk=quotation.pk)
    return render(
        request,
        "services/customer/quotation_detail.html",
        {"page_title": f"Quotation {quotation.reference}", "quotation": quotation},
    )


@require_POST
@login_required
def quotation_pay(request, pk):
    quotation = _owned_quotation(request, pk)
    if quotation.customer_id != request.user.id:
        raise PermissionDenied("You cannot pay for this quotation.")
    try:
        payment = order_payments.initialize_quotation_payment(
            quotation, actor=request.user, request=request
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
        return redirect("services:quotation_detail", pk=pk)
    url = order_payments.latest_authorization_url(payment)
    if not url:
        messages.info(request, "We could not open the payment page. Please try again.")
        return redirect("services:quotation_detail", pk=pk)
    return redirect(url)


@login_required
def service_payment_callback(request, reference):
    """Paystack redirect target for a service quotation; re-verifies server-side."""
    quotation = ServiceQuotation.objects.filter(reference=reference).first()
    if quotation is None:
        messages.error(request, "Quotation not found.")
        return redirect("services:service_home")
    if quotation.customer_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied("You cannot view this quotation.")

    reference_value = request.GET.get("reference") or request.GET.get("trxref") or ""
    queryset = quotation.payments.filter(provider=PaymentProvider.PAYSTACK)
    payment = None
    if reference_value:
        payment = (
            queryset.filter(reference=reference_value).first()
            or queryset.filter(provider_reference=reference_value).first()
        )
    if payment is None:
        payment = queryset.order_by("-created_at").first()
    if payment is None:
        messages.error(request, "We could not find a payment for this quotation.")
        return redirect("services:quotation_detail", pk=quotation.pk)

    try:
        order_payments.verify_payment(payment, request=request, source="callback")
    except ValidationError as exc:
        messages.error(request, _errors(exc))
    except Exception:
        messages.warning(
            request, "We could not confirm your payment yet. Please refresh in a moment."
        )
    else:
        payment.refresh_from_db()
        if payment.status in {PaymentState.PAID, PaymentState.PARTIALLY_REFUNDED}:
            messages.success(request, "Payment confirmed. Thank you!")
        elif payment.requires_review:
            messages.info(request, "Payment received — our finance team will verify it shortly.")
        else:
            messages.info(request, "Your payment is still being processed.")
    return redirect("services:quotation_detail", pk=quotation.pk)


@login_required
@require_POST
def proposal_decide(request, pk):
    from .models import MarketingProposal

    proposal = (
        MarketingProposal.objects.filter(pk=pk, enquiry__request__customer=request.user)
        .select_related("enquiry__request")
        .first()
    )
    if proposal is None:
        raise Http404("Proposal not found.")
    accepted = request.POST.get("decision") == "accept"
    try:
        services.decide_marketing_proposal(
            proposal, actor=request.user, accepted=accepted, note=request.POST.get("note", "")
        )
        messages.success(request, "Proposal decision recorded.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    return redirect("services:request_detail", reference=proposal.enquiry.request.reference)

"""Customer export-portal views (``/account/export/...``).

Reads come from :mod:`apps.export.selectors`; every write goes through
:mod:`apps.export.services` and is ownership-checked. Customers only ever see
their own enquiries, quotations, orders, documents and shipments. The payment
callback re-verifies server-side through the Phase 6 pipeline.
"""

from __future__ import annotations

import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability
from apps.orders import payments as order_payments
from apps.orders.payment_models import PaymentProvider, PaymentState

from . import selectors, services
from .forms import EnquiryForm, EnquiryItemFormSet, UserDocumentForm
from .models import ExportDocument, ExportEnquiry, ExportOrder


def _errors(exc) -> str:
    return "; ".join(getattr(exc, "messages", [str(exc)]))


def _owned(model, request, reference):
    """Fetch a customer-owned enquiry/order by reference or raise 404."""
    obj = model.objects.filter(reference=reference, customer=request.user).first()
    if obj is None:
        raise Http404("Not found.")
    return obj


# ---------------------------------------------------------------------------
# Portal home & lists
# ---------------------------------------------------------------------------


@login_required
def export_home(request):
    return render(
        request,
        "export/customer/home.html",
        {
            "page_title": "Export",
            "enquiries": selectors.enquiries_for(request.user)[:5],
            "quotations": selectors.quotations_for(request.user)[:5],
            "orders": selectors.orders_for(request.user)[:5],
            "shipments": selectors.shipments_for(request.user)[:5],
        },
    )


@login_required
def enquiry_list(request):
    return render(
        request,
        "export/customer/enquiry_list.html",
        {"page_title": "My export enquiries", "enquiries": selectors.enquiries_for(request.user)},
    )


@login_required
def enquiry_create(request):
    if request.method == "POST":
        form = EnquiryForm(request.POST)
        formset = EnquiryItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            data = dict(form.cleaned_data)
            destination = data.pop("destination")
            items = []
            for item_form in formset:
                cleaned = getattr(item_form, "cleaned_data", None)
                if not cleaned or not cleaned.get("product"):
                    continue
                items.append(
                    {
                        "product": cleaned["product"],
                        "listing": cleaned.get("listing"),
                        "quantity": cleaned["quantity"],
                        "unit": cleaned.get("unit") or cleaned["product"].unit,
                        "packaging_requirements": cleaned.get("packaging_requirements", ""),
                        "notes": cleaned.get("notes", ""),
                    }
                )
            try:
                enquiry = services.create_enquiry(
                    customer=request.user,
                    destination=destination,
                    items=items,
                    actor=request.user,
                    **data,
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _errors(exc))
            else:
                messages.success(request, f"Enquiry {enquiry.reference} submitted.")
                return redirect("export:enquiry_detail", reference=enquiry.reference)
    else:
        form = EnquiryForm()
        formset = EnquiryItemFormSet()
    return render(
        request,
        "export/customer/enquiry_form.html",
        {"page_title": "New export enquiry", "form": form, "formset": formset},
    )


@login_required
def enquiry_detail(request, reference):
    enquiry = _owned(ExportEnquiry, request, reference)
    return render(
        request,
        "export/customer/enquiry_detail.html",
        {
            "page_title": f"Enquiry {enquiry.reference}",
            "enquiry": enquiry,
            "items": enquiry.items.select_related("product", "unit"),
            "history": enquiry.status_history.select_related("actor"),
            "quotations": enquiry.quotations.all(),
        },
    )


@login_required
def quotation_list(request):
    return render(
        request,
        "export/customer/quotation_list.html",
        {
            "page_title": "My export quotations",
            "quotations": selectors.quotations_for(request.user),
        },
    )


@login_required
def quotation_detail(request, pk):
    quotation = selectors.quotations_for(request.user).filter(pk=pk).first()
    if quotation is None:
        raise Http404("Quotation not found.")
    order = getattr(quotation, "order", None)
    return render(
        request,
        "export/customer/quotation_detail.html",
        {
            "page_title": f"Quotation {quotation.reference}",
            "quotation": quotation,
            "items": quotation.items.all(),
            "revisions": quotation.revisions.all(),
            "order": order,
        },
    )


@require_POST
@login_required
def quotation_accept(request, pk):
    quotation = selectors.quotations_for(request.user).filter(pk=pk).first()
    if quotation is None:
        raise Http404("Quotation not found.")
    try:
        order = services.accept_quotation(quotation, actor=request.user)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
        return redirect("export:quotation_detail", pk=pk)
    messages.success(request, f"Quotation accepted. Export order {order.reference} created.")
    return redirect("export:order_detail", reference=order.reference)


@login_required
def order_list(request):
    return render(
        request,
        "export/customer/order_list.html",
        {"page_title": "My export orders", "orders": selectors.orders_for(request.user)},
    )


@login_required
def order_detail(request, reference):
    order = _owned(ExportOrder, request, reference)
    checklist = getattr(order, "compliance_checklist", None)
    return render(
        request,
        "export/customer/order_detail.html",
        {
            "page_title": f"Export order {order.reference}",
            "order": order,
            "items": order.items.select_related("product", "unit"),
            "documents": selectors.visible_documents(order),
            "shipments": order.shipments.select_related("provider").prefetch_related("milestones"),
            "checklist": checklist,
            "document_form": UserDocumentForm(),
            "history": order.status_history.select_related("actor"),
        },
    )


@require_POST
@login_required
def order_pay(request, reference):
    order = _owned(ExportOrder, request, reference)
    amount = order.balance_due or order.total
    purpose = "balance" if order.amount_paid else ("deposit" if order.deposit_amount else "full")
    try:
        payment = order_payments.initialize_export_payment(
            order, actor=request.user, amount=amount, purpose=purpose, request=request
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
        return redirect("export:order_detail", reference=reference)
    url = order_payments.latest_authorization_url(payment)
    if not url:
        messages.info(request, "We could not open the payment page. Please try again.")
        return redirect("export:order_detail", reference=reference)
    return redirect(url)


@require_POST
@login_required
def document_upload(request, reference):
    order = _owned(ExportOrder, request, reference)
    form = UserDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            services.upload_customer_document(
                order,
                customer=request.user,
                document_type=form.cleaned_data["document_type"],
                file=form.cleaned_data["file"],
                document_reference=form.cleaned_data.get("document_reference", ""),
                expiration_date=form.cleaned_data.get("expiration_date"),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Document uploaded.")
    else:
        messages.error(request, "Please correct the upload errors.")
    return redirect("export:order_detail", reference=order.reference)


@login_required
def document_download(request, pk):
    document = ExportDocument.objects.select_related("order", "document_type").filter(pk=pk).first()
    if document is None:
        raise Http404("Document not found.")
    is_staff = has_capability(
        request.user, Capability.EXPORT_MANAGE, Capability.EXPORT_APPROVE, any_of=True
    )
    if not is_staff:
        if document.order.customer_id != request.user.id or not document.is_customer_visible:
            raise PermissionDenied("You cannot access this document.")
    return FileResponse(
        document.file.open("rb"),
        as_attachment=True,
        filename=os.path.basename(document.file.name),
    )


@login_required
def shipment_list(request):
    return render(
        request,
        "export/customer/shipment_list.html",
        {
            "page_title": "My export shipments",
            "shipments": selectors.shipments_for(request.user),
        },
    )


@login_required
def shipment_detail(request, reference):
    shipment = selectors.shipments_for(request.user).filter(reference=reference).first()
    if shipment is None:
        raise Http404("Shipment not found.")
    return render(
        request,
        "export/customer/shipment_detail.html",
        {
            "page_title": f"Shipment {shipment.reference}",
            "shipment": shipment,
            "milestones": shipment.milestones.select_related("recorded_by"),
        },
    )


@login_required
def payment_callback(request, reference):
    """Paystack redirect target for an export order; re-verifies server-side."""
    order = ExportOrder.objects.filter(reference=reference).first()
    if order is None:
        messages.error(request, "Export order not found.")
        return redirect("export:export_home")
    if order.customer_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied("You cannot view this export order.")

    reference_value = request.GET.get("reference") or request.GET.get("trxref") or ""
    queryset = order.payments.filter(provider=PaymentProvider.PAYSTACK)
    payment = None
    if reference_value:
        payment = (
            queryset.filter(reference=reference_value).first()
            or queryset.filter(provider_reference=reference_value).first()
        )
    if payment is None:
        payment = queryset.order_by("-created_at").first()
    if payment is None:
        messages.error(request, "We could not find a payment for this export order.")
        return redirect("export:order_detail", reference=order.reference)

    try:
        order_payments.verify_payment(payment, request=request, source="callback")
    except ValidationError as exc:
        messages.error(request, _errors(exc))
    except Exception:  # pragma: no cover - defensive; never expose provider errors
        messages.warning(request, "We could not confirm your payment yet. Please refresh.")
    else:
        payment.refresh_from_db()
        if payment.status == PaymentState.PAID:
            messages.success(request, "Payment confirmed. Thank you!")
        elif payment.requires_review:
            messages.info(request, "Payment received — our finance team will verify it shortly.")
        else:
            messages.info(request, "We have not received confirmation of your payment yet.")
    return redirect("export:order_detail", reference=order.reference)

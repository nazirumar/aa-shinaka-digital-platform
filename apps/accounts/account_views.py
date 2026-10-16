"""Customer account portal views (``/account/...``)."""

from __future__ import annotations

import os

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.audit import record_audit

from . import documents as document_services
from .activity import activity_feed
from .forms import AddressForm, ProfileForm, StyledPasswordChangeForm
from .models import Address
from .services import (
    delete_address,
    set_default_address,
    update_customer_profile,
)


def _profile_completion(user) -> tuple[int, list[str]]:
    """Return (percentage, missing_labels) based on real stored data only."""
    checks = [
        ("First name", bool(user.first_name)),
        ("Last name", bool(user.last_name)),
        ("Phone number", bool(user.phone)),
        ("Email verified", user.is_email_verified),
        ("Delivery address", user.addresses.exists()),
    ]
    missing = [label for label, done in checks if not done]
    done_count = len(checks) - len(missing)
    return round(done_count / len(checks) * 100), missing


def _account_metrics(user) -> dict:
    """Real, non-fabricated counters for the unified portal dashboard."""
    from apps.export.models import ExportEnquiry
    from apps.notifications.models import Notification
    from apps.orders.models import Order
    from apps.orders.payment_models import Invoice
    from apps.services.models import ServiceRequest
    from apps.support.models import SupportStatus, SupportTicket
    from apps.training.models import Enrollment

    return {
        "orders_total": Order.objects.filter(user=user).count(),
        "invoices_total": Invoice.objects.filter(order__user=user).count(),
        "service_requests_total": ServiceRequest.objects.filter(customer=user).count(),
        "export_enquiries_total": ExportEnquiry.objects.filter(customer=user).count(),
        "enrollments_total": Enrollment.objects.filter(student=user).count(),
        "tickets_open": SupportTicket.objects.filter(customer=user)
        .exclude(status__in=[SupportStatus.RESOLVED, SupportStatus.CLOSED])
        .count(),
        "notifications_unread": Notification.objects.filter(recipient=user, is_read=False).count(),
        "documents_total": document_services.document_count(user),
    }


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Customer landing page with real account status only."""
    percentage, missing = _profile_completion(request.user)
    return render(
        request,
        "accounts/account_dashboard.html",
        {
            "page_title": "My account",
            "profile_completion": percentage,
            "missing_profile_items": missing,
            "addresses": request.user.addresses.all()[:3],
            "metrics": _account_metrics(request.user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def profile(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            update_customer_profile(
                user=request.user,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                phone=form.cleaned_data["phone"],
                marketing_opt_in=form.cleaned_data["marketing_opt_in"],
                state=form.cleaned_data["state"],
                request=request,
            )
            messages.success(request, "Your profile has been updated.")
            return redirect("account:profile")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "accounts/profile.html", {"form": form, "page_title": "Profile"})


@login_required
def address_list(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "accounts/address_list.html",
        {"addresses": request.user.addresses.all(), "page_title": "Addresses"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def address_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = AddressForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Address saved.")
            return redirect("account:addresses")
    else:
        form = AddressForm(user=request.user)
    return render(
        request,
        "accounts/address_form.html",
        {"form": form, "page_title": "Add address"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def address_edit(request: HttpRequest, pk) -> HttpResponse:
    address = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method == "POST":
        form = AddressForm(request.POST, instance=address, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Address updated.")
            return redirect("account:addresses")
    else:
        form = AddressForm(instance=address, user=request.user)
    return render(
        request,
        "accounts/address_form.html",
        {"form": form, "address": address, "page_title": "Edit address"},
    )


@login_required
@require_POST
def address_delete(request: HttpRequest, pk) -> HttpResponse:
    address = get_object_or_404(Address, pk=pk, user=request.user)
    delete_address(user=request.user, address=address, request=request)
    messages.success(request, "Address removed.")
    return redirect("account:addresses")


@login_required
@require_POST
def address_set_default(request: HttpRequest, pk) -> HttpResponse:
    address = get_object_or_404(Address, pk=pk, user=request.user)
    set_default_address(user=request.user, address=address, request=request)
    messages.success(request, "Default address updated.")
    return redirect("account:addresses")


@login_required
@require_http_methods(["GET", "POST"])
def security(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = StyledPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Keeps this session valid; other sessions are invalidated because
            # their stored password hash no longer matches.
            update_session_auth_hash(request, user)
            record_audit(
                actor=user,
                action="account.password_changed",
                target=user,
                request=request,
            )
            messages.success(request, "Your password has been changed.")
            return redirect("account:security")
    else:
        form = StyledPasswordChangeForm(request.user)
    return render(request, "accounts/security.html", {"form": form, "page_title": "Security"})


@login_required
def documents(request: HttpRequest) -> HttpResponse:
    """The customer's documents across every domain, in one place."""
    return render(
        request,
        "accounts/documents.html",
        {
            "page_title": "Documents",
            "sections": document_services.document_sections(request.user),
        },
    )


@login_required
def document_download(request: HttpRequest, kind: str, pk) -> HttpResponse:
    """Authorised download of a customer-owned service file.

    Ownership is enforced by :func:`apps.accounts.documents.service_file`; an
    unknown kind or a record that does not belong to the caller is a 404.
    """
    document = document_services.service_file(request.user, kind, pk)
    if document is None or not document.file:
        raise Http404("Document not found.")
    record_audit(
        actor=request.user,
        action="account.document_downloaded",
        target=document,
        after={"kind": kind},
        request=request,
    )
    return FileResponse(
        document.file.open("rb"),
        as_attachment=True,
        filename=os.path.basename(document.file.name),
    )


@login_required
def activity(request: HttpRequest) -> HttpResponse:
    """Reverse-chronological feed of the customer's real activity."""
    return render(
        request,
        "accounts/activity.html",
        {
            "page_title": "Activity",
            "entries": activity_feed(request.user),
        },
    )

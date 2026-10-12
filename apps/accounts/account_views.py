"""Customer account portal views (``/account/...``)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.audit import record_audit

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

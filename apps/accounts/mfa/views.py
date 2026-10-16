"""MFA views: enrolment (start/confirm), login challenge, verify and disable."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.ratelimit import hit, rate_limit, rate_limit_response
from apps.core.ratelimit import reset as reset_rate_limit

from .forms import ConfirmTOTPForm, VerifyTOTPForm
from .models import MFADevice
from .services import (
    confirm_enrollment,
    disable_mfa,
    start_enrollment,
    verify_challenge,
)


def _parked_target(request: HttpRequest, default: str) -> str:
    candidate = request.session.get("mfa_pending_next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


@require_http_methods(["GET", "POST"])
def challenge(request: HttpRequest) -> HttpResponse:
    """Second login factor for a parked, password-verified session.

    The user is **not** authenticated yet: the session only carries the parked
    user id set by ``accounts.views.login_view``. Passing the challenge (TOTP
    code or a single-use recovery code) completes ``login()``.
    """
    if request.user.is_authenticated:
        return redirect("account:dashboard")

    user_id = request.session.get("mfa_pending_user_id")
    if not user_id:
        messages.info(request, "Please sign in again.")
        return redirect("accounts:login")

    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except (User.DoesNotExist, ValueError):
        request.session.flush()
        return redirect("accounts:login")

    form = VerifyTOTPForm(request.POST or None)
    if request.method == "POST":
        scope_id = f"{user_id}:{request.META.get('REMOTE_ADDR', 'unknown')}"
        if hit(
            "mfa_challenge",
            scope_id,
            limit=settings.MFA_RATE_LIMIT_ATTEMPTS,
            window=settings.MFA_RATE_LIMIT_WINDOW,
        ):
            return rate_limit_response(request, message="Too many verification attempts.")
        try:
            verify_challenge(user, request.POST, request=request)
        except Exception as exc:  # ValidationError carries the safe message
            messages.error(request, " ".join(str(m) for m in getattr(exc, "messages", [exc])))
        else:
            reset_rate_limit("mfa_challenge", scope_id)
            target = _parked_target(request, settings.LOGIN_REDIRECT_URL)
            request.session.flush()
            # Session fixation protection: login() cycles the session key again.
            login(request, user)
            messages.success(request, "You are signed in.")
            return redirect(target)

    return render(request, "accounts/mfa/challenge.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def start(request: HttpRequest) -> HttpResponse:
    """Begin enrolment: mint secret + recovery codes, show them once."""
    try:
        _device, secret, codes = start_enrollment(request.user, request=request)
    except Exception as exc:
        messages.error(request, " ".join(str(m) for m in getattr(exc, "messages", [exc])))
        return redirect("account:security")
    return render(request, "accounts/mfa/start.html", {"secret": secret, "codes": codes})


@login_required
@require_http_methods(["GET", "POST"])
def confirm(request: HttpRequest) -> HttpResponse:
    """Confirm enrolment with the first valid TOTP code."""
    form = ConfirmTOTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            confirm_enrollment(request.user, form.cleaned_data["code"], request=request)
        except Exception as exc:
            messages.error(request, " ".join(str(m) for m in getattr(exc, "messages", [exc])))
        else:
            messages.success(request, "Multi-factor authentication is now enabled.")
            return redirect("account:security")
    elif MFADevice.objects.filter(user=request.user).exists() is False:
        messages.info(request, "Start MFA enrolment first.")
        return redirect("mfa:start")
    return render(request, "accounts/mfa/confirm.html", {"form": form})


@rate_limit(
    scope="mfa_verify",
    limit=settings.MFA_RATE_LIMIT_ATTEMPTS,
    window=settings.MFA_RATE_LIMIT_WINDOW,
    by_user=True,
)
@login_required
@require_http_methods(["GET", "POST"])
def verify(request: HttpRequest) -> HttpResponse:
    """Manual MFA verification (step-up check for a signed-in user)."""
    form = VerifyTOTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            verify_challenge(request.user, request.POST, request=request)
        except Exception as exc:
            messages.error(request, " ".join(str(m) for m in getattr(exc, "messages", [exc])))
        else:
            messages.success(request, "Verification successful.")
            return redirect("account:security")
    return render(request, "accounts/mfa/verify.html", {"form": form})


@login_required
@require_POST
def disable(request: HttpRequest) -> HttpResponse:
    """Disable MFA — requires a fresh code from the account's own device."""
    try:
        disable_mfa(request.user, request=request, form_data=request.POST)
    except Exception as exc:
        messages.error(request, " ".join(str(m) for m in getattr(exc, "messages", [exc])))
        return redirect("account:security")
    messages.success(request, "Multi-factor authentication disabled.")
    return redirect("account:security")

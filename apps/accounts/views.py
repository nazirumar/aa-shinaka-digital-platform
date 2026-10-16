"""Authentication views: registration, login, logout and email verification."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

try:
    from apps.locations.models import LGA
except Exception:  # pragma: no cover
    from apps.core.models import LGA  # type: ignore[import-not-found,no-redef]
from apps.core.ratelimit import hit, rate_limit, rate_limit_response
from apps.core.ratelimit import reset as reset_rate_limit

from .emails import send_email_verification
from .forms import EmailAuthenticationForm, RegisterForm
from .mfa.services import mfa_enforced
from .services import confirm_email_token


def _safe_redirect_target(request: HttpRequest, default: str) -> str:
    """Return a validated post-login redirect target (open-redirect safe)."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


@require_http_methods(["GET", "POST"])
@rate_limit(
    scope="register",
    limit=settings.FORM_RATE_LIMIT_ATTEMPTS,
    window=settings.FORM_RATE_LIMIT_WINDOW,
)
def register(request: HttpRequest) -> HttpResponse:
    """Public customer self-registration (customers only)."""
    if request.user.is_authenticated:
        return redirect("account:dashboard")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
            except ValidationError as exc:
                form.add_error("email", exc.messages[0])
            else:
                login(request, user)
                send_email_verification(user, request=request)
                messages.success(
                    request,
                    "Welcome to AA Shinaka. We've emailed you a link to verify your address.",
                )
                return redirect("account:dashboard")
    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {"form": form})


@require_http_methods(["GET", "POST"])
@rate_limit(
    scope="login",
    limit=settings.LOGIN_RATE_LIMIT_ATTEMPTS,
    window=settings.LOGIN_RATE_LIMIT_WINDOW,
)
def login_view(request: HttpRequest) -> HttpResponse:
    """Email/password login with rate limiting and safe redirect handling.

    Privileged accounts with MFA confirmed are **not** logged in here: the
    session is parked as ``mfa_pending`` and the user must pass the TOTP (or
    recovery code) challenge at ``mfa:challenge`` first.
    """
    if request.user.is_authenticated:
        return redirect("account:dashboard")

    if request.method == "POST":
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            reset_rate_limit("login", f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}")
            if mfa_enforced(user):
                # Park the credentials-check result; do NOT authenticate yet.
                request.session.cycle_key()
                request.session["mfa_pending_user_id"] = str(user.pk)
                request.session["mfa_pending_next"] = _safe_redirect_target(
                    request, settings.LOGIN_REDIRECT_URL
                )
                request.session.set_expiry(settings.MFA_CHALLENGE_TIMEOUT)
                return redirect("mfa:challenge")
            # Session fixation protection: login() cycles the session key.
            login(request, user)
            messages.success(request, "You are signed in.")
            return redirect(_safe_redirect_target(request, settings.LOGIN_REDIRECT_URL))
    else:
        form = EmailAuthenticationForm(request)

    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    """Log out (POST only, so it cannot be triggered by a link/GET)."""
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "You have been signed out.")
    return redirect("core:home")


@require_http_methods(["GET"])
def verify_email(request: HttpRequest, token: str) -> HttpResponse:
    """Confirm an email-verification token."""
    user, status = confirm_email_token(token=token, request=request)

    if status == "ok" and user is not None:
        messages.success(request, "Your email address has been verified. Thank you!")
        target = "account:dashboard" if request.user.is_authenticated else "accounts:login"
        return redirect(target)

    if status == "already":
        messages.info(request, "This email address is already verified.")
        target = "account:dashboard" if request.user.is_authenticated else "accounts:login"
        return redirect(target)

    return render(
        request,
        "accounts/verify_email_invalid.html",
        {"reason": status},
        status=400,
    )


@require_POST
@rate_limit(
    scope="resend_verification",
    limit=settings.FORM_RATE_LIMIT_ATTEMPTS,
    window=settings.FORM_RATE_LIMIT_WINDOW,
    by_user=True,
)
def resend_verification(request: HttpRequest) -> HttpResponse:
    """Resend the verification email to the signed-in user."""
    if not request.user.is_authenticated:
        return redirect("accounts:login")

    if request.user.is_email_verified:
        messages.info(request, "Your email address is already verified.")
    else:
        send_email_verification(request.user, request=request)
        messages.success(request, "A fresh verification link is on its way.")
    return redirect("account:dashboard")


@require_http_methods(["GET"])
def lga_options(request: HttpRequest) -> HttpResponse:
    """HTMX endpoint returning LGA ``<option>`` elements for a chosen state."""
    state_id = request.GET.get("state") or request.GET.get("id_state")
    lgas = LGA.objects.none()
    if state_id:
        lgas = LGA.objects.filter(state_id=state_id, is_active=True).order_by("name")
    return render(request, "accounts/partials/lga_options.html", {"lgas": lgas})


class ThrottledPasswordResetView(auth_views.PasswordResetView):
    """Password reset request view with cache-backed rate limiting."""

    def post(self, request, *args, **kwargs):
        identifiers = [f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"]
        email = request.POST.get("email")
        if email:
            identifiers.append(f"email:{email.strip().lower()}")
        for identifier in identifiers:
            if hit(
                "password_reset",
                identifier,
                limit=settings.FORM_RATE_LIMIT_ATTEMPTS,
                window=settings.FORM_RATE_LIMIT_WINDOW,
            ):
                return rate_limit_response(request)
        return super().post(request, *args, **kwargs)

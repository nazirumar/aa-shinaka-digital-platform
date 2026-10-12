"""Authentication URLs (``/accounts/...``)."""

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from django.views.generic import RedirectView

from . import views
from .forms import StyledPasswordResetForm, StyledSetPasswordForm

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path(
        "signup/",
        RedirectView.as_view(pattern_name="accounts:register", permanent=True),
        name="signup",
    ),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    # NOTE: keep the fixed "resend" path before the token catch-all.
    path("verify-email/resend/", views.resend_verification, name="resend_verification"),
    path("verify-email/<str:token>/", views.verify_email, name="verify_email"),
    path("lgas/", views.lga_options, name="lga_options"),
    # Password reset — built on Django's established token/flow.
    path(
        "password-reset/",
        views.ThrottledPasswordResetView.as_view(
            template_name="accounts/password_reset_form.html",
            form_class=StyledPasswordResetForm,
            email_template_name="accounts/email/password_reset_body.txt",
            subject_template_name="accounts/email/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            form_class=StyledSetPasswordForm,
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]

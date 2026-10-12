"""Transactional email helpers (verification, etc.).

Email delivery is configured entirely through settings (SMTP in production, the
console backend in development). No credentials are hardcoded here.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from .tokens import make_email_token


def build_absolute_url(request, path: str) -> str:
    if request is not None:
        return request.build_absolute_uri(path)
    # Fallback for contexts without a request (e.g. management commands).
    return f"https://{settings.ALLOWED_HOSTS[0]}{path}" if settings.ALLOWED_HOSTS else path


def send_email_verification(user, *, request=None) -> None:
    """Send (or resend) the email-verification message to ``user``."""
    token = make_email_token(user)
    verify_path = reverse("accounts:verify_email", kwargs={"token": token})
    context = {
        "user": user,
        "verify_url": build_absolute_url(request, verify_path),
        "expires_hours": settings.EMAIL_VERIFICATION_TIMEOUT // 3600,
    }
    subject = render_to_string("accounts/email/verify_email_subject.txt", context).strip()
    text_body = render_to_string("accounts/email/verify_email_body.txt", context)
    html_body = render_to_string("accounts/email/verify_email_body.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)

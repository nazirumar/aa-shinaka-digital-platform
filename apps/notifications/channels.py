"""Provider-agnostic notification channel adapters.

Only the **email** channel is wired to a real transport. SMS and WhatsApp expose
the same interface but stay inert until a provider is configured through settings
(no credentials are ever hardcoded); calling :meth:`SmsChannel.send` while
unconfigured raises :class:`ChannelNotConfigured` so nothing is silently dropped.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .models import NotificationChannel

logger = logging.getLogger(__name__)


class ChannelNotConfigured(Exception):
    """Raised when a channel has no usable provider configuration."""


class BaseChannel:
    """A delivery channel. Subclasses implement configuration + send."""

    name: str = ""

    def is_configured(self) -> bool:
        return True

    def is_enabled_for(self, preference) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def send(self, notification) -> str:  # pragma: no cover - overridden
        """Deliver ``notification``; return a provider reference (may be empty)."""
        raise NotImplementedError


class InAppChannel(BaseChannel):
    """In-app delivery is intrinsic to the stored ``Notification`` row."""

    name = NotificationChannel.IN_APP

    def is_enabled_for(self, preference) -> bool:
        return bool(preference.in_app_enabled)

    def send(self, notification) -> str:
        return ""


class EmailChannel(BaseChannel):
    """Sends a branded transactional email via the configured mail backend."""

    name = NotificationChannel.EMAIL

    def is_configured(self) -> bool:
        return bool(getattr(settings, "NOTIFICATION_EMAIL_ENABLED", True))

    def is_enabled_for(self, preference) -> bool:
        return bool(preference.email_enabled) and self.is_configured()

    def _company(self):
        try:
            from apps.cms.models import SiteSetting

            return SiteSetting.load()
        except Exception:  # pragma: no cover - CMS not migrated yet
            return None

    def send(self, notification) -> str:
        recipient = notification.recipient
        to = getattr(recipient, "email", "")
        if not to:
            raise ChannelNotConfigured("Recipient has no email address.")
        context = {
            "company": self._company(),
            "notification": notification,
            "heading": notification.title,
            "intro": notification.message,
            "site_url": getattr(settings, "SITE_URL", "") or "",
        }
        text = render_to_string("notifications/email/notification_body.txt", context)
        html = render_to_string("notifications/email/notification_body.html", context)
        message = EmailMultiAlternatives(
            subject=notification.title,
            body=text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to],
        )
        message.attach_alternative(html, "text/html")
        sent = message.send(fail_silently=False)
        if not sent:
            # A backend that reports zero deliveries must never be recorded as
            # success (Task 7: never claim delivery without a provider response).
            raise RuntimeError("Email backend reported no delivery.")
        return ""


class SmsChannel(BaseChannel):
    """Placeholder SMS adapter — inert until a provider is configured."""

    name = NotificationChannel.SMS

    def is_configured(self) -> bool:
        return bool(getattr(settings, "SMS_PROVIDER_URL", "")) and bool(
            getattr(settings, "SMS_PROVIDER_API_KEY", "")
        )

    def is_enabled_for(self, preference) -> bool:
        return bool(preference.sms_enabled) and self.is_configured()

    def send(self, notification) -> str:
        if not self.is_configured():
            raise ChannelNotConfigured("SMS delivery is not configured.")
        # A real provider adapter would be plugged in here. It is intentionally
        # not implemented until an approved provider is chosen.
        raise ChannelNotConfigured("SMS provider adapter is not implemented.")


class WhatsAppChannel(BaseChannel):
    """Placeholder WhatsApp adapter — needs an approved template + consent."""

    name = NotificationChannel.WHATSAPP

    def is_configured(self) -> bool:
        return bool(getattr(settings, "WHATSAPP_PROVIDER_URL", "")) and bool(
            getattr(settings, "WHATSAPP_PROVIDER_API_KEY", "")
        )

    def is_enabled_for(self, preference) -> bool:
        return bool(preference.whatsapp_enabled) and self.is_configured()

    def send(self, notification) -> str:
        if not self.is_configured():
            raise ChannelNotConfigured("WhatsApp delivery is not configured.")
        raise ChannelNotConfigured("WhatsApp provider adapter is not implemented.")


_CHANNELS: dict[str, BaseChannel] = {
    NotificationChannel.IN_APP: InAppChannel(),
    NotificationChannel.EMAIL: EmailChannel(),
    NotificationChannel.SMS: SmsChannel(),
    NotificationChannel.WHATSAPP: WhatsAppChannel(),
}


def get_channel(name: str) -> BaseChannel:
    try:
        return _CHANNELS[name]
    except KeyError as exc:  # pragma: no cover - guarded by choices
        raise ChannelNotConfigured(f"Unknown channel '{name}'.") from exc


def all_channels() -> list[BaseChannel]:
    return list(_CHANNELS.values())


__all__ = [
    "BaseChannel",
    "ChannelNotConfigured",
    "EmailChannel",
    "InAppChannel",
    "SmsChannel",
    "WhatsAppChannel",
    "get_channel",
]

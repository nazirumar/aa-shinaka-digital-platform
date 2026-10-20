"""HTTPS email delivery backend (Resend).

Render's Free web services cannot open outbound SMTP connections on ports 25,
465 or 587, so an HTTPS API is the supported way to deliver verification and
notification email there. This backend uses only the standard library (the
project deliberately avoids a new dependency for a single HTTP endpoint).

Enable it with::

    EMAIL_BACKEND=config.email_backends.ResendEmailBackend
    RESEND_API_KEY=re_...

The key is read from settings/environment and never logged. Failures log only
the exception type and HTTP status — never the recipients, message body or key.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    """Deliver Django email messages through Resend's HTTPS API."""

    def __init__(self, fail_silently: bool = False, **kwargs) -> None:
        super().__init__(fail_silently=fail_silently)
        self.api_key = str(getattr(settings, "RESEND_API_KEY", "") or "")
        self.api_url = str(
            getattr(settings, "RESEND_API_URL", "https://api.resend.com/emails")
            or "https://api.resend.com/emails"
        )
        self.timeout = int(getattr(settings, "RESEND_TIMEOUT", 10) or 10)

    def send_messages(self, email_messages) -> int:
        if not email_messages:
            return 0
        sent = 0
        for message in email_messages:
            if self._send(message):
                sent += 1
        return sent

    # -- internals ---------------------------------------------------------
    def _send(self, message) -> bool:
        recipients = message.recipients()
        if not recipients:
            return False
        if not self.api_key:
            if not self.fail_silently:
                raise ImproperlyConfigured("RESEND_API_KEY is required by ResendEmailBackend.")
            logger.error("Resend email skipped: RESEND_API_KEY is not configured.")
            return False

        payload = self._payload(message)
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
            return True
        except urllib.error.HTTPError as exc:
            # The response body can echo recipient addresses: log the status only.
            logger.warning("Resend rejected a message with HTTP %s.", exc.code)
            if not self.fail_silently:
                raise
            return False
        except Exception as exc:  # noqa: BLE001 - network failures must not leak data
            logger.warning("Resend delivery failed: %s.", type(exc).__name__)
            if not self.fail_silently:
                raise
            return False

    def _payload(self, message) -> dict:
        payload: dict = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(message.to),
            "subject": message.subject,
            "text": message.body,
        }
        if message.cc:
            payload["cc"] = list(message.cc)
        if message.bcc:
            payload["bcc"] = list(message.bcc)
        if message.reply_to:
            payload["reply_to"] = list(message.reply_to)
        if message.extra_headers:
            payload["headers"] = dict(message.extra_headers)

        # Only EmailMultiAlternatives carries `.alternatives`; a plain
        # EmailMessage does not.
        for alternative, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html" and "html" not in payload:
                payload["html"] = alternative

        attachments = []
        for filename, content, mimetype in message.attachments:
            if isinstance(content, str):
                content = content.encode("utf-8")
            attachments.append(
                {
                    "filename": filename,
                    "content": base64.b64encode(content).decode("ascii"),
                    **({"content_type": mimetype} if mimetype else {}),
                }
            )
        if attachments:
            payload["attachments"] = attachments
        return payload

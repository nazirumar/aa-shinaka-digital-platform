"""Paystack API boundary.

Everything that talks to Paystack lives here so the rest of the codebase never
handles provider credentials directly. Amounts are converted to a provider's
smallest currency unit **only** here (kobo for NGN) and back to ``Decimal`` on
the way in.

Security notes:

* The secret key is read from settings only — never logged, never rendered.
* Webhook signatures are verified with HMAC-SHA512 over the **raw** request body
  using the secret key (Paystack does not use a separate webhook secret unless
  one is explicitly configured). See ``docs/ARCHITECTURE.md``.
* Errors raised are :class:`PaystackError`; network/JSON failures never leak the
  key or the raw response to the caller.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)

KOBO_PER_UNIT = Decimal("100")


class PaystackError(Exception):
    """A safe, non-secret-bearing error raised for any Paystack failure."""

    def __init__(self, message: str, *, code: str = "error", status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _is_live_key() -> bool:
    """A live (money-moving) Paystack key, as opposed to a test key."""
    key = _secret_key()
    return key.startswith("sk_live_") or key.startswith("pk_live_")


def live_key_blocked() -> bool:
    """True when a *live* key is configured but live mode is switched off.

    This is the Phase 13 fail-closed guard: the platform ships "test mode only",
    so a live key left in the environment must never move real money until the
    owner explicitly sets ``PAYSTACK_LIVE_MODE=True`` (a launch gate).
    """
    return _is_live_key() and not bool(getattr(settings, "PAYSTACK_LIVE_MODE", False))


def is_enabled() -> bool:
    """Whether Paystack calls are configured and switched on.

    Disabled (fail closed) if a live key is present while live mode is off, even
    when ``PAYSTACK_ENABLED`` is true — a misconfiguration can never charge a
    real card by accident.
    """
    if live_key_blocked():
        logger.warning(
            "A live Paystack key is configured but PAYSTACK_LIVE_MODE is off; "
            "payments are disabled until launch is explicitly approved."
        )
        return False
    return bool(getattr(settings, "PAYSTACK_ENABLED", False)) and bool(
        getattr(settings, "PAYSTACK_SECRET_KEY", "")
    )


def _secret_key() -> str:
    return getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""


def _api_base() -> str:
    return getattr(settings, "PAYSTACK_API_BASE_URL", "https://api.paystack.co").rstrip("/")


def _timeout() -> float:
    return float(getattr(settings, "PAYSTACK_TIMEOUT", 20))


def to_kobo(amount) -> int:
    """Convert a ``Decimal`` amount to the smallest unit (kobo) as an int."""
    return int((Decimal(str(amount)) * Decimal("100")).to_integral_value())


def from_kobo(value) -> Decimal:
    """Convert a smallest-unit integer back to a 2dp ``Decimal``."""
    return (Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"))


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Constant-time verification of the ``x-paystack-signature`` header."""
    secret = getattr(settings, "PAYSTACK_WEBHOOK_SECRET", "") or _secret_key()
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _provider_message(raw: bytes) -> str:
    try:
        parsed = json.loads(raw or b"{}")
    except ValueError:
        return ""
    message = parsed.get("message") if isinstance(parsed, dict) else None
    return str(message) if message else ""


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    """Perform a signed request and return the ``data`` object.

    Raises :class:`PaystackError` for configuration, transport, HTTP and
    provider-level errors. The response body is never logged verbatim.
    """
    secret = _secret_key()
    if not secret:
        raise PaystackError("Paystack is not configured.", code="not_configured")
    if live_key_blocked():
        # Defence in depth: never send a live key unless launch is approved.
        raise PaystackError(
            "Live Paystack mode is disabled pending launch approval.",
            code="live_mode_disabled",
        )

    url = f"{_api_base()}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {secret}")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")

    try:
        timeout = float(getattr(settings, "PAYSTACK_TIMEOUT", 20))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        message = _provider_message(raw) or f"Paystack returned HTTP {exc.code}."
        logger.warning("Paystack HTTP error on %s: %s", path, exc.code)
        raise PaystackError(message, code="http_error", status_code=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Paystack transport error on %s: %s", path, type(exc).__name__)
        raise PaystackError(
            "Could not reach Paystack. Please try again.", code="network_error"
        ) from exc

    try:
        parsed = json.loads(body or b"{}")
    except ValueError as exc:
        raise PaystackError("Invalid response from Paystack.", code="bad_response") from exc

    if not isinstance(parsed, dict) or not parsed.get("status"):
        message = _provider_message(body) or "Paystack rejected the request."
        raise PaystackError(message, code="provider_error")

    return parsed.get("data") or {}


# ---------------------------------------------------------------------------
# Transaction operations
# ---------------------------------------------------------------------------


def initialize_transaction(
    *,
    email: str,
    amount_kobo: int,
    currency: str,
    reference: str,
    callback_url: str = "",
    metadata: dict | None = None,
    channels: list[str] | None = None,
) -> dict:
    """Create a hosted checkout and return ``{authorization_url, access_code, reference}``."""
    payload: dict = {
        "email": email,
        "amount": int(amount_kobo),
        "currency": currency,
        "reference": reference,
    }
    if callback_url:
        payload["callback_url"] = callback_url
    if metadata:
        payload["metadata"] = metadata
    if channels:
        payload["channels"] = list(channels)
    return _request("POST", "/transaction/initialize", payload)


def verify_transaction(reference: str) -> dict:
    """Authoritatively verify a transaction by reference (server-side)."""
    safe = urllib.parse.quote(str(reference), safe="")
    return _request("GET", f"/transaction/verify/{safe}")


def refund_transaction(
    *, transaction: str, amount_kobo: int | None = None, merchant_note: str = ""
) -> dict:
    """Initiate a full (amount omitted) or partial provider refund."""
    payload: dict = {"transaction": str(transaction)}
    if amount_kobo is not None:
        payload["amount"] = int(amount_kobo)
    if merchant_note:
        payload["merchant_note"] = merchant_note[:200]
    return _request("POST", "/refund", payload)


__all__ = [
    "PaystackError",
    "from_kobo",
    "initialize_transaction",
    "is_enabled",
    "live_key_blocked",
    "refund_transaction",
    "to_kobo",
    "verify_transaction",
    "verify_webhook_signature",
]

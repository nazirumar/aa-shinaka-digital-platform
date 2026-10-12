"""Audit logging helper.

Audit records are created by a single helper so every sensitive operation logs
consistently and **never** stores secrets. The ``AuditLog`` model lives in
``apps.dashboard``; it is imported lazily to keep app import order simple.
"""

from __future__ import annotations

from typing import Any

# Keys that must never be written to an audit record.
_REDACTED_KEYS = frozenset(
    {
        "password",
        "password1",
        "password2",
        "new_password",
        "new_password1",
        "new_password2",
        "current_password",
        "token",
        "secret",
        "secret_key",
        "api_key",
        "authorization",
        "otp",
        "raw_payload",
    }
)

REDACTED = "[redacted]"


def redact(data: Any) -> Any:
    """Return a JSON-safe copy of ``data`` with sensitive values removed."""
    if isinstance(data, dict):
        return {
            key: REDACTED if str(key).lower() in _REDACTED_KEYS else redact(value)
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [redact(item) for item in data]
    if isinstance(data, (str, int, float, bool)) or data is None:
        return data
    return str(data)


def _request_meta(request) -> tuple[str | None, str]:
    if request is None:
        return None, ""
    ip = request.META.get("REMOTE_ADDR")
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    return ip, request.META.get("HTTP_USER_AGENT", "")[:300]


def record_audit(
    *,
    actor,
    action: str,
    target: Any = None,
    before: dict | None = None,
    after: dict | None = None,
    request=None,
    note: str = "",
):
    """Create an ``AuditLog`` entry for a sensitive operation.

    ``actor`` may be ``None`` or an anonymous user; it is stored only when it is
    an authenticated user. ``before``/``after`` are redacted before saving.
    """
    from apps.dashboard.models import AuditLog

    safe_actor = actor if getattr(actor, "is_authenticated", False) else None
    ip_address, user_agent = _request_meta(request)

    target_type = ""
    target_id = ""
    if target is not None:
        if hasattr(target, "_meta"):
            target_type = target._meta.label
            target_id = str(getattr(target, "pk", "") or "")
        else:
            target_type = type(target).__name__
            target_id = str(target)

    return AuditLog.objects.create(
        actor=safe_actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=redact(before) if before is not None else None,
        after=redact(after) if after is not None else None,
        note=note[:500],
        ip_address=ip_address or None,
        user_agent=user_agent,
    )

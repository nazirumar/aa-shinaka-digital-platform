"""Expose the signed-in customer's unread-notification count to every template."""

from __future__ import annotations


def unread_notifications(request) -> dict:
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {"unread_notifications_count": 0}
    try:
        from .services import unread_count

        return {"unread_notifications_count": unread_count(user)}
    except Exception:  # pragma: no cover - never break page rendering
        return {"unread_notifications_count": 0}

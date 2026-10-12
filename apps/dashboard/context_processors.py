"""Template context processors."""

from __future__ import annotations


def notifications(request):
    """Expose recent real activity for the staff notification area.

    Only runs for authenticated staff, and degrades to an empty list if the
    audit table is not available yet.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False) or not user.is_staff:
        return {}
    try:
        from .selectors import recent_activity

        return {"notifications": list(recent_activity(limit=6))}
    except Exception:  # noqa: BLE001 - never break page rendering
        return {"notifications": []}

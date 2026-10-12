"""Signal receivers for the order app."""

from __future__ import annotations

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def merge_guest_cart_on_login(sender, request, user, **kwargs):
    """Merge any active guest cart into the customer's cart after login.

    Django rotates the session key *before* it fires this signal, so the
    pre-login key is gone. The cart is therefore identified by the ``cart_id``
    stored in the session (session data survives the rotation). Failures must
    never block a login.
    """
    session = getattr(request, "session", None)
    if session is None:
        return
    from . import services

    try:
        services.merge_guest_cart(
            user,
            cart_id=session.get("cart_id"),
            session_key=session.session_key,
        )
    except Exception:  # pragma: no cover - defensive: login must still succeed
        pass
    else:
        session.pop("cart_id", None)

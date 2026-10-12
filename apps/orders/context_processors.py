"""Template context processors for the order app."""

from __future__ import annotations

from . import services


def cart_summary(request):
    """Expose the active cart's item count for the site header badge."""
    try:
        cart = services.get_active_cart(request)
    except Exception:  # pragma: no cover - defensive: never break page rendering
        return {"cart_item_count": 0}
    if cart is None:
        return {"cart_item_count": 0}
    return {"cart_item_count": cart.items.count()}

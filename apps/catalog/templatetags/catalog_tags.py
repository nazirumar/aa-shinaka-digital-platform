"""Template helpers for the catalogue (money, status badges)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

CURRENCY_SYMBOLS = {"NGN": "₦", "USD": "$", "EUR": "€", "GBP": "£"}

STATUS_CLASSES = {
    "draft": "bg-stone-100 text-stone-600",
    "published": "bg-leaf/15 text-leaf",
    "active": "bg-leaf/10 text-leaf",
    "out_of_stock": "bg-amber-100 text-amber-800",
    "archived": "bg-stone-200 text-stone-600",
}


@register.filter
def money(value, currency: str = "NGN"):
    """Format a Decimal as currency, e.g. ``₦12,500.00``. Never hardcoded data."""
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    symbol = "₦" if currency == "NGN" else f"{currency} "
    return f"{symbol}{amount:,.2f}"


@register.filter
def status_class(value) -> str:
    """Return a Tailwind badge class for a status/stock value."""
    return STATUS_CLASSES.get(str(value), "bg-stone-100 text-stone-600")


@register.filter
def stock_state(listing) -> str:
    """Return ``out``, ``low`` or ``in`` for a listing's availability."""
    if not getattr(listing, "in_stock", False):
        return "out"
    if getattr(listing, "low_stock", False):
        return "low"
    return "in"


@register.filter
def decimal_str(value):
    """Render a quantity without trailing zeros (e.g. ``2.5`` not ``2.500``)."""
    try:
        return format(Decimal(value).normalize(), "f")
    except (InvalidOperation, TypeError, ValueError):
        return value

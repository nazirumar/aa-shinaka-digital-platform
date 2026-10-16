"""Validated filters and business-timezone date-range resolution (Phase 11).

Only allow-listed filter names are read; invalid values degrade to their default
rather than erroring. Date windows are converted to *aware* datetimes in the
configured business timezone and applied as a half-open ``[start, end)`` range so
a report never double-counts or drops a boundary row.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.utils import timezone

#: Named date presets offered in the UI. ``custom`` reads explicit dates.
PRESETS: dict[str, str] = {
    "today": "Today",
    "last_7_days": "Last 7 days",
    "last_30_days": "Last 30 days",
    "this_month": "This month",
    "this_year": "This year",
    "all_time": "All time",
    "custom": "Custom range",
}
DEFAULT_PRESET = "last_30_days"


def resolve_preset(preset: str, *, today=None) -> tuple[object, object]:
    """Return inclusive ``(date_from, date_to)`` for a named preset."""
    today = today or timezone.localdate()
    if preset == "today":
        return today, today
    if preset == "last_7_days":
        return today - timedelta(days=6), today
    if preset == "this_month":
        return today.replace(day=1), today
    if preset == "this_year":
        return today.replace(month=1, day=1), today
    if preset in {"all_time", "custom"}:
        return None, None
    # Default: last 30 days (inclusive of today).
    return today - timedelta(days=29), today


def parse_date(value):
    """Parse an ISO date string; return ``None`` for anything invalid."""
    if not value:
        return None
    if not isinstance(value, str):
        return value
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None


def day_start(day):
    """Aware datetime at the start of ``day`` in the business timezone."""
    if day is None:
        return None
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


def day_end_exclusive(day):
    """Aware datetime at the start of the day after ``day`` (exclusive bound)."""
    start = day_start(day)
    return None if start is None else start + timedelta(days=1)


class ReportFilters:
    """Validated, allow-listed report filters (JSON-safe)."""

    __slots__ = (
        "preset",
        "date_from",
        "date_to",
        "status",
        "division",
        "product_id",
        "warehouse_id",
        "state_id",
        "lga_id",
        "destination_id",
        "currency",
    )

    def __init__(
        self,
        *,
        preset: str = DEFAULT_PRESET,
        date_from=None,
        date_to=None,
        status: str = "",
        division: str = "",
        product_id: str = "",
        warehouse_id: str = "",
        state_id: str = "",
        lga_id: str = "",
        destination_id: str = "",
        currency: str = "",
    ) -> None:
        if preset not in PRESETS:
            preset = DEFAULT_PRESET
        self.preset = preset
        if preset == "custom":
            self.date_from = parse_date(date_from)
            self.date_to = parse_date(date_to)
        else:
            self.date_from, self.date_to = resolve_preset(preset)
        self.status = (status or "").strip()[:40]
        self.division = (division or "").strip()[:40]
        self.product_id = (product_id or "").strip()[:36]
        self.warehouse_id = (warehouse_id or "").strip()[:36]
        self.state_id = (state_id or "").strip()[:36]
        self.lga_id = (lga_id or "").strip()[:36]
        self.destination_id = (destination_id or "").strip()[:36]
        self.currency = (currency or "").strip().upper()[:3]

    # -- serialisation ------------------------------------------------------
    def as_dict(self) -> dict:
        return {
            "preset": self.preset,
            "date_from": self.date_from.isoformat() if self.date_from else "",
            "date_to": self.date_to.isoformat() if self.date_to else "",
            "status": self.status,
            "division": self.division,
            "product_id": self.product_id,
            "warehouse_id": self.warehouse_id,
            "state_id": self.state_id,
            "lga_id": self.lga_id,
            "destination_id": self.destination_id,
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, data) -> ReportFilters:
        data = data or {}
        return cls(
            preset=data.get("preset", DEFAULT_PRESET),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            status=data.get("status", ""),
            division=data.get("division", ""),
            product_id=data.get("product_id", ""),
            warehouse_id=data.get("warehouse_id", ""),
            state_id=data.get("state_id", ""),
            lga_id=data.get("lga_id", ""),
            destination_id=data.get("destination_id", ""),
            currency=data.get("currency", ""),
        )

    @classmethod
    def from_request(cls, params) -> ReportFilters:
        """Build from a QueryDict/POST dict (unknown keys ignored)."""
        return cls(
            preset=params.get("preset", DEFAULT_PRESET),
            date_from=params.get("date_from"),
            date_to=params.get("date_to"),
            status=params.get("status", ""),
            division=params.get("division", ""),
            product_id=params.get("product_id", ""),
            warehouse_id=params.get("warehouse_id", ""),
            state_id=params.get("state_id", ""),
            lga_id=params.get("lga_id", ""),
            destination_id=params.get("destination_id", ""),
            currency=params.get("currency", ""),
        )

    # -- date bounds --------------------------------------------------------
    def start(self):
        return day_start(self.date_from) if self.date_from else None

    def end(self):
        return day_end_exclusive(self.date_to) if self.date_to else None

    def contains(self, model_field: str, queryset):
        """Apply the date window to ``queryset`` on ``model_field``."""
        start, end = self.start(), self.end()
        if start is not None:
            queryset = queryset.filter(**{f"{model_field}__gte": start})
        if end is not None:
            queryset = queryset.filter(**{f"{model_field}__lt": end})
        return queryset

    def label(self) -> str:
        if self.date_from and self.date_to:
            return f"{self.date_from.isoformat()} → {self.date_to.isoformat()}"
        return "All time"

    def replace(self, **kwargs) -> ReportFilters:
        data = self.as_dict()
        data.update(kwargs)
        return ReportFilters.from_dict(data)


#: Filter names accepted by the report builder (allow-list).
FILTER_KEYS = frozenset(
    {
        "preset",
        "date_from",
        "date_to",
        "status",
        "division",
        "product_id",
        "warehouse_id",
        "state_id",
        "lga_id",
        "destination_id",
        "currency",
    }
)


__all__ = [
    "DEFAULT_PRESET",
    "FILTER_KEYS",
    "PRESETS",
    "ReportFilters",
    "day_end_exclusive",
    "day_start",
    "parse_date",
    "resolve_preset",
]

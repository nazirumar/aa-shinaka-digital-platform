"""Chart.js payload builders (Phase 11 — Task 11).

Charts are rendered from **server-computed JSON** embedded with Django's
``json_script`` filter (never string-interpolated into JavaScript). Each builder
returns a plain, JSON-safe dict::

    {"type": "bar", "labels": [...], "datasets": [{"label": ..., "data": [...]}]}

With no data the payload is an empty chart so the template can show a clean "no
data for this period" state rather than inventing or extrapolating values. Money
is converted to ``float`` **only** for chart geometry; the exact ``Decimal`` is
always shown in the accompanying table.
"""

from __future__ import annotations

from decimal import Decimal

from . import selectors as sel


def _num(value):
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return float(value)
    return value


def _payload(chart_type: str, labels, datasets) -> dict:
    return {
        "type": chart_type,
        "labels": list(labels),
        "datasets": datasets,
        "empty": not labels,
    }


def bar(labels, data, *, label: str = "") -> dict:
    return _payload("bar", labels, [{"label": label, "data": [_num(v) for v in data]}])


def line(labels, data, *, label: str = "", fill: bool = False) -> dict:
    return _payload(
        "line",
        labels,
        [{"label": label, "data": [_num(v) for v in data], "fill": fill, "tension": 0.3}],
    )


def doughnut(labels, data, *, label: str = "") -> dict:
    return _payload("doughnut", labels, [{"label": label, "data": [_num(v) for v in data]}])


def _titles(rows, key: str) -> list[str]:
    return [str(row.get(key) or "—").replace("_", " ").title() for row in rows]


# ---------------------------------------------------------------------------
# Per-page chart sets
# ---------------------------------------------------------------------------


def executive_charts(*, filters) -> dict:
    trend = sel.receipts_by_day(filters=filters)
    by_currency = sel.receipts_by_currency(filters=filters)
    return {
        "receipts_trend": line(
            [row["day"].strftime("%Y-%m-%d") for row in trend],
            [row["total"] for row in trend],
            label="Verified receipts",
            fill=True,
        ),
        "receipts_by_currency": doughnut(
            [row["currency"] for row in by_currency],
            [row["total"] for row in by_currency],
            label="Receipts",
        ),
    }


def sales_charts(*, filters) -> dict:
    trend = sel.sales_trend(filters=filters)
    status = sel.order_status_distribution(filters=filters)
    countries = sel.sales_by_delivery_state(filters=filters)
    return {
        "trend": line(
            [row["day"].strftime("%Y-%m-%d") for row in trend],
            [row["orders"] for row in trend],
            label="Orders",
        ),
        "status": doughnut(_titles(status, "status"), [r["count"] for r in status], label="Orders"),
        "delivery_states": bar(
            [row["state"] for row in countries],
            [row["orders"] for row in countries],
            label="Orders",
        ),
    }


def finance_charts(*, filters) -> dict:
    day_rows = sel.receipts_by_day(filters=filters)
    method_rows = sel.receipts_by_method(filters=filters)
    currency_rows = sel.receipts_by_currency(filters=filters)
    return {
        "receipts_trend": line(
            [row["day"].strftime("%Y-%m-%d") for row in day_rows],
            [row["total"] for row in day_rows],
            label="Verified receipts",
            fill=True,
        ),
        "by_method": doughnut(
            [str(row["method"]).replace("_", " ").title() for row in method_rows],
            [row["total"] for row in method_rows],
            label="Receipts",
        ),
        "by_currency": doughnut(
            [row["currency"] for row in currency_rows],
            [row["total"] for row in currency_rows],
            label="Receipts",
        ),
    }


def inventory_charts(*, filters) -> dict:
    by_warehouse = sel.stock_by_warehouse()
    kind_rows = sel.movements_by_kind(filters=filters)
    trend = sel.movements_trend(filters=filters)
    return {
        "by_warehouse": bar(
            [row["warehouse"] for row in by_warehouse],
            [row["on_hand"] for row in by_warehouse],
            label="On hand",
        ),
        "movements_by_kind": doughnut(
            _titles(kind_rows, "kind"), [row["count"] for row in kind_rows], label="Movements"
        ),
        "movements_trend": line(
            [row["day"].strftime("%Y-%m-%d") for row in trend],
            [row["count"] for row in trend],
            label="Movements",
        ),
    }


def services_charts(*, filters) -> dict:
    metrics = sel.services_metrics(filters=filters)
    return {
        "by_division": doughnut(
            _titles(metrics["by_division"], "service_type"),
            [row["count"] for row in metrics["by_division"]],
            label="Requests",
        ),
        "farm_status": bar(
            _titles(metrics["farm_projects_by_status"], "status"),
            [row["count"] for row in metrics["farm_projects_by_status"]],
            label="Projects",
        ),
        "storage_utilization": bar(
            [row["facility"] for row in metrics["storage_utilization"]],
            [_num(row["percent"]) for row in metrics["storage_utilization"]],
            label="% allocated",
        ),
    }


def export_charts(*, filters) -> dict:
    metrics = sel.export_metrics(filters=filters)
    destinations = [
        (row["destination__country__name"] or row["destination__country_code"] or "—")
        for row in metrics["enquiries_by_destination"]
    ]
    return {
        "enquiries_by_destination": bar(
            destinations,
            [row["count"] for row in metrics["enquiries_by_destination"]],
            label="Enquiries",
        ),
        "orders_by_status": doughnut(
            _titles(metrics["orders_by_status"], "status"),
            [row["count"] for row in metrics["orders_by_status"]],
            label="Orders",
        ),
        "compliance": doughnut(
            _titles(metrics["compliance_by_status"], "compliance_status"),
            [row["count"] for row in metrics["compliance_by_status"]],
            label="Orders",
        ),
    }


def training_charts(*, filters) -> dict:
    metrics = sel.training_metrics(filters=filters)
    return {
        "enrollments_by_status": doughnut(
            _titles(metrics["enrollments_by_status"], "status"),
            [row["count"] for row in metrics["enrollments_by_status"]],
            label="Enrollments",
        ),
        "course_popularity": bar(
            [row["course"] or "—" for row in metrics["course_popularity"]],
            [row["total"] for row in metrics["course_popularity"]],
            label="Enrollments",
        ),
    }


def support_charts(*, filters) -> dict:
    metrics = sel.support_analytics(filters=filters)
    return {
        "by_status": doughnut(
            _titles(metrics["by_status"], "status"),
            [row["count"] for row in metrics["by_status"]],
            label="Tickets",
        ),
        "by_priority": doughnut(
            _titles(metrics["by_priority"], "priority"),
            [row["count"] for row in metrics["by_priority"]],
            label="Tickets",
        ),
        "by_category": bar(
            _titles(metrics["by_category"], "category"),
            [row["count"] for row in metrics["by_category"]],
            label="Tickets",
        ),
    }


def customers_charts(*, filters) -> dict:
    metrics = sel.customer_metrics(filters=filters)
    return {
        "customer_mix": doughnut(
            ["New in period", "Repeat purchasers", "Training participants", "Service users"],
            [
                metrics["new_customers"],
                metrics["repeat_customers"],
                metrics["training_participants"],
                metrics["service_usage_customers"],
            ],
            label="Customers",
        ),
    }


__all__ = [
    "bar",
    "customers_charts",
    "doughnut",
    "executive_charts",
    "export_charts",
    "finance_charts",
    "inventory_charts",
    "line",
    "services_charts",
    "support_charts",
    "training_charts",
]

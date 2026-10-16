"""The controlled report registry (Phase 11 — Tasks 12, 13, 15).

Reports are **code-defined and allow-listed**. A request can only ever name a key
from :data:`REPORT_DEFINITIONS`; there is no way to supply SQL, a model path or an
arbitrary field list. Filters are typed and validated in
:mod:`apps.analytics.filters`, and money columns are additionally gated behind the
``analytics.finance`` capability so a report cannot leak financial detail to a
user who only holds ``reports.build``.

Customer identity (name, email, phone, address) is deliberately **absent** from
every report — analytics are aggregate/operational by default.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, Q

from apps.catalog.models import StockBalance, StockMovement
from apps.export.models import ExportEnquiry, ExportOrder, ExportShipment
from apps.orders.payment_models import Invoice, InvoiceState, Refund, RefundState
from apps.services.models import ServiceRequest
from apps.support.models import SupportTicket
from apps.training.models import AttendanceRecord, AttendanceStatus, Enrollment

from . import selectors as sel

MONEY = "money"
NUMBER = "number"
TEXT = "text"
DATE = "date"
DATETIME = "datetime"
PERCENT = "percent"


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = TEXT
    finance: bool = False


@dataclass(frozen=True)
class ReportDefinition:
    key: str
    label: str
    description: str
    division: str
    columns: tuple[Column, ...]
    builder: Callable[..., list[dict]]
    allowed_filters: tuple[str, ...] = ("preset", "date_from", "date_to")
    is_financial: bool = False
    base_capability: str = "reports.build"

    @property
    def money_columns(self) -> tuple[Column, ...]:
        return tuple(c for c in self.columns if c.kind in (MONEY, PERCENT))


# ---------------------------------------------------------------------------
# Row builders — each returns a list of dicts keyed by ``Column.key``
# ---------------------------------------------------------------------------


def _sales_orders(filters) -> list[dict]:
    rows = sel.counted_orders(filters).values(
        "number", "created_at", "status", "currency", "grand_total"
    )
    return [
        {
            "order": r["number"],
            "placed_at": r["created_at"],
            "status": r["status"],
            "currency": r["currency"],
            "grand_total": r["grand_total"],
        }
        for r in rows
    ]


def _sales_by_product(filters) -> list[dict]:
    return [
        {
            "product": r["product_name"],
            "quantity": r["quantity"],
            "orders": r["orders"],
            "value": r["value"],
        }
        for r in sel.top_products(filters=filters, limit=1000)
    ]


def _sales_by_category(filters) -> list[dict]:
    return [
        {"category": r["category"], "quantity": r["quantity"], "value": r["value"]}
        for r in sel.top_categories(filters=filters, limit=1000)
    ]


def _sales_by_origin(filters) -> list[dict]:
    out = []
    for r in sel.sales_by_origin_state(filters=filters, limit=1000):
        out.append(
            {
                "origin_state": r["state"],
                "origin_lga": "",
                "quantity": r["quantity"],
                "value": r["value"],
            }
        )
    for r in sel.sales_by_origin_lga(filters=filters, limit=1000):
        out.append(
            {
                "origin_state": "",
                "origin_lga": r["lga"],
                "quantity": r["quantity"],
                "value": r["value"],
            }
        )
    return out


def _sales_by_destination(filters) -> list[dict]:
    return [
        {"state": r["state"], "orders": r["orders"], "value": r["value"]}
        for r in sel.sales_by_delivery_state(filters=filters, limit=1000)
    ]


def _finance_receipts(filters) -> list[dict]:
    rows = sel.settled_payments(filters).values(
        "reference", "provider", "method", "currency", "verified_amount", "verified_at", "status"
    )
    return [
        {
            "reference": r["reference"],
            "provider": r["provider"],
            "method": r["method"] or "—",
            "currency": r["currency"],
            "amount": r["verified_amount"],
            "verified_at": r["verified_at"],
            "status": r["status"],
        }
        for r in rows
    ]


def _finance_refunds(filters) -> list[dict]:
    qs = Refund.objects.filter(status=RefundState.COMPLETED).select_related("payment")
    if filters is not None:
        if filters.start():
            qs = qs.filter(processed_at__gte=filters.start())
        if filters.end():
            qs = qs.filter(processed_at__lt=filters.end())
    return [
        {
            "reference": r.reference,
            "payment": r.payment.reference,
            "amount": r.amount,
            "currency": r.payment.currency,
            "processed_at": r.processed_at,
            "status": r.get_status_display(),
        }
        for r in qs
    ]


def _finance_invoices(filters) -> list[dict]:
    qs = Invoice.objects.filter(status__in=[InvoiceState.UNPAID, InvoiceState.PARTIALLY_PAID])
    if filters is not None and filters.start():
        qs = qs.filter(created_at__gte=filters.start())
    if filters is not None and filters.end():
        qs = qs.filter(created_at__lt=filters.end())
    return [
        {
            "invoice": r.number,
            "status": r.get_status_display(),
            "currency": r.currency,
            "total": r.total,
            "due_at": r.due_at,
        }
        for r in qs
    ]


def _inventory_stock(filters) -> list[dict]:
    qs = StockBalance.objects.all().select_related(
        "listing__product", "listing__package_unit", "warehouse"
    )
    if filters is not None and filters.warehouse_id:
        qs = qs.filter(warehouse_id=filters.warehouse_id)
    if filters is not None and filters.product_id:
        qs = qs.filter(listing__product_id=filters.product_id)
    return [
        {
            "product": r.listing.product.name,
            "packaging": r.listing.packaging,
            "warehouse": r.warehouse.name,
            "on_hand": r.on_hand,
            "reserved": r.reserved,
            "available": r.available,
            "unit": r.listing.package_unit.name if r.listing.package_unit_id else "—",
        }
        for r in qs
    ]


def _inventory_low_stock(filters) -> list[dict]:
    return [
        {
            "product": r["product"],
            "state": r["state"],
            "available": r["available"],
            "threshold": r["threshold"],
            "unit": r["unit"],
        }
        for r in sel.low_stock_listings(limit=1000)
    ]


def _inventory_movements(filters) -> list[dict]:
    qs = sel.count_filtered(
        StockMovement.objects.all().select_related("listing__product", "warehouse"), filters
    )
    return [
        {
            "movement_at": r.created_at,
            "product": r.listing.product.name,
            "kind": r.get_kind_display(),
            "quantity_delta": r.quantity_delta,
            "balance_after": r.balance_after,
            "warehouse": r.warehouse.name if r.warehouse_id else "—",
            "reference": r.reference,
        }
        for r in qs
    ]


def _services_requests(filters) -> list[dict]:
    qs = sel.count_filtered(ServiceRequest.objects.all(), filters)
    if filters is not None and filters.status:
        qs = qs.filter(status=filters.status)
    if filters is not None and filters.division:
        qs = qs.filter(service_type=filters.division)
    return [
        {
            "reference": r.reference,
            "service_type": r.get_service_type_display(),
            "status": r.get_status_display(),
            "state": r.state.name if r.state_id else "—",
            "created_at": r.created_at,
        }
        for r in qs
    ]


def _storage_utilization(filters) -> list[dict]:
    return [
        {
            "facility": r["facility"],
            "unit": r["unit"],
            "allocated": r["allocated"],
            "capacity": r["capacity"],
            "percent": r["percent"],
        }
        for r in sel.storage_utilization()
    ]


def _export_enquiries(filters) -> list[dict]:
    qs = sel.count_filtered(
        ExportEnquiry.objects.all().select_related("destination__country"), filters
    )
    if filters is not None and filters.destination_id:
        qs = qs.filter(destination_id=filters.destination_id)
    if filters is not None and filters.status:
        qs = qs.filter(status=filters.status)
    return [
        {
            "reference": r.reference,
            "destination": r.destination.country.name if r.destination_id else "—",
            "status": r.get_status_display(),
            "priority": r.priority,
            "created_at": r.created_at,
        }
        for r in qs
    ]


def _export_orders(filters) -> list[dict]:
    qs = sel.count_filtered(
        ExportOrder.objects.all().select_related("destination__country"), filters
    )
    if filters is not None and filters.destination_id:
        qs = qs.filter(destination_id=filters.destination_id)
    return [
        {
            "reference": r.reference,
            "destination": r.destination.country.name if r.destination_id else "—",
            "status": r.get_status_display(),
            "compliance": r.get_compliance_status_display(),
            "currency": r.currency,
            "total": r.total,
            "created_at": r.created_at,
        }
        for r in qs
    ]


def _export_shipments(filters) -> list[dict]:
    qs = sel.count_filtered(ExportShipment.objects.all(), filters)
    return [
        {
            "reference": r.reference,
            "origin": r.origin,
            "destination": r.destination,
            "status": r.get_status_display(),
            "departure_date": r.departure_date,
            "estimated_arrival": r.estimated_arrival,
            "actual_arrival": r.actual_arrival,
        }
        for r in qs
    ]


def _training_enrollments(filters) -> list[dict]:
    qs = sel.count_filtered(Enrollment.objects.all().select_related("session__course"), filters)
    if filters is not None and filters.status:
        qs = qs.filter(status=filters.status)
    return [
        {
            "reference": r.reference,
            "course": r.session.course.title if r.session_id else "—",
            "status": r.get_status_display(),
            "payment_status": r.get_payment_status_display(),
            "created_at": r.created_at,
        }
        for r in qs
    ]


def _training_attendance(filters) -> list[dict]:
    qs = sel.count_filtered(
        AttendanceRecord.objects.all().select_related("attendance_session__session__course"),
        filters,
    )
    return [
        {
            "course": r["attendance_session__session__course__title"] or "—",
            "total": r["total"],
            "attended": r["attended"],
            "rate": sel._percent(r["attended"], r["total"]),
        }
        for r in qs.values("attendance_session__session__course__title")
        .annotate(
            total=Count("id"),
            attended=Count(
                "id", filter=Q(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE])
            ),
        )
        .order_by("-total")
    ]


def _customers_new_by_month(filters) -> list[dict]:
    return sel.customers_new_by_month(filters=filters)


def _support_tickets(filters) -> list[dict]:
    qs = sel.count_filtered(SupportTicket.objects.all(), filters)
    if filters is not None and filters.status:
        qs = qs.filter(status=filters.status)
    return [
        {
            "reference": r.reference,
            "category": r.get_category_display(),
            "priority": r.get_priority_display(),
            "status": r.get_status_display(),
            "created_at": r.created_at,
            "resolved_at": r.resolved_at,
        }
        for r in qs
    ]


def _support_agents(filters) -> list[dict]:
    qs = sel.count_filtered(SupportTicket.objects.filter(assigned_to__isnull=False), filters)
    return [
        {"agent": r["assigned_to__email"], "tickets": r["count"]}
        for r in qs.values("assigned_to__email").annotate(count=Count("id")).order_by("-count")
    ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _c(key, label, kind=TEXT, finance=False) -> Column:
    return Column(key, label, kind, finance)


REPORT_DEFINITIONS: dict[str, ReportDefinition] = {
    "sales_orders": ReportDefinition(
        key="sales_orders",
        label="Sales orders",
        description="Every counted sales order (cancelled/expired excluded), one row per order.",
        division="sales",
        columns=(
            _c("order", "Order"),
            _c("placed_at", "Placed", DATETIME),
            _c("status", "Status"),
            _c("currency", "Currency"),
            _c("grand_total", "Grand total", MONEY, finance=True),
        ),
        builder=_sales_orders,
        is_financial=True,
    ),
    "sales_by_product": ReportDefinition(
        key="sales_by_product",
        label="Sales by product",
        description="Sold quantity and value per product (from order-line snapshots).",
        division="sales",
        columns=(
            _c("product", "Product"),
            _c("quantity", "Quantity", NUMBER),
            _c("orders", "Orders", NUMBER),
            _c("value", "Sales value", MONEY, finance=True),
        ),
        builder=_sales_by_product,
        is_financial=True,
    ),
    "sales_by_category": ReportDefinition(
        key="sales_by_category",
        label="Sales by category",
        description="Sold quantity and value per product category.",
        division="sales",
        columns=(
            _c("category", "Category"),
            _c("quantity", "Quantity", NUMBER),
            _c("value", "Sales value", MONEY, finance=True),
        ),
        builder=_sales_by_category,
        is_financial=True,
    ),
    "sales_by_origin": ReportDefinition(
        key="sales_by_origin",
        label="Sales by origin (state/LGA)",
        description="Sold quantity and value by the produce origin captured on the order line.",
        division="sales",
        columns=(
            _c("origin_state", "Origin state"),
            _c("origin_lga", "Origin LGA"),
            _c("quantity", "Quantity", NUMBER),
            _c("value", "Sales value", MONEY, finance=True),
        ),
        builder=_sales_by_origin,
        is_financial=True,
    ),
    "sales_by_destination": ReportDefinition(
        key="sales_by_destination",
        label="Sales by delivery state",
        description="Order count and placed value by delivery state.",
        division="sales",
        columns=(
            _c("state", "Delivery state"),
            _c("orders", "Orders", NUMBER),
            _c("value", "Placed value", MONEY, finance=True),
        ),
        builder=_sales_by_destination,
        is_financial=True,
    ),
    "finance_receipts": ReportDefinition(
        key="finance_receipts",
        label="Verified receipts",
        description="Settled payments only (verified money), one row per payment.",
        division="finance",
        columns=(
            _c("reference", "Reference"),
            _c("provider", "Provider"),
            _c("method", "Method"),
            _c("currency", "Currency"),
            _c("amount", "Verified amount", MONEY, finance=True),
            _c("verified_at", "Verified", DATETIME),
            _c("status", "Status"),
        ),
        builder=_finance_receipts,
        is_financial=True,
    ),
    "finance_refunds": ReportDefinition(
        key="finance_refunds",
        label="Completed refunds",
        description="Refunds that reached the completed state.",
        division="finance",
        columns=(
            _c("reference", "Refund"),
            _c("payment", "Payment"),
            _c("amount", "Amount", MONEY, finance=True),
            _c("currency", "Currency"),
            _c("processed_at", "Processed", DATETIME),
            _c("status", "Status"),
        ),
        builder=_finance_refunds,
        is_financial=True,
    ),
    "finance_outstanding_invoices": ReportDefinition(
        key="finance_outstanding_invoices",
        label="Outstanding invoices",
        description="Invoices in unpaid/partially-paid states.",
        division="finance",
        columns=(
            _c("invoice", "Invoice"),
            _c("status", "Status"),
            _c("currency", "Currency"),
            _c("total", "Total", MONEY, finance=True),
            _c("due_at", "Due", DATE),
        ),
        builder=_finance_invoices,
        is_financial=True,
    ),
    "inventory_stock": ReportDefinition(
        key="inventory_stock",
        label="Stock on hand",
        description="On-hand, reserved and available quantities per listing and warehouse.",
        division="inventory",
        columns=(
            _c("product", "Product"),
            _c("packaging", "Packaging"),
            _c("warehouse", "Warehouse"),
            _c("on_hand", "On hand", NUMBER),
            _c("reserved", "Reserved", NUMBER),
            _c("available", "Available", NUMBER),
            _c("unit", "Unit"),
        ),
        builder=_inventory_stock,
        allowed_filters=("preset", "warehouse_id", "product_id"),
    ),
    "inventory_low_stock": ReportDefinition(
        key="inventory_low_stock",
        label="Low-stock listings",
        description="Listings at or below their configured low-stock threshold.",
        division="inventory",
        columns=(
            _c("product", "Product"),
            _c("state", "Origin state"),
            _c("available", "Available", NUMBER),
            _c("threshold", "Threshold", NUMBER),
            _c("unit", "Unit"),
        ),
        builder=_inventory_low_stock,
    ),
    "inventory_movements": ReportDefinition(
        key="inventory_movements",
        label="Stock movements",
        description="Append-only stock movement ledger within the window.",
        division="inventory",
        columns=(
            _c("movement_at", "When", DATETIME),
            _c("product", "Product"),
            _c("kind", "Kind"),
            _c("quantity_delta", "Delta", NUMBER),
            _c("balance_after", "Balance after", NUMBER),
            _c("warehouse", "Warehouse"),
            _c("reference", "Reference"),
        ),
        builder=_inventory_movements,
    ),
    "services_requests": ReportDefinition(
        key="services_requests",
        label="Service requests",
        description="Agricultural service requests across every division.",
        division="services",
        columns=(
            _c("reference", "Reference"),
            _c("service_type", "Division"),
            _c("status", "Status"),
            _c("state", "State"),
            _c("created_at", "Created", DATETIME),
        ),
        builder=_services_requests,
        allowed_filters=("preset", "date_from", "date_to", "status", "division"),
    ),
    "storage_utilization": ReportDefinition(
        key="storage_utilization",
        label="Storage utilization",
        description="Allocated capacity versus facility capacity, per capacity unit.",
        division="services",
        columns=(
            _c("facility", "Facility"),
            _c("unit", "Unit"),
            _c("allocated", "Allocated", NUMBER),
            _c("capacity", "Capacity", NUMBER),
            _c("percent", "Utilization %", PERCENT),
        ),
        builder=_storage_utilization,
    ),
    "export_enquiries": ReportDefinition(
        key="export_enquiries",
        label="Export enquiries",
        description="Export leads by destination. Enquiries are never counted as sales.",
        division="export",
        columns=(
            _c("reference", "Reference"),
            _c("destination", "Destination"),
            _c("status", "Status"),
            _c("priority", "Priority"),
            _c("created_at", "Created", DATETIME),
        ),
        builder=_export_enquiries,
        allowed_filters=("preset", "date_from", "date_to", "status", "destination_id"),
    ),
    "export_orders": ReportDefinition(
        key="export_orders",
        label="Export orders",
        description="Confirmed export orders and their compliance status.",
        division="export",
        columns=(
            _c("reference", "Reference"),
            _c("destination", "Destination"),
            _c("status", "Status"),
            _c("compliance", "Compliance"),
            _c("currency", "Currency"),
            _c("total", "Total", MONEY, finance=True),
            _c("created_at", "Created", DATETIME),
        ),
        builder=_export_orders,
        allowed_filters=("preset", "date_from", "date_to", "status", "destination_id"),
        is_financial=True,
    ),
    "export_shipments": ReportDefinition(
        key="export_shipments",
        label="Export shipments",
        description="Shipments with planned and actual milestone dates.",
        division="export",
        columns=(
            _c("reference", "Reference"),
            _c("origin", "Origin"),
            _c("destination", "Destination"),
            _c("status", "Status"),
            _c("departure_date", "Departure", DATE),
            _c("estimated_arrival", "ETA", DATE),
            _c("actual_arrival", "Arrived", DATE),
        ),
        builder=_export_shipments,
    ),
    "training_enrollments": ReportDefinition(
        key="training_enrollments",
        label="Training enrollments",
        description="Course enrollment requests and their confirmed status.",
        division="training",
        columns=(
            _c("reference", "Reference"),
            _c("course", "Course"),
            _c("status", "Status"),
            _c("payment_status", "Payment"),
            _c("created_at", "Created", DATETIME),
        ),
        builder=_training_enrollments,
        allowed_filters=("preset", "date_from", "date_to", "status"),
    ),
    "training_attendance": ReportDefinition(
        key="training_attendance",
        label="Training attendance",
        description="Attendance rate per course.",
        division="training",
        columns=(
            _c("course", "Course"),
            _c("total", "Records", NUMBER),
            _c("attended", "Attended", NUMBER),
            _c("rate", "Attendance %", PERCENT),
        ),
        builder=_training_attendance,
    ),
    "customers_new_by_month": ReportDefinition(
        key="customers_new_by_month",
        label="New customers by month",
        description="Customer accounts created per month (aggregate only — no personal data).",
        division="customers",
        columns=(
            _c("month", "Month", DATE),
            _c("new_customers", "New customers", NUMBER),
        ),
        builder=_customers_new_by_month,
    ),
    "support_tickets": ReportDefinition(
        key="support_tickets",
        label="Support tickets",
        description="Support tickets with category, priority and resolution timestamps.",
        division="support",
        columns=(
            _c("reference", "Reference"),
            _c("category", "Category"),
            _c("priority", "Priority"),
            _c("status", "Status"),
            _c("created_at", "Created", DATETIME),
            _c("resolved_at", "Resolved", DATETIME),
        ),
        builder=_support_tickets,
        allowed_filters=("preset", "date_from", "date_to", "status"),
    ),
    "support_agents": ReportDefinition(
        key="support_agents",
        label="Support workload by agent",
        description="Assigned ticket counts per support agent (internal staff data).",
        division="support",
        columns=(
            _c("agent", "Agent"),
            _c("tickets", "Tickets", NUMBER),
        ),
        builder=_support_agents,
    ),
}


def get_report(key: str) -> ReportDefinition | None:
    """Allow-listed lookup — unknown keys return ``None``."""
    return REPORT_DEFINITIONS.get(key or "")


def available_reports(capabilities) -> list[ReportDefinition]:
    """Reports the holder of ``capabilities`` may build."""
    capabilities = set(capabilities or ())
    out = []
    for definition in REPORT_DEFINITIONS.values():
        if definition.is_financial and "analytics.finance" not in capabilities:
            continue
        if definition.base_capability not in capabilities:
            continue
        out.append(definition)
    return out


def visible_columns(definition: ReportDefinition, *, allow_finance: bool) -> list[Column]:
    if allow_finance:
        return list(definition.columns)
    return [c for c in definition.columns if not c.finance and c.kind != MONEY]


def build_rows(definition: ReportDefinition, filters) -> list[dict]:
    """Run an allow-listed builder. Never raises on empty data."""
    return definition.builder(filters)


def compute_totals(rows: list[dict], columns: list[Column]) -> dict:
    """Sum additive numeric/money columns for the report footer.

    Percentages are deliberately **not** totalled — summing rates is meaningless.
    """
    totals: dict = {}
    for column in columns:
        if column.kind in (NUMBER, MONEY):
            total = Decimal("0")
            for row in rows:
                value = row.get(column.key)
                if value is None:
                    continue
                total += Decimal(value)
            totals[column.key] = total
    return totals


__all__ = [
    "Column",
    "REPORT_DEFINITIONS",
    "ReportDefinition",
    "available_reports",
    "build_rows",
    "compute_totals",
    "get_report",
    "visible_columns",
]

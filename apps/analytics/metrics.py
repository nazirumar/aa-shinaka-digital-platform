"""The analytics KPI registry (documentation-as-code).

Every figure the dashboards and reports display has one entry here describing
exactly what it means, where it comes from and how it is computed. The registry
is the single source of truth that ``docs/ANALYTICS_METRICS.md`` mirrors, and it
is used to render metric tooltips and to decide which figures need a finance
capability.

Money rule: no KPI ever combines different currencies. Currency-bearing KPIs are
returned per currency (or in the configured base currency) and are never summed
across currencies without a configured exchange rate.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.accounts.roles import Capability


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    description: str
    category: str  # "financial" | "operational"
    unit: str  # "currency" | "count" | "percent" | "duration" | "decimal"
    source: str
    definition: str
    requires: str = ""
    notes: str = ""


_M = [
    # ---------------------------------------------------------------- executive
    MetricDef(
        key="gross_verified_receipts",
        label="Gross verified receipts",
        description="Total value of payments whose funds were actually verified.",
        category="financial",
        unit="currency",
        source="orders.Payment (status in paid/refunded/partially_refunded)",
        definition=(
            "SUM(Payment.verified_amount) over settled payment states, windowed on verified_at."
        ),
        requires=Capability.ANALYTICS_FINANCE,
        notes="A payment-in-review is never counted; only verified money.",
    ),
    MetricDef(
        key="confirmed_refunds",
        label="Confirmed refunds",
        description="Value of refunds that were fully completed.",
        category="financial",
        unit="currency",
        source="orders.Refund (status = completed)",
        definition="SUM(Refund.amount) where status = completed, windowed on processed_at.",
        requires=Capability.ANALYTICS_FINANCE,
    ),
    MetricDef(
        key="net_verified_receipts",
        label="Net verified receipts",
        description="Verified receipts less completed refunds. NOT accounting profit.",
        category="financial",
        unit="currency",
        source="orders.Payment, orders.Refund",
        definition="gross_verified_receipts − confirmed_refunds.",
        requires=Capability.ANALYTICS_FINANCE,
        notes="This is a cash figure, not profit. Profit is not reported because no "
        "authoritative cost/expense ledger exists.",
    ),
    MetricDef(
        key="orders_total",
        label="Sales orders",
        description="Orders placed in the window.",
        category="operational",
        unit="count",
        source="orders.Order",
        definition="COUNT(Order) windowed on created_at.",
    ),
    MetricDef(
        key="orders_fulfilled",
        label="Fulfilled orders",
        description="Orders delivered or completed.",
        category="operational",
        unit="count",
        source="orders.Order (status in delivered/completed)",
        definition="COUNT(Order) where status in {delivered, completed}.",
    ),
    MetricDef(
        key="orders_open",
        label="Open orders",
        description="Orders still in the fulfilment pipeline.",
        category="operational",
        unit="count",
        source="orders.Order",
        definition="COUNT(Order) excluding terminal states (completed/cancelled/expired/refunded).",
    ),
    MetricDef(
        key="new_customers",
        label="New customers",
        description="Customer accounts created in the window.",
        category="operational",
        unit="count",
        source="accounts.User (role = customer)",
        definition="COUNT(User) where role = customer and created_at in window.",
    ),
    MetricDef(
        key="open_support_tickets",
        label="Open support tickets",
        description="Support tickets not yet resolved or closed.",
        category="operational",
        unit="count",
        source="support.SupportTicket",
        definition="COUNT(ticket) where status in the open state set.",
    ),
    # -------------------------------------------------------------------- sales
    MetricDef(
        key="average_order_value",
        label="Average order value",
        description="Mean grand total of counted orders.",
        category="financial",
        unit="currency",
        source="orders.Order.grand_total",
        definition="SUM(grand_total) / COUNT(orders), per currency.",
        requires=Capability.ANALYTICS_FINANCE,
        notes="Uses placed-order totals (snapshotted). Recognised-sales value is a "
        "separate figure and the two are never mixed.",
    ),
    MetricDef(
        key="repeat_customers",
        label="Repeat purchasing customers",
        description="Customers with more than one counted order.",
        category="operational",
        unit="count",
        source="orders.Order",
        definition="COUNT(DISTINCT user) HAVING COUNT(order) > 1.",
    ),
    MetricDef(
        key="sales_value_placed",
        label="Placed sales value",
        description="Grand total of orders placed, regardless of payment.",
        category="financial",
        unit="currency",
        source="orders.Order.grand_total",
        definition="SUM(grand_total) windowed on created_at. Excludes cancelled/expired.",
        requires=Capability.ANALYTICS_FINANCE,
    ),
    MetricDef(
        key="sales_value_paid",
        label="Paid sales value",
        description="Verified money attributed to sales orders.",
        category="financial",
        unit="currency",
        source="orders.Payment",
        definition="SUM(verified_amount) where order is not null, settled states.",
        requires=Capability.ANALYTICS_FINANCE,
    ),
    # ------------------------------------------------------------------ finance
    MetricDef(
        key="outstanding_invoice_balance",
        label="Outstanding invoice balance",
        description="Invoiced value not yet paid.",
        category="financial",
        unit="currency",
        source="orders.Invoice",
        definition="SUM(total) for invoices in unpaid/partially_paid, per currency.",
        requires=Capability.ANALYTICS_FINANCE,
    ),
    MetricDef(
        key="pending_payments",
        label="Pending payments",
        description="Payments initialized but not yet verified.",
        category="financial",
        unit="count",
        source="orders.Payment (status pending/processing)",
        definition="COUNT(Payment) in open payment states.",
        requires=Capability.ANALYTICS_FINANCE,
    ),
    MetricDef(
        key="receipts_by_division",
        label="Receipts by division",
        description="Verified receipts split by the business record they settle.",
        category="financial",
        unit="currency",
        source="orders.Payment target FKs",
        definition="SUM(verified_amount) grouped by (order / service_quotation / "
        "export_order / training_enrollment), per currency.",
        requires=Capability.ANALYTICS_FINANCE,
        notes="A payment has exactly one target, so divisions never double-count.",
    ),
    # ---------------------------------------------------------------- inventory
    MetricDef(
        key="stock_on_hand",
        label="Stock on hand",
        description="Physical quantity recorded across warehouse balances.",
        category="operational",
        unit="decimal",
        source="catalog.StockBalance.on_hand",
        definition="SUM(on_hand). Quantities in different units are never combined.",
    ),
    MetricDef(
        key="stock_reserved",
        label="Reserved stock",
        description="Quantity held against open reservations.",
        category="operational",
        unit="decimal",
        source="catalog.StockBalance.reserved",
        definition="SUM(reserved).",
    ),
    MetricDef(
        key="stock_available",
        label="Available stock",
        description="On hand less reserved.",
        category="operational",
        unit="decimal",
        source="catalog.StockBalance",
        definition="SUM(on_hand − reserved).",
    ),
    MetricDef(
        key="low_stock_listings",
        label="Low-stock listings",
        description="Listings at or below their configured low-stock threshold.",
        category="operational",
        unit="count",
        source="catalog.ProductListing",
        definition="COUNT(listing) where low_stock_threshold is set and available <= threshold.",
        notes="Customer-owned storage inventory is never treated as company saleable stock.",
    ),
    # ----------------------------------------------------------------- services
    MetricDef(
        key="consultancy_requests",
        label="Consultancy requests",
        description="Service requests of type consultancy.",
        category="operational",
        unit="count",
        source="services.ServiceRequest (service_type = consultancy)",
        definition="COUNT(request) windowed on created_at.",
    ),
    MetricDef(
        key="confirmed_appointments",
        label="Confirmed appointments",
        description="Consultation appointments confirmed or rescheduled.",
        category="operational",
        unit="count",
        source="services.ConsultationAppointment",
        definition="COUNT(appointment) where status in {confirmed, rescheduled}.",
    ),
    MetricDef(
        key="completed_consultations",
        label="Completed consultations",
        description="Consultation appointments marked completed.",
        category="operational",
        unit="count",
        source="services.ConsultationAppointment",
        definition="COUNT(appointment) where status = completed.",
    ),
    MetricDef(
        key="farm_project_status",
        label="Farm projects",
        description="Farm project counts grouped by lifecycle status.",
        category="operational",
        unit="count",
        source="services.FarmProject",
        definition="COUNT(project) grouped by status.",
    ),
    MetricDef(
        key="storage_utilization",
        label="Storage utilization",
        description="Allocated capacity as a percentage of facility capacity.",
        category="operational",
        unit="percent",
        source="services.StorageCapacityAllocation, StorageFacility.capacity",
        definition="allocated_quantity / facility_capacity × 100, per capacity unit.",
        notes="Capacity units are compared only within the same unit.",
    ),
    MetricDef(
        key="service_quotation_acceptance",
        label="Quotation acceptance rate",
        description="Share of issued service quotations that were accepted.",
        category="operational",
        unit="percent",
        source="services.ServiceQuotation",
        definition="accepted / (issued + accepted) × 100.",
    ),
    # ------------------------------------------------------------------- export
    MetricDef(
        key="export_enquiries",
        label="Export enquiries",
        description="Export enquiries submitted, by destination country.",
        category="operational",
        unit="count",
        source="export.ExportEnquiry",
        definition="COUNT(enquiry) windowed on created_at.",
        notes="Enquiries are leads, never counted as completed exports.",
    ),
    MetricDef(
        key="export_active_orders",
        label="Active export orders",
        description="Export orders not yet completed or cancelled.",
        category="operational",
        unit="count",
        source="export.ExportOrder",
        definition="COUNT(order) excluding {completed, cancelled}.",
    ),
    MetricDef(
        key="export_shipments_dispatched",
        label="Shipments dispatched",
        description="Shipments that have left origin.",
        category="operational",
        unit="count",
        source="export.ExportShipment",
        definition="COUNT(shipment) where status in {dispatched, in_transit, "
        "customs_processing, delivered}.",
    ),
    MetricDef(
        key="export_shipments_delivered",
        label="Shipments delivered",
        description="Shipments confirmed delivered.",
        category="operational",
        unit="count",
        source="export.ExportShipment",
        definition="COUNT(shipment) where status = delivered.",
    ),
    # ----------------------------------------------------------------- training
    MetricDef(
        key="confirmed_enrollments",
        label="Confirmed enrollments",
        description="Enrollments confirmed or completed.",
        category="operational",
        unit="count",
        source="training.Enrollment",
        definition="COUNT(enrollment) where status in {confirmed, completed}.",
        notes="Pending registrations are never counted as confirmed.",
    ),
    MetricDef(
        key="attendance_rate",
        label="Attendance rate",
        description="Attendance records marked present or late, over all records.",
        category="operational",
        unit="percent",
        source="training.AttendanceRecord",
        definition="attended / total_records × 100.",
    ),
    MetricDef(
        key="completion_rate",
        label="Completion rate",
        description="Enrollments completed over finished enrollments.",
        category="operational",
        unit="percent",
        source="training.Enrollment",
        definition="completed / (completed + cancelled) × 100.",
    ),
    MetricDef(
        key="certificates_issued",
        label="Certificates issued",
        description="Certificates with issued status.",
        category="operational",
        unit="count",
        source="training.Certificate",
        definition="COUNT(certificate) where status = issued.",
    ),
    # ---------------------------------------------------------------- customers
    MetricDef(
        key="active_customers",
        label="Active customers",
        description="Customers with an order, order attempt or service request in the window.",
        category="operational",
        unit="count",
        source="accounts.User, orders.Order, services.ServiceRequest",
        definition="COUNT(DISTINCT customer) with any of the above in the window.",
        notes="Aggregated only; personal data is never exposed in aggregate views.",
    ),
    # ------------------------------------------------------------------ support
    MetricDef(
        key="avg_first_response_time",
        label="Average first response time",
        description="Mean time from ticket creation to the first staff (non-internal) reply.",
        category="operational",
        unit="duration",
        source="support.SupportTicket, support.SupportMessage",
        definition="AVG(first non-internal staff reply created_at − ticket created_at).",
        notes="Internal notes are excluded from the customer-response calculation.",
    ),
    MetricDef(
        key="average_resolution_time",
        label="Average resolution time",
        description="Mean time from ticket creation to resolution.",
        category="operational",
        unit="duration",
        source="support.SupportTicket",
        definition="AVG(resolved_at − created_at) for resolved tickets.",
    ),
    MetricDef(
        key="ticket_backlog",
        label="Ticket backlog",
        description="Open tickets that are still unassigned.",
        category="operational",
        unit="count",
        source="support.SupportTicket",
        definition="COUNT(ticket) where assigned_to is null and status is open.",
    ),
]

METRICS: dict[str, MetricDef] = {metric.key: metric for metric in _M}


def metric(key: str) -> MetricDef | None:
    return METRICS.get(key)


def metrics_for(capabilities) -> list[MetricDef]:
    """Metrics visible to a set of capabilities (finance metrics gated)."""
    caps = set(capabilities or ())
    return [metric for metric in METRICS.values() if not metric.requires or metric.requires in caps]


def metric_label(key: str, default: str = "") -> str:
    entry = METRICS.get(key)
    return entry.label if entry else (default or key)


__all__ = ["METRICS", "MetricDef", "metric", "metric_label", "metrics_for"]

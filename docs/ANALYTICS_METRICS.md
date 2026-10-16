# Analytics metrics reference (Phase 11)

This document mirrors the **analytics KPI registry** in
`apps/analytics/metrics.py`. That registry is the single source of truth: every
figure the dashboards and reports display has one entry there describing exactly
what it means, where it comes from and how it is computed, and the registry is
used to gate financial figures.

It is a reference for operators and reviewers, not a promise of invented numbers —
every metric below is derived from the authoritative domain models at request
time, and an empty dataset yields an empty metric, never an estimate.

## Reading the tables

- **Unit** — `currency`, `count`, `percent`, `duration` or `decimal`.
- **Requires** — the capability a user must hold for the figure to be **computed
  and returned at all**. Figures marked `analytics.finance` are hidden from a user
  who only holds `analytics.view`.
- **Money rule** — no metric ever combines different currencies. Currency metrics
  are returned per currency (or in the configured base currency) and are never
  summed across currencies without a configured exchange rate.
- **Profit** — net receipts are a **cash** figure, not accounting profit. No profit
  metric exists because there is no authoritative cost/expense ledger.

## Executive overview

| Key | Label | Unit | Requires |
|---|---|---|---|
| `gross_verified_receipts` | Gross verified receipts | currency | `analytics.finance` |
| `confirmed_refunds` | Confirmed refunds | currency | `analytics.finance` |
| `net_verified_receipts` | Net verified receipts | currency | `analytics.finance` |
| `orders_total` | Sales orders | count | — |
| `orders_fulfilled` | Fulfilled orders | count | — |
| `orders_open` | Open orders | count | — |
| `new_customers` | New customers | count | — |
| `open_support_tickets` | Open support tickets | count | — |

- **Gross verified receipts** — `SUM(Payment.verified_amount)` over settled
  payment states (`paid`, `refunded`, `partially_refunded`), windowed on
  `verified_at`. A payment-in-review is never counted.
- **Confirmed refunds** — `SUM(Refund.amount)` where the refund is `completed`,
  windowed on `processed_at`.
- **Net verified receipts** — `gross_verified_receipts − confirmed_refunds`. **This
  is cash, not profit.**
- **Sales orders** — `COUNT(Order)` windowed on `created_at`.
- **Fulfilled orders** — `COUNT(Order)` where status ∈ {`delivered`, `completed`}.
- **Open orders** — `COUNT(Order)` excluding terminal states (`completed`,
  `cancelled`, `expired`, `refunded`).
- **New customers** — `COUNT(User)` where role = customer and `created_at` is in
  the window.
- **Open support tickets** — `COUNT(ticket)` in the open state set.

## Sales

| Key | Label | Unit | Requires |
|---|---|---|---|
| `average_order_value` | Average order value | currency | `analytics.finance` |
| `repeat_customers` | Repeat purchasing customers | count | — |
| `sales_value_placed` | Placed sales value | currency | `analytics.finance` |
| `sales_value_paid` | Paid sales value | currency | `analytics.finance` |

- **Average order value** — `SUM(grand_total) / COUNT(orders)`, per currency. Uses
  placed-order totals (snapshotted); it is never mixed with recognised sales.
- **Repeat purchasing customers** — `COUNT(DISTINCT user)` having more than one
  counted order.
- **Placed sales value** — `SUM(Order.grand_total)` windowed on `created_at`,
  excluding cancelled/expired orders.
- **Paid sales value** — `SUM(Payment.verified_amount)` where the payment targets
  an order and is in a settled state.

Order-line values always come from the immutable `OrderItem` price snapshots, so a
later price change never rewrites history.

## Finance

| Key | Label | Unit | Requires |
|---|---|---|---|
| `outstanding_invoice_balance` | Outstanding invoice balance | currency | `analytics.finance` |
| `pending_payments` | Pending payments | count | `analytics.finance` |
| `receipts_by_division` | Receipts by division | currency | `analytics.finance` |

- **Outstanding invoice balance** — `SUM(Invoice.total)` for invoices in
  `unpaid`/`partially_paid`, per currency.
- **Pending payments** — `COUNT(Payment)` in open payment states
  (`pending`/`processing`).
- **Receipts by division** — `SUM(verified_amount)` grouped by the business record
  the payment settles (order / service quotation / export order / training
  enrollment), per currency. A payment has exactly one target, so divisions never
  double-count.

## Inventory

| Key | Label | Unit |
|---|---|---|
| `stock_on_hand` | Stock on hand | decimal |
| `stock_reserved` | Reserved stock | decimal |
| `stock_available` | Available stock | decimal |
| `low_stock_listings` | Low-stock listings | count |

- **Stock on hand** — `SUM(StockBalance.on_hand)`. Quantities in different units
  are never combined.
- **Reserved stock** — `SUM(StockBalance.reserved)`.
- **Available stock** — `SUM(on_hand − reserved)`.
- **Low-stock listings** — `COUNT(listing)` where a low-stock threshold is set and
  `available <= threshold`.

Customer-owned storage inventory is never treated as company saleable stock, and
incompatible stock units are never summed.

## Services

| Key | Label | Unit |
|---|---|---|
| `consultancy_requests` | Consultancy requests | count |
| `confirmed_appointments` | Confirmed appointments | count |
| `completed_consultations` | Completed consultations | count |
| `farm_project_status` | Farm projects | count |
| `storage_utilization` | Storage utilization | percent |
| `service_quotation_acceptance` | Quotation acceptance rate | percent |

- **Consultancy requests** — `COUNT(ServiceRequest)` of type consultancy, windowed
  on `created_at`.
- **Confirmed appointments** — `COUNT(appointment)` where status ∈ {`confirmed`,
  `rescheduled`}.
- **Completed consultations** — `COUNT(appointment)` where status = `completed`.
- **Farm projects** — `COUNT(project)` grouped by lifecycle status.
- **Storage utilization** — `allocated_quantity / facility_capacity × 100`, per
  capacity unit (compared only within the same unit).
- **Quotation acceptance rate** — `accepted / (issued + accepted) × 100`.

Quotations and enquiries are never counted as completed business.

## Export

| Key | Label | Unit |
|---|---|---|
| `export_enquiries` | Export enquiries | count |
| `export_active_orders` | Active export orders | count |
| `export_shipments_dispatched` | Shipments dispatched | count |
| `export_shipments_delivered` | Shipments delivered | count |

- **Export enquiries** — `COUNT(enquiry)` windowed on `created_at`. Enquiries are
  leads and are never counted as completed exports.
- **Active export orders** — `COUNT(order)` excluding {`completed`, `cancelled`}.
- **Shipments dispatched** — `COUNT(shipment)` where status ∈ {`dispatched`,
  `in_transit`, `customs_processing`, `delivered`}.
- **Shipments delivered** — `COUNT(shipment)` where status = `delivered`.

## Training

| Key | Label | Unit |
|---|---|---|
| `confirmed_enrollments` | Confirmed enrollments | count |
| `attendance_rate` | Attendance rate | percent |
| `completion_rate` | Completion rate | percent |
| `certificates_issued` | Certificates issued | count |

- **Confirmed enrollments** — `COUNT(enrollment)` where status ∈ {`confirmed`,
  `completed`}. Pending registrations are never counted as confirmed.
- **Attendance rate** — `attended / total_records × 100` (`present` or `late`).
- **Completion rate** — `completed / (completed + cancelled) × 100`.
- **Certificates issued** — `COUNT(certificate)` where status = `issued`.

## Customers

| Key | Label | Unit |
|---|---|---|
| `active_customers` | Active customers | count |

- **Active customers** — `COUNT(DISTINCT customer)` with an order, order attempt or
  service request in the window. Aggregated only; personal data is never exposed
  in aggregate views.

## Support

| Key | Label | Unit |
|---|---|---|
| `avg_first_response_time` | Average first response time | duration |
| `average_resolution_time` | Average resolution time | duration |
| `ticket_backlog` | Ticket backlog | count |

- **Average first response time** — mean time from ticket creation to the first
  **non-internal** staff reply. Internal notes are excluded.
- **Average resolution time** — `AVG(resolved_at − created_at)` for resolved
  tickets.
- **Ticket backlog** — `COUNT(ticket)` where `assigned_to` is null and status is
  open.

## See also

- `docs/PHASE_11_COMPLETION_REPORT.md` — deliverables, URLs, the report catalogue
  and the multi-currency policy.
- `apps/analytics/metrics.py` — the machine-readable registry this document
  mirrors.

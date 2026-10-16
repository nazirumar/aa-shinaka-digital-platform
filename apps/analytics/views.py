"""Analytics & reporting views (Phase 11 — Tasks 3–10, 12–16).

Every view enforces its capability server-side. Financial figures are gated
behind ``analytics.finance`` both in what is **computed** and in what a page can
render, so a user without that capability never receives the data at all. Charts
are embedded with ``json_script`` (never string-interpolated into JavaScript).

The eight operational pages share one generic renderer driven by a small,
server-built view model (KPIs, charts, tables); the executive overview has a
bespoke layout.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import capability_required, has_capability, user_capabilities
from apps.accounts.roles import Capability
from apps.core.upload_security import enforce_downloadable

from . import charts, exports, services
from . import selectors as sel
from .data_quality import run_checks, summary
from .filters import PRESETS, ReportFilters
from .forms import ReportBuilderForm, ScheduledReportForm
from .models import ExecutionStatus, ReportExport, ScheduledReport
from .reports import get_report

PAGE_TITLES = {
    "sales": "Sales analytics",
    "finance": "Financial analytics",
    "inventory": "Inventory analytics",
    "services": "Services analytics",
    "export": "Export analytics",
    "training": "Training analytics",
    "customers": "Customer analytics",
    "support": "Support analytics",
}
FINANCE_PAGES = frozenset({"finance"})

_CHART_BUILDERS = {
    "sales": charts.sales_charts,
    "finance": charts.finance_charts,
    "inventory": charts.inventory_charts,
    "services": charts.services_charts,
    "export": charts.export_charts,
    "training": charts.training_charts,
    "customers": charts.customers_charts,
    "support": charts.support_charts,
}

_CHART_TITLES = {
    "sales": {
        "trend": ("Orders over time", "Placed orders, excluding cancelled/expired"),
        "status": ("Order status", ""),
        "delivery_states": ("Orders by delivery state", ""),
    },
    "finance": {
        "receipts_trend": ("Verified receipts over time", "Only verified funds are counted"),
        "by_method": ("Receipts by method", ""),
        "by_currency": ("Receipts by currency", "Currencies are never combined"),
    },
    "inventory": {
        "by_warehouse": ("On hand by warehouse", "Quantities are only comparable within a unit"),
        "movements_by_kind": ("Movements by kind", ""),
        "movements_trend": ("Movements over time", ""),
    },
    "services": {
        "by_division": ("Requests by division", ""),
        "farm_status": ("Farm projects by status", ""),
        "storage_utilization": ("Storage utilization", "% of capacity allocated"),
    },
    "export": {
        "enquiries_by_destination": ("Enquiries by destination", "Enquiries are leads, not sales"),
        "orders_by_status": ("Export orders by status", ""),
        "compliance": ("Compliance by status", ""),
    },
    "training": {
        "enrollments_by_status": ("Enrollments by status", ""),
        "course_popularity": ("Course popularity", ""),
    },
    "customers": {
        "customer_mix": ("Customer mix", ""),
    },
    "support": {
        "by_status": ("Tickets by status", ""),
        "by_priority": ("Tickets by priority", ""),
        "by_category": ("Tickets by category", ""),
    },
}


# ---------------------------------------------------------------------------
# Small rendering helpers
# ---------------------------------------------------------------------------


def _kpi(label, value, kind="count", currency="", help_text=""):
    return {"label": label, "value": value, "kind": kind, "currency": currency, "help": help_text}


def _col(key, label, kind="text", finance=False):
    return {"key": key, "label": label, "kind": kind, "finance": finance}


def _format_value(value, kind, currency=""):
    if value is None or value == "":
        return "—"
    if kind == "money":
        try:
            amount = Decimal(value)
        except (InvalidOperation, TypeError, ValueError):
            return str(value)
        if currency:
            symbol = "₦" if currency == "NGN" else f"{currency} "
            return f"{symbol}{amount:,.2f}"
        return f"{amount:,.2f}"
    if kind == "decimal":
        try:
            return format(Decimal(value).normalize(), "f")
        except (InvalidOperation, TypeError, ValueError):
            return str(value)
    if kind == "percent":
        return f"{value}%"
    if kind == "date":
        return value.strftime("%d %b %Y") if hasattr(value, "strftime") else str(value)
    if kind == "datetime":
        if hasattr(value, "year"):
            return timezone.localtime(value).strftime("%d %b %Y %H:%M")
        return str(value)
    return str(value)


def _table(title, columns, rows, *, show_finance, currency="", note=""):
    cols = [c for c in columns if show_finance or not c["finance"]]
    display_rows = [
        [_format_value(row.get(c["key"]), c["kind"], row.get("currency") or currency) for c in cols]
        for row in rows
    ]
    totals: list[str] = []
    for c in cols:
        if c["kind"] in ("money", "decimal") and rows:
            total = Decimal("0")
            for row in rows:
                value = row.get(c["key"])
                if value in (None, ""):
                    continue
                total += Decimal(value)
            totals.append(_format_value(total, c["kind"]))
        else:
            totals.append("")
    return {
        "title": title,
        "columns": cols,
        "rows": display_rows,
        "totals": totals if any(totals) else [],
        "note": note,
        "currency": currency,
        "empty": "No data for this period.",
    }


def _chart(chart_id, title, payload, subtitle=""):
    return {"id": chart_id, "title": title, "subtitle": subtitle, "payload": payload}


def _charts_for(page, filters):
    payloads = _CHART_BUILDERS[page](filters=filters)
    meta = _CHART_TITLES[page]
    out = []
    for key, payload in payloads.items():
        title, subtitle = meta.get(key, (key.replace("_", " ").title(), ""))
        out.append(_chart(f"chart-{page}-{key}", title, payload, subtitle))
    return out


def _page_chrome(page_title, active_nav, filters):
    return {
        "page_title": page_title,
        "active_nav": active_nav,
        "filters": filters,
        "presets": PRESETS,
    }


def _capabilities(user) -> frozenset:
    return user_capabilities(user)


def _render_preview(preview):
    """Add display-ready columns/rows/totals to a raw report preview."""
    columns = preview["columns"]
    preview["display_columns"] = [c.label for c in columns]
    preview["display_rows"] = [
        [exports.format_cell(c, row.get(c.key)) for c in columns] for row in preview["rows"]
    ]
    totals = preview.get("totals", {})
    preview["display_totals"] = [
        exports.format_cell(c, totals[c.key]) if c.key in totals else "" for c in columns
    ]
    return preview


# ---------------------------------------------------------------------------
# Page view models
# ---------------------------------------------------------------------------


def _context_for_page(page, filters, *, show_finance):
    currency = sel.base_currency()
    kpis: list = []
    tables: list = []
    notes: list = []

    if page == "sales":
        overview = sel.sales_overview(filters=filters)
        kpis = [
            _kpi("Sales orders", overview["order_count"]),
            _kpi("Fulfilled", overview["fulfilled_count"]),
            _kpi("Open", overview["open_count"]),
            _kpi("Repeat purchasers", overview["repeat_customers"]),
        ]
        if show_finance:
            for row in overview["by_currency"]:
                kpis.append(
                    _kpi(
                        f"Placed value ({row['currency']})",
                        row["total"],
                        kind="money",
                        currency=row["currency"],
                    )
                )
        tables = [
            _table(
                "Top products",
                [
                    _col("product_name", "Product"),
                    _col("quantity", "Quantity", "decimal"),
                    _col("orders", "Orders"),
                    _col("value", "Value", "money", finance=True),
                ],
                sel.top_products(filters=filters, limit=15),
                show_finance=show_finance,
                currency=currency,
            ),
            _table(
                "Sales by category",
                [
                    _col("category", "Category"),
                    _col("quantity", "Quantity", "decimal"),
                    _col("value", "Value", "money", finance=True),
                ],
                sel.top_categories(filters=filters, limit=15),
                show_finance=show_finance,
                currency=currency,
            ),
            _table(
                "Sales by origin state",
                [
                    _col("state", "Origin state"),
                    _col("quantity", "Quantity", "decimal"),
                    _col("value", "Value", "money", finance=True),
                ],
                sel.sales_by_origin_state(filters=filters, limit=15),
                show_finance=show_finance,
                currency=currency,
            ),
        ]
        notes.append(
            "Sales value is the placed order total from order-line snapshots; paid and "
            "recognised values are never mixed into it."
        )

    elif page == "finance":
        receipts = sel.receipts_by_currency(filters=filters)
        gross = sel.verified_receipts(filters=filters, currency=currency)
        refunds = sel.confirmed_refunds(filters=filters, currency=currency)
        by_division = sel.receipts_by_division(filters=filters, currency=currency)
        kpis = [
            _kpi(f"Gross receipts ({currency})", gross, kind="money", currency=currency),
            _kpi(f"Confirmed refunds ({currency})", refunds, kind="money", currency=currency),
            _kpi(
                f"Net receipts ({currency})",
                gross - refunds,
                kind="money",
                currency=currency,
                help_text="Cash received less refunds — not accounting profit.",
            ),
            _kpi("Pending payments", sel.pending_payments_count()),
        ]
        tables = [
            _table(
                "Receipts by currency",
                [_col("currency", "Currency"), _col("total", "Verified", "money")],
                receipts,
                show_finance=True,
                note="Currencies are listed separately and never summed together.",
            ),
            _table(
                "Receipts by division",
                [_col("division", "Division"), _col("total", "Receipts", "money")],
                [
                    {"division": "Products", "total": by_division["products"]},
                    {"division": "Services", "total": by_division["services"]},
                    {"division": "Export", "total": by_division["export"]},
                ],
                show_finance=True,
                currency=currency,
            ),
            _table(
                "Outstanding invoices",
                [
                    _col("currency", "Currency"),
                    _col("total", "Outstanding", "money"),
                    _col("count", "Invoices"),
                ],
                sel.outstanding_invoice_balance(filters=filters),
                show_finance=True,
            ),
            _table(
                "Refunds by status",
                [_col("status", "Status"), _col("count", "Count")],
                sel.refunds_by_status(),
                show_finance=True,
            ),
        ]
        notes.append(
            "Net receipts are cash received less refunds. They are **not** accounting "
            "profit: the platform holds no cost or expense ledger."
        )
        notes.append("Currencies are never combined without a configured exchange-rate source.")

    elif page == "inventory":
        summary_row = sel.stock_summary()
        # Compute the low-stock set once: the KPI needs the full count, the table
        # only the first 25. Calling the selector twice was the L-1 double-compute.
        low_stock = sel.low_stock_listings(limit=500)
        kpis = [
            _kpi(
                "On hand",
                summary_row["on_hand"],
                kind="decimal",
                help_text="Quantities are only comparable within the same unit of measure.",
            ),
            _kpi("Reserved", summary_row["reserved"], kind="decimal"),
            _kpi("Available", summary_row["available"], kind="decimal"),
            _kpi("Warehouses", summary_row["warehouse_count"]),
            _kpi("Active listings", summary_row["listing_count"]),
            _kpi("Low-stock listings", len(low_stock)),
        ]
        tables = [
            _table(
                "Stock by product",
                [
                    _col("product", "Product"),
                    _col("unit", "Unit"),
                    _col("on_hand", "On hand", "decimal"),
                    _col("reserved", "Reserved", "decimal"),
                    _col("available", "Available", "decimal"),
                ],
                sel.stock_by_product(filters=filters, limit=25),
                show_finance=show_finance,
            ),
            _table(
                "Low-stock listings",
                [
                    _col("product", "Product"),
                    _col("state", "Origin state"),
                    _col("unit", "Unit"),
                    _col("available", "Available", "decimal"),
                    _col("threshold", "Threshold", "decimal"),
                ],
                low_stock[:25],
                show_finance=show_finance,
            ),
        ]
        notes.append("Stock the platform holds as a custodian is never counted as available stock.")

    elif page == "services":
        metrics = sel.services_metrics(filters=filters)
        kpis = [
            _kpi("Service requests", metrics["total_requests"]),
            _kpi("Open requests", metrics["open_requests"]),
            _kpi("Consultancy requests", metrics["consultancy_requests"]),
            _kpi("Confirmed appointments", metrics["confirmed_appointments"]),
            _kpi("Completed consultations", metrics["completed_consultations"]),
            _kpi("Quotations issued", metrics["quotations_issued"]),
            _kpi("Quotations accepted", metrics["quotations_accepted"]),
            _kpi("Acceptance rate", metrics["quotation_acceptance_rate"], kind="percent"),
        ]
        tables = [
            _table(
                "Farm projects by status",
                [_col("status", "Status"), _col("count", "Projects")],
                metrics["farm_projects_by_status"],
                show_finance=show_finance,
            ),
            _table(
                "Storage utilization",
                [
                    _col("facility", "Facility"),
                    _col("unit", "Unit"),
                    _col("allocated", "Allocated", "decimal"),
                    _col("capacity", "Capacity", "decimal"),
                    _col("percent", "Utilization", "percent"),
                ],
                metrics["storage_utilization"],
                show_finance=show_finance,
                note="Capacity is compared only within the same unit.",
            ),
        ]

    elif page == "export":
        metrics = sel.export_metrics(filters=filters)
        kpis = [
            _kpi("Enquiries", metrics["enquiries_total"]),
            _kpi("Open enquiries", metrics["open_enquiries"]),
            _kpi("Quotations issued", metrics["quotations_issued"]),
            _kpi("Quotations accepted", metrics["quotations_accepted"]),
            _kpi("Active export orders", metrics["orders_active"]),
            _kpi("Shipments dispatched", metrics["shipments_dispatched"]),
            _kpi("Shipments delivered", metrics["shipments_delivered"]),
        ]
        tables = [
            _table(
                "Enquiries by destination",
                [_col("destination", "Destination"), _col("count", "Enquiries")],
                [
                    {
                        "destination": r["destination__country__name"]
                        or r["destination__country_code"]
                        or "—",
                        "count": r["count"],
                    }
                    for r in metrics["enquiries_by_destination"]
                ],
                show_finance=show_finance,
            ),
            _table(
                "Export products",
                [
                    _col("product", "Product"),
                    _col("quantity", "Quantity", "decimal"),
                    _col("orders", "Orders"),
                ],
                metrics["products"],
                show_finance=show_finance,
            ),
            _table(
                "Compliance by status",
                [_col("compliance_status", "Compliance"), _col("count", "Orders")],
                metrics["compliance_by_status"],
                show_finance=show_finance,
            ),
        ]
        notes.append("Enquiries are leads and are never counted as completed exports.")

    elif page == "training":
        metrics = sel.training_metrics(filters=filters)
        kpis = [
            _kpi("Enrollments", metrics["total_enrollments"]),
            _kpi("Confirmed enrollments", metrics["confirmed_enrollments"]),
            _kpi("Completed", metrics["completed_enrollments"]),
            _kpi("Attendance rate", metrics["attendance_rate"], kind="percent"),
            _kpi("Completion rate", metrics["completion_rate"], kind="percent"),
            _kpi("Certificates issued", metrics["certificates_issued"]),
        ]
        tables = [
            _table(
                "Enrollments by status",
                [_col("status", "Status"), _col("count", "Enrollments")],
                metrics["enrollments_by_status"],
                show_finance=show_finance,
            ),
            _table(
                "Course popularity",
                [
                    _col("course", "Course"),
                    _col("total", "Enrollments"),
                    _col("confirmed", "Confirmed"),
                ],
                metrics["course_popularity"],
                show_finance=show_finance,
            ),
        ]
        notes.append("Pending registrations are never counted as confirmed enrollments.")

    elif page == "customers":
        metrics = sel.customer_metrics(filters=filters)
        kpis = [
            _kpi("New customers", metrics["new_customers"]),
            _kpi("Total customers", metrics["total_customers"]),
            _kpi("Active customers", metrics["active_customers"]),
            _kpi("Repeat purchasers", metrics["repeat_customers"]),
            _kpi("Training participants", metrics["training_participants"]),
            _kpi("Service users", metrics["service_usage_customers"]),
        ]
        tables = [
            _table(
                "New customers by month",
                [_col("month", "Month", "date"), _col("new_customers", "New customers")],
                sel.customers_new_by_month(filters=filters),
                show_finance=show_finance,
            ),
        ]
        notes.append(
            "Customer analytics are aggregated only. Names, emails, phone numbers and "
            "addresses are never exposed here."
        )

    elif page == "support":
        metrics = sel.support_analytics(filters=filters)
        kpis = [
            _kpi("Tickets", metrics["total"]),
            _kpi("Open", metrics["open"]),
            _kpi("Resolved", metrics["resolved"]),
            _kpi("Unassigned backlog", metrics["backlog_unassigned"]),
            _kpi("Avg first response", metrics["avg_first_response_display"]),
            _kpi("Avg resolution", metrics["avg_resolution_display"]),
        ]
        tables = [
            _table(
                "Support workload by agent",
                [_col("agent", "Agent"), _col("tickets", "Tickets")],
                [
                    {"agent": r["assigned_to__email"], "tickets": r["count"]}
                    for r in metrics["staff_workload"]
                ],
                show_finance=show_finance,
                note="Internal staff workload — customer identities are not shown.",
            ),
        ]

    return {
        "kpis": kpis,
        "charts": _charts_for(page, filters),
        "tables": tables,
        "notes": notes,
    }


def _executive_context(filters, *, show_finance):
    overview = sel.executive_overview(filters=filters, include_finance=show_finance)
    currency = sel.base_currency()
    kpis = [
        _kpi("Sales orders", overview["orders_total"]),
        _kpi("Fulfilled orders", overview["orders_fulfilled"]),
        _kpi("Open orders", overview["orders_open"]),
        _kpi("New customers", overview["new_customers"]),
        _kpi("Open support tickets", overview["open_support_tickets"]),
        _kpi("Low-stock listings", overview["low_stock_count"]),
        _kpi("Open export enquiries", overview["export_open_enquiries"]),
        _kpi("Active export orders", overview["export_active_orders"]),
        _kpi("Open service requests", overview["services_open_requests"]),
        _kpi("Confirmed enrollments", overview["training_confirmed_enrollments"]),
    ]
    status_rows = sel.order_status_distribution(filters=filters)
    chart_list = [
        _chart(
            "chart-exec-status",
            "Orders by status",
            charts.doughnut(
                _status_labels(status_rows),
                [r["count"] for r in status_rows],
                label="Orders",
            ),
        )
    ]
    tables: list = []
    if show_finance:
        kpis = [
            _kpi(
                f"Gross receipts ({currency})",
                overview["gross_receipts"],
                kind="money",
                currency=currency,
            ),
            _kpi(
                f"Confirmed refunds ({currency})",
                overview["confirmed_refunds"],
                kind="money",
                currency=currency,
            ),
            _kpi(
                f"Net receipts ({currency})",
                overview["net_receipts"],
                kind="money",
                currency=currency,
                help_text="Cash received less refunds. Not accounting profit.",
            ),
        ] + kpis
        trend = sel.receipts_by_day(filters=filters)
        chart_list.insert(
            0,
            _chart(
                "chart-exec-receipts",
                "Verified receipts over time",
                charts.line(
                    [r["day"].strftime("%Y-%m-%d") for r in trend],
                    [r["total"] for r in trend],
                    label="Verified receipts",
                    fill=True,
                ),
                "Only verified funds are counted",
            ),
        )
        tables.append(
            _table(
                "Receipts by currency",
                [_col("currency", "Currency"), _col("total", "Receipts", "money")],
                overview["receipts_by_currency"],
                show_finance=True,
                note="Currencies are never combined without a configured exchange-rate source.",
            )
        )
        tables.append(
            _table(
                "Outstanding invoices",
                [
                    _col("currency", "Currency"),
                    _col("total", "Outstanding", "money"),
                    _col("count", "Invoices"),
                ],
                overview["outstanding_invoices"],
                show_finance=True,
            )
        )
    return {"kpis": kpis, "charts": chart_list, "tables": tables, "notes": []}


def _status_labels(rows):
    return [str(r["status"]).replace("_", " ").title() for r in rows]


def _chart_data(chart_list):
    """Flatten chart payloads into a JSON-safe list for ``json_script``."""
    return [{"id": c["id"], **c["payload"]} for c in chart_list]


def _navigation_pages(show_finance):
    return {
        key: label for key, label in PAGE_TITLES.items() if show_finance or key not in FINANCE_PAGES
    }


# ---------------------------------------------------------------------------
# Analytics pages
# ---------------------------------------------------------------------------


@capability_required(Capability.ANALYTICS_VIEW)
def executive(request):
    filters = ReportFilters.from_request(request.GET)
    show_finance = has_capability(request.user, Capability.ANALYTICS_FINANCE)
    context = _executive_context(filters, show_finance=show_finance)
    context.update(_page_chrome("Executive overview", "analytics_executive", filters))
    context["show_finance"] = show_finance
    context["pages"] = _navigation_pages(show_finance)
    context["chart_data"] = _chart_data(context["charts"])
    return render(request, "dashboard/analytics/executive.html", context)


@capability_required(Capability.ANALYTICS_VIEW)
def analytics_page(request, page):
    if page not in PAGE_TITLES:
        raise Http404("Unknown analytics page.")
    if page in FINANCE_PAGES and not has_capability(request.user, Capability.ANALYTICS_FINANCE):
        raise PermissionDenied("Financial analytics requires the finance capability.")
    filters = ReportFilters.from_request(request.GET)
    show_finance = has_capability(request.user, Capability.ANALYTICS_FINANCE)
    context = _context_for_page(page, filters, show_finance=show_finance)
    context.update(_page_chrome(PAGE_TITLES[page], "analytics_page", filters))
    context["show_finance"] = show_finance
    context["page"] = page
    context["pages"] = _navigation_pages(show_finance)
    context["chart_data"] = _chart_data(context["charts"])
    return render(request, "dashboard/analytics/page.html", context)


@capability_required(Capability.ANALYTICS_VIEW)
def analytics_api(request, page):
    if page not in PAGE_TITLES:
        raise Http404("Unknown analytics page.")
    if page in FINANCE_PAGES and not has_capability(request.user, Capability.ANALYTICS_FINANCE):
        raise PermissionDenied("Financial analytics requires the finance capability.")
    filters = ReportFilters.from_request(request.GET)
    show_finance = has_capability(request.user, Capability.ANALYTICS_FINANCE)
    context = _context_for_page(page, filters, show_finance=show_finance)
    return JsonResponse(
        {
            "page": page,
            "period": filters.label(),
            "kpis": [
                {"label": k["label"], "value": str(k["value"]), "kind": k["kind"]}
                for k in context["kpis"]
            ],
            "charts": [
                {"id": c["id"], "title": c["title"], **c["payload"]} for c in context["charts"]
            ],
        }
    )


# ---------------------------------------------------------------------------
# Report builder, exports and history
# ---------------------------------------------------------------------------


@capability_required(Capability.REPORTS_BUILD)
def report_builder(request):
    capabilities = _capabilities(request.user)
    preview = None
    if request.method == "POST":
        form = ReportBuilderForm(request.POST, capabilities=capabilities)
        if form.is_valid():
            definition = get_report(form.cleaned_data["report"])
            preview = _render_preview(services.preview_report(definition, form.filters()))
    else:
        form = ReportBuilderForm(capabilities=capabilities)
    return render(
        request,
        "dashboard/analytics/builder.html",
        {
            "form": form,
            "preview": preview,
            "page_title": "Report builder",
            "active_nav": "analytics_reports",
            "breadcrumbs": [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Report history", "url": "analytics:report_history"},
                {"label": "Builder"},
            ],
        },
    )


@capability_required(Capability.REPORTS_BUILD)
@require_POST
def report_generate(request):
    capabilities = _capabilities(request.user)
    form = ReportBuilderForm(request.POST, capabilities=capabilities)
    if not form.is_valid():
        return render(
            request,
            "dashboard/analytics/builder.html",
            {
                "form": form,
                "preview": None,
                "page_title": "Report builder",
                "active_nav": "analytics_reports",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Report history", "url": "analytics:report_history"},
                    {"label": "Builder"},
                ],
            },
        )
    definition = get_report(form.cleaned_data["report"])
    export = services.create_report_export(
        definition=definition,
        filters=form.filters(),
        export_format=form.cleaned_data["format"],
        user=request.user,
    )
    services.generate_report_export(export)
    if export.is_financial:
        services.record_report_access(
            actor=request.user,
            export=export,
            action="report.financial.generated",
            request=request,
        )
    if export.status == ExecutionStatus.SUCCEEDED:
        messages.success(request, f"Report generated ({export.row_count} rows).")
    else:
        messages.error(request, f"Report generation failed: {export.error}")
    return redirect("analytics:report_download", pk=export.pk)


@capability_required(Capability.REPORTS_BUILD)
def report_history(request):
    queryset = ReportExport.objects.select_related("requested_by")
    if not has_capability(request.user, Capability.REPORTS_MANAGE):
        queryset = queryset.filter(requested_by=request.user)
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "dashboard/analytics/history.html",
        {
            "exports": page,
            "page_obj": page,
            "page_title": "Report history",
            "active_nav": "analytics_reports",
            "can_manage_reports": has_capability(request.user, Capability.REPORTS_MANAGE),
            "breadcrumbs": [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Report history"},
            ],
        },
    )


@capability_required(Capability.REPORTS_BUILD)
def report_download(request, pk):
    export = get_object_or_404(ReportExport, pk=pk)
    if not has_capability(request.user, Capability.REPORTS_MANAGE) and (
        export.requested_by_id != request.user.id
    ):
        raise PermissionDenied("You can only download reports you generated.")
    if export.is_financial and not has_capability(request.user, Capability.ANALYTICS_FINANCE):
        raise PermissionDenied("Financial reports require the finance capability.")
    if not export.file:
        raise Http404("This report has no stored file (it may have expired).")
    # Platform-generated export: no user uploaded these bytes, so no scan gate.
    enforce_downloadable(export.file, trusted=True)
    services.record_report_access(
        actor=request.user,
        export=export,
        action="report.downloaded",
        request=request,
    )
    filename = export.file.name.rsplit("/", 1)[-1]
    return FileResponse(
        export.file.open("rb"),
        as_attachment=True,
        filename=filename,
        content_type=exports.CONTENT_TYPES_BY_FORMAT.get(
            export.export_format, "application/octet-stream"
        ),
    )


# ---------------------------------------------------------------------------
# Scheduled reports
# ---------------------------------------------------------------------------


@capability_required(Capability.REPORTS_SCHEDULE)
def scheduled_list(request):
    schedules = ScheduledReport.objects.select_related("created_by").prefetch_related("recipients")
    if not has_capability(request.user, Capability.REPORTS_MANAGE):
        schedules = schedules.filter(created_by=request.user)
    return render(
        request,
        "dashboard/analytics/scheduled.html",
        {
            "schedules": schedules,
            "page_title": "Scheduled reports",
            "active_nav": "analytics_scheduled",
            "can_manage_reports": has_capability(request.user, Capability.REPORTS_MANAGE),
            "breadcrumbs": [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Scheduled reports"},
            ],
        },
    )


@capability_required(Capability.REPORTS_SCHEDULE)
def scheduled_create(request):
    capabilities = _capabilities(request.user)
    if request.method == "POST":
        form = ScheduledReportForm(request.POST, capabilities=capabilities)
        if form.is_valid():
            definition = get_report(form.cleaned_data["report"])
            services.create_scheduled_report(
                name=form.cleaned_data["name"],
                definition=definition,
                filters=form.filters(),
                frequency=form.cleaned_data["frequency"],
                export_format=form.cleaned_data["format"],
                recipients=form.cleaned_data["recipients"],
                user=request.user,
            )
            messages.success(request, "Scheduled report created.")
            return redirect("analytics:scheduled_list")
    else:
        form = ScheduledReportForm(capabilities=capabilities)
    return render(
        request,
        "dashboard/analytics/scheduled_form.html",
        {
            "form": form,
            "page_title": "New scheduled report",
            "active_nav": "analytics_scheduled",
            "breadcrumbs": [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Scheduled reports", "url": "analytics:scheduled_list"},
                {"label": "New"},
            ],
        },
    )


def _require_schedule_owner(request, scheduled):
    if not has_capability(request.user, Capability.REPORTS_MANAGE) and (
        scheduled.created_by_id != request.user.id
    ):
        raise PermissionDenied("You can only manage schedules you created.")


@capability_required(Capability.REPORTS_SCHEDULE)
@require_POST
def scheduled_toggle(request, pk):
    scheduled = get_object_or_404(ScheduledReport, pk=pk)
    _require_schedule_owner(request, scheduled)
    scheduled.is_enabled = request.POST.get("enabled") == "true"
    scheduled.save(update_fields=["is_enabled", "updated_at"])
    messages.success(request, "Schedule updated.")
    return redirect("analytics:scheduled_list")


@capability_required(Capability.REPORTS_SCHEDULE)
@require_POST
def scheduled_run_now(request, pk):
    scheduled = get_object_or_404(ScheduledReport, pk=pk)
    _require_schedule_owner(request, scheduled)
    execution = services.execute_scheduled_report(scheduled)
    if execution is None:
        messages.info(request, "That schedule already ran for this period.")
    elif execution.status == ExecutionStatus.SUCCEEDED:
        messages.success(request, f"Ran schedule ({execution.row_count} rows).")
    else:
        messages.error(request, f"Schedule run failed: {execution.error}")
    return redirect("analytics:scheduled_list")


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------


@capability_required(Capability.ANALYTICS_VIEW)
def data_quality(request):
    results = run_checks()
    return render(
        request,
        "dashboard/analytics/data_quality.html",
        {
            "results": results,
            "summary": summary(results),
            "page_title": "Data quality",
            "active_nav": "analytics_quality",
            "breadcrumbs": [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Data quality"},
            ],
        },
    )


__all__ = [
    "analytics_api",
    "analytics_page",
    "data_quality",
    "executive",
    "report_builder",
    "report_download",
    "report_generate",
    "report_history",
    "scheduled_create",
    "scheduled_list",
    "scheduled_run_now",
    "scheduled_toggle",
]

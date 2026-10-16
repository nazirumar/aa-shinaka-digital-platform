# Phase 11 — Analytics & reporting

**Status:** Complete (see owner approval before Phase 12)
**Date:** 2026-10-15

## Objective delivered

Phase 11 gives AA Shinaka a **business-intelligence and reporting layer** that is
derived entirely from the authoritative operational records and never invents a
number. It is delivered in one new domain app, **`apps.analytics`**, plus the new
capabilities in `apps.accounts` and an Analytics section in the dashboard
navigation:

- **Analytics dashboards** — an executive overview plus eight operational pages
  (sales, finance, inventory, services, export, training, customers, support),
  each with real KPIs, Chart.js visualisations and detail tables, driven by one
  allow-listed, server-built view model.
- **A controlled report builder** — 21 code-defined, allow-listed report
  definitions with typed columns and validated filters, a live preview, and
  history.
- **Dependency-free exports** — CSV, XLSX (hand-built Open XML) and PDF, with a
  spreadsheet formula-injection guard, private storage and permission-checked
  downloads.
- **Scheduled reports** — recurring report configurations with per-period
  duplicate protection, per-recipient capability re-checks and a delivery ledger.
- **Report history** — every generated file with its filters, owner and status.
- **Data-quality checks** — ten conservative, read-only integrity checks that
  surface records which would skew analytics.

The hard rules hold throughout:

- **No fabricated metrics.** Every figure is derived from the authoritative domain
  models at request time; empty states stay empty.
- **Money is per-currency.** No KPI or report ever sums across currencies;
  currency-bearing KPIs are returned per currency (or in the configured base
  currency) and conversion happens only with configured exchange rates.
- **Net receipts are cash, not profit.** The UI and docs label them explicitly and
  no profit figure is computed, because no authoritative cost/expense ledger
  exists.
- **Sales-value definitions are never mixed.** Placed value (`Order.grand_total`),
  paid value (`Payment.verified_amount`) and recognised sales are separate metrics
  and separate columns.
- **Aggregate by default.** Customer identity (name, email, phone, address) is
  absent from every dashboard and report.
- **Capabilities are enforced server-side** — in what is computed as well as what
  a page can render. Financial figures require `analytics.finance`; a user without
  it never receives the data at all.
- **No arbitrary SQL and no public file URLs.** Reports are code-defined; stored
  files are served only through a permission-checked view.
- **Sensitive financial report access is audited.**

## Files created/modified

### App — `apps.analytics` (new)

- `apps.py` — app config `AnalyticsConfig`.
- `models.py` — `ReportExport`, `ScheduledReport`, `ReportExecution`,
  `ReportDelivery`, the enumerations (`ExportFormat`, `ExecutionStatus`,
  `ScheduleFrequency`, `DeliveryStatus`) and a local `UUIDTimeStampedModel`.
- `metrics.py` — the KPI **documentation-as-code** registry: every dashboard/report
  figure with its label, definition, source, unit and required capability. Also
  used to gate financial figures.
- `filters.py` — `ReportFilters` (validated, allow-listed, JSON-safe, business-
  timezone aware), `PRESETS`, `resolve_preset`, `parse_date`, `day_start`/
  `day_end_exclusive`.
- `selectors.py` — read-only aggregations over every domain (orders, payments,
  refunds, invoices, catalog stock, services, export, training, customers,
  support). Money is always `Decimal` and always per-currency.
- `reports.py` — the allow-listed `Column`/`ReportDefinition` registry
  (`REPORT_DEFINITIONS`), 21 row builders, `get_report`, `available_reports`,
  `visible_columns`, `build_rows`, `compute_totals` (percentages deliberately not
  totalled).
- `charts.py` — Chart.js payload builders (`bar`/`line`/`doughnut` + per-page chart
  sets); payloads are JSON-safe and embedded with `json_script`.
- `exports.py` — CSV/XLSX encoders, the formula-injection `guard`, `format_cell`,
  `safe_filename`, `CONTENT_TYPES_BY_FORMAT`, and `generate(...)`.
- `pdf.py` — a minimal dependency-free PDF table renderer.
- `data_quality.py` — ten conservative checks (`CHECKS`), `run_checks()`,
  `summary()`.
- `services.py` — the write layer: `create_report_export`,
  `generate_report_export`, `preview_report`, `record_report_access`,
  `create_scheduled_report`, `deliver_report`, `execute_scheduled_report`,
  `run_due_schedules`, `cleanup_expired_exports`, `retention_days`,
  `compute_next_run_at`, `period_key_for`.
- `tasks.py` — Celery wrappers: `run_scheduled_reports`,
  `cleanup_report_exports`, `generate_report_export_task`.
- `forms.py` — `FilterFieldsMixin`, `ReportBuilderForm`, `ScheduledReportForm`.
- `views.py` — `executive`, `analytics_page`, `analytics_api`, `report_builder`,
  `report_generate`, `report_history`, `report_download`, `scheduled_list`,
  `scheduled_create`, `scheduled_toggle`, `scheduled_run_now`, `data_quality`.
- `urls.py` — the `analytics` namespace (mounted under `/dashboard/`).
- `admin.py` — **read-only** registrations (add/change disabled).
- `migrations/0001_initial.py` — the four models + indexes + the per-period
  uniqueness constraint.
- `management/commands/` — `run_scheduled_reports`, `cleanup_report_exports`,
  `check_analytics_data`.

### Capabilities, settings & navigation

- `apps/accounts/roles.py` — new capabilities `ANALYTICS_VIEW`,
  `ANALYTICS_FINANCE`, `REPORTS_BUILD`, `REPORTS_SCHEDULE`, `REPORTS_MANAGE`.
  Sales/Inventory/Training/Export officers and the Training Manager get
  `analytics.view` + `reports.build`; the Consultant gets `analytics.view`; the
  Finance Officer gets all five; Administrator/Owner hold everything.
- `config/settings/base.py` — `apps.analytics` in `LOCAL_APPS`; the
  `ANALYTICS_*` settings block; `CELERY_BEAT_SCHEDULE` entries
  `run-scheduled-reports` (hourly) and `cleanup-report-exports` (daily).
- `config/urls.py` — mounts the `analytics` namespace.
- `templates/dashboard/base.html` — capability-gated Analytics navigation.
- `templates/dashboard/analytics/` — `_filters.html`, `_kpis.html`, `_charts.html`,
  `_table.html`, `executive.html`, `page.html`, `builder.html`, `history.html`,
  `scheduled.html`, `scheduled_form.html`, `data_quality.html`.

### Documentation

- `docs/PHASE_11_COMPLETION_REPORT.md` (this file),
  `docs/ANALYTICS_METRICS.md` (the KPI reference),
  `docs/IMPLEMENTATION_ROADMAP.md`, `docs/SRS.md`, `docs/DATABASE_DESIGN.md`,
  `docs/ARCHITECTURE.md`, `docs/UI_UX_SPEC.md`, `README.md`, `.env.example`.

### Tests

- `tests/test_analytics.py` — 45 tests (access control, selectors/multi-currency,
  the report registry and builder, generation/download/ownership, financial-report
  auditing, export formats and the injection guard, retention, data quality,
  scheduling, duplicate-period protection, delivery-permission skipping).

## Migrations

- `analytics/0001_initial.py` — `ReportExecution`, `ReportDelivery`,
  `ReportExport`, `ScheduledReport`; indexes `rpt_export_key_idx`,
  `rpt_export_user_idx`, `rpt_exec_idx`; constraint
  `uniq_schedule_period_execution`.

All migrations are generated, reviewed and applied; `makemigrations --check`
reports no missing migrations.

## Models

| Model | Purpose |
|---|---|
| `ReportExport` | One generated report file plus the filters that produced it (history). `reference` (`AS-RPT-…`, unique), `report_key`, `export_format`, `filters` (JSON), `currency`, `requested_by`, `status`, `is_financial`, `row_count`, private `file`, `error`, `generated_at`, `expires_at`; `report_label` / `is_expired` properties. |
| `ScheduledReport` | A recurring report configuration: `name`, `report_key`, `filters`, `frequency` (`daily`/`weekly`/`monthly`), `export_format`, `recipients` (M2M), `is_enabled`, `next_run_at`, `last_run_at`, `created_by`; `report_label` property. |
| `ReportExecution` | One run of a schedule; also records duplicate prevention via `(scheduled_report, period_key)`. `period_key`, `triggered_by`, `export` FK, `triggered_by_user`, `row_count`, `status`, `error`, `started_at`/`finished_at`. |
| `ReportDelivery` | Delivery outcome of an execution to one recipient: `execution`, `recipient`, `email`, `status` (`pending`/`sent`/`failed`/`skipped`), `error`, `sent_at`. |

Enumerations: `ExportFormat` (`csv`/`xlsx`/`pdf`), `ExecutionStatus`
(`pending`/`running`/`succeeded`/`failed`/`expired`), `ScheduleFrequency`,
`DeliveryStatus`.

## URLs (mounted under `/dashboard/`)

```
/dashboard/executive/                              executive overview   (analytics.view)
/dashboard/analytics/<page>/                       one of eight pages   (analytics.view; finance needs analytics.finance)
/dashboard/analytics/api/<page>/                   JSON chart/KPI feed  (same gating as the page)
/dashboard/reports/builder/                         report builder       (reports.build)
/dashboard/reports/generate/                        generate + download  (reports.build)
/dashboard/reports/history/                         report history       (reports.build)
/dashboard/reports/<uuid>/download/                 permission-checked file download (reports.build + ownership/finance)
/dashboard/reports/scheduled/                       schedules            (reports.schedule)
/dashboard/reports/scheduled/new/                   new schedule         (reports.schedule)
/dashboard/reports/scheduled/<uuid>/toggle/         enable/disable       (reports.schedule + ownership)
/dashboard/reports/scheduled/<uuid>/run/            run now              (reports.schedule + ownership)
/dashboard/reports/data-quality/                    data-quality checks  (analytics.view)
```

## The report catalogue (21 allow-listed reports)

| Division | Reports |
|---|---|
| Sales | `sales_orders`, `sales_by_product`, `sales_by_category`, `sales_by_origin`, `sales_by_destination` |
| Finance | `finance_receipts`, `finance_refunds`, `finance_outstanding_invoices` |
| Inventory | `inventory_stock`, `inventory_low_stock`, `inventory_movements` |
| Services | `services_requests`, `storage_utilization` |
| Export | `export_enquiries`, `export_orders`, `export_shipments` |
| Training | `training_enrollments`, `training_attendance` |
| Customers | `customers_new_by_month` |
| Support | `support_tickets`, `support_agents` |

Reports marked `is_financial` (sales value/order totals, finance, export order
totals) are hidden from `available_reports` unless the user holds
`analytics.finance`, and their money columns are stripped from the preview and
export for anyone without it. There is no way to supply SQL, a model path or an
arbitrary field list.

## Multi-currency policy

- Every money selector returns **per-currency rows** (`receipts_by_currency`,
  `receipts_by_division`, `outstanding_invoice_balance`, …) and never a combined
  total.
- `ANALYTICS_BASE_CURRENCY` (default `NGN`) selects the reporting currency only.
  A cross-currency total is produced **only** when `ANALYTICS_EXCHANGE_RATES` is
  configured; the platform never invents a rate.

## Scheduled reports & retention

```
Celery beat (hourly) or `manage.py run_scheduled_reports`
  └─> services.run_due_schedules()
        └─> for each enabled schedule with next_run_at <= now:
              services.execute_scheduled_report()
                • period_key = period_key_for(frequency, run_at)
                • skip if a ReportExecution already exists for (schedule, period_key)
                  → at most one run per period (DB UniqueConstraint also guards races)
                • generate the export, then deliver_report()
                      · each recipient is re-checked for the report's capability
                        (finance report → analytics.finance, else reports.build)
                      · an unauthorised recipient is recorded `skipped`, never emailed
```

Retention: a generated export gets `expires_at` from
`ANALYTICS_REPORT_RETENTION_DAYS`; `manage.py cleanup_report_exports` (or the
daily Celery task) deletes files past retention and marks the records `expired`.

## Export safety

- **Formula-injection guard** — text beginning with `=`, `+`, `-`, `@`, TAB or CR
  is prefixed with an apostrophe so a spreadsheet treats it as text.
- **Type fidelity** — numeric cells stay numeric in XLSX; everything else is an
  inline string.
- **Private storage** — files live under `analytics_reports/%Y/%m/` and are served
  only through `report_download`, which re-checks ownership (or `reports.manage`),
  the finance capability for financial reports, and writes an audit entry.

## Data-quality checks

Ten read-only checks: settled payment without a verification timestamp, settled
payment without a verified amount, cancelled order with captured money, paid
invoice without a settled payment, negative stock balances, reserved exceeds
on-hand, listing/product without a unit, delivered shipment without an arrival
date, and duplicate provider references. Each returns a count, severity and a
plain description; a broken check is reported rather than hiding the rest.

## Tests

The full suite passes: **`uv run pytest` → 679 passed** (14 warnings, all
pre-existing Django 6.0 deprecation notices).

**45 new tests** in `tests/test_analytics.py`:

- **Access control**: dashboard requires login; customer forbidden; Consultant can
  view the executive overview but not the finance page or the builder; Finance
  Officer can; Sales Officer can build but cannot schedule; every one of the eight
  pages renders for an administrator; unknown page 404; the JSON API returns
  `kpis`/`charts`.
- **Selectors & multi-currency**: receipts are grouped per currency and never
  combined; `verified_receipts` is single-currency; an unverified payment is not a
  receipt; confirmed refunds reduce only the matching currency; chart payloads are
  JSON-safe.
- **Registry & builder**: unknown key returns `None`; finance reports are hidden
  without the capability and shown with it; the builder rejects a report outside
  the user's capabilities; preview renders rows.
- **Generation, history & audit**: generate → download; download is ownership/
  capability-checked; history is scoped to the owner unless `reports.manage`;
  financial-report generation writes an audit row.
- **Exports**: the formula-injection guard; CSV/`'=EVIL` escaping; XLSX is a valid
  zip; PDF has the `%PDF-` magic; `cleanup_expired_exports` removes the file and
  marks the record expired.
- **Data quality**: a settled payment missing verification is flagged.
- **Scheduling**: create view; delivery skips an unauthorised recipient and sends
  to an authorised one; at most one run per period; `run_due_schedules`; the
  management command; toggle + run-now.

## Quality gates (end of Phase 11)

Run in this order:

- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — clean.
- `uv run pytest` — **679 passed** (14 warnings, all pre-existing).
- `uv run python manage.py check` — clean.
- `uv run python manage.py makemigrations --check --dry-run` — “No changes
  detected”.
- `npm run build:css` — rebuilt after template/class changes.

## Documentation updates

- `docs/IMPLEMENTATION_ROADMAP.md` — Revision 1.1: Phase 11 delivered; dependency
  graph and requirement traceability updated.
- `docs/SRS.md` — FR-REP delivery notes, FR-DASH reporting surfaces and the
  analytics/report capabilities in the permission matrix; ASSUMPTION-11
  (retention) resolved with `ANALYTICS_REPORT_RETENTION_DAYS`.
- `docs/DATABASE_DESIGN.md` — §7 reporting models replaced with the delivered
  `apps.analytics` schema.
- `docs/ARCHITECTURE.md` — the `apps.analytics` app row, URL map, reporting
  pipeline and multi-currency policy.
- `docs/UI_UX_SPEC.md` — dashboard analytics/report/scheduled/data-quality rows.
- `docs/ANALYTICS_METRICS.md` (new) — the KPI reference.
- `README.md` — Phase 11 feature summary + report link.
- `.env.example` — the Phase 11 analytics settings block.

## Remaining work / not in scope

- **Phase 12** — Hardening, performance & deployment.
- Profit reporting remains out of scope until an authoritative cost/expense ledger
  exists (net receipts are cash, never profit).
- Cross-currency totals require a configured exchange-rate source.
- DRF remains deferred — the JSON endpoint is a same-authentication HTMX/Chart.js
  feed, not a public API.
- (Pre-existing, out of Phase 11 scope) the Phase 8 export-dashboard tile
  `overview_metrics.active_destinations` counts destinations by `is_active` only,
  whereas `export.selectors.active_destinations()` also requires
  `approval_status="approved"`. Phase 11 does not use that tile; it reports export
  data by destination grouping.
- **Phase 12 must not start without explicit owner approval.**

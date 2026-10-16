# Phase 11 build plan (internal)

New app `apps.analytics`:
- models: ReportExport, ScheduledReport, ReportExecution, ReportDelivery
- metrics.py (KPI registry), filters.py (validated filters/timezone), selectors.py (aggregations)
- reports.py (allowlisted report definitions), exports.py + pdf.py (CSV/XLSX/PDF, dependency-free)
- charts.py, data_quality.py, services.py, tasks.py, forms.py, views.py, urls.py, admin.py
- management command analytics_data_quality
- templates/analytics/**

Capabilities added to apps.accounts.roles.Capability:
ANALYTICS_VIEW, ANALYTICS_FINANCE, REPORTS_BUILD, REPORTS_SCHEDULE, REPORTS_MANAGE

Money rule: never combine currencies; per-currency lines; conversion only with configured rates.

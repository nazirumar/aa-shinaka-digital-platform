"""Analytics & reporting URLs (mounted at ``/dashboard/`` by ``config.urls``).

Namespaced ``analytics`` so templates and redirects stay stable regardless of the
prefix the project chooses.
"""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("executive/", views.executive, name="executive"),
    # The eight operational analytics pages and their JSON chart endpoint.
    path("analytics/<slug:page>/", views.analytics_page, name="page"),
    path("analytics/api/<slug:page>/", views.analytics_api, name="api"),
    # Controlled report builder, generation, history and download.
    path("reports/builder/", views.report_builder, name="report_builder"),
    path("reports/generate/", views.report_generate, name="report_generate"),
    path("reports/history/", views.report_history, name="report_history"),
    path("reports/<uuid:pk>/download/", views.report_download, name="report_download"),
    # Scheduled reports.
    path("reports/scheduled/", views.scheduled_list, name="scheduled_list"),
    path("reports/scheduled/new/", views.scheduled_create, name="scheduled_create"),
    path("reports/scheduled/<uuid:pk>/toggle/", views.scheduled_toggle, name="scheduled_toggle"),
    path("reports/scheduled/<uuid:pk>/run/", views.scheduled_run_now, name="scheduled_run_now"),
    # Data-quality checks.
    path("reports/data-quality/", views.data_quality, name="data_quality"),
]

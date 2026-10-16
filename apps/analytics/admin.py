"""Django-admin registration for analytics reporting records.

These are read-only in the admin: exports, schedules, executions and deliveries
are produced by the application, never hand-edited.
"""

from __future__ import annotations

from django.contrib import admin

from .models import ReportDelivery, ReportExecution, ReportExport, ScheduledReport


@admin.register(ReportExport)
class ReportExportAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "report_key",
        "export_format",
        "status",
        "is_financial",
        "row_count",
        "created_at",
    )
    list_filter = ("export_format", "status", "is_financial", "report_key")
    search_fields = ("reference", "report_key", "requested_by__email")
    date_hierarchy = "created_at"
    readonly_fields = (
        "reference",
        "report_key",
        "export_format",
        "filters",
        "currency",
        "requested_by",
        "status",
        "is_financial",
        "row_count",
        "file",
        "error",
        "generated_at",
        "expires_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ScheduledReport)
class ScheduledReportAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "report_key",
        "frequency",
        "export_format",
        "is_enabled",
        "next_run_at",
        "created_by",
    )
    list_filter = ("frequency", "export_format", "is_enabled", "report_key")
    search_fields = ("name", "report_key", "created_by__email")
    filter_horizontal = ("recipients",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ReportExecution)
class ReportExecutionAdmin(admin.ModelAdmin):
    list_display = (
        "report_key",
        "scheduled_report",
        "period_key",
        "status",
        "row_count",
        "started_at",
    )
    list_filter = ("status", "triggered_by", "report_key")
    search_fields = ("report_key", "period_key")
    date_hierarchy = "created_at"
    readonly_fields = (
        "scheduled_report",
        "report_key",
        "filters",
        "period_key",
        "status",
        "triggered_by",
        "row_count",
        "export",
        "triggered_by_user",
        "error",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ReportDelivery)
class ReportDeliveryAdmin(admin.ModelAdmin):
    list_display = ("email", "execution", "status", "sent_at")
    list_filter = ("status",)
    search_fields = ("email",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "execution",
        "recipient",
        "email",
        "status",
        "error",
        "sent_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

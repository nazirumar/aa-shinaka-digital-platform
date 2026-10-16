"""Read-only Django admin registrations for the export domain.

The admin is deliberately view-only: all writes go through
:mod:`apps.export.services` so transitions, compliance gates, snapshots and
audit logging cannot be bypassed.
"""

from __future__ import annotations

from django.contrib import admin

from .models import (
    ExportComplianceChecklist,
    ExportDestination,
    ExportDocument,
    ExportDocumentType,
    ExportEnquiry,
    ExportOrder,
    ExportProductProfile,
    ExportQuotation,
    ExportShipment,
    ExportTradeRestriction,
    LogisticsProvider,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ExportDestination)
class ExportDestinationAdmin(ReadOnlyAdmin):
    list_display = ("country", "approval_status", "is_active", "last_verified_at")
    list_filter = ("approval_status", "is_active")
    search_fields = ("country__name", "country_code")


@admin.register(ExportProductProfile)
class ExportProductProfileAdmin(ReadOnlyAdmin):
    list_display = ("product", "is_export_eligible", "export_availability", "export_grade")
    list_filter = ("is_export_eligible", "export_availability")
    search_fields = ("product__name",)


@admin.register(ExportTradeRestriction)
class ExportTradeRestrictionAdmin(ReadOnlyAdmin):
    list_display = ("destination", "restriction_type", "product", "category", "is_active")
    list_filter = ("restriction_type", "is_active")


@admin.register(ExportEnquiry)
class ExportEnquiryAdmin(ReadOnlyAdmin):
    list_display = ("reference", "customer", "destination", "status", "priority", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("reference", "customer__email")
    date_hierarchy = "created_at"


@admin.register(ExportQuotation)
class ExportQuotationAdmin(ReadOnlyAdmin):
    list_display = (
        "reference",
        "customer",
        "destination",
        "status",
        "currency",
        "total",
        "revision",
    )
    list_filter = ("status", "currency")
    search_fields = ("reference", "customer__email")


@admin.register(ExportOrder)
class ExportOrderAdmin(ReadOnlyAdmin):
    list_display = (
        "reference",
        "customer",
        "destination",
        "status",
        "compliance_status",
        "currency",
        "total",
    )
    list_filter = ("status", "compliance_status", "fulfillment_status")
    search_fields = ("reference", "customer__email")
    date_hierarchy = "created_at"


@admin.register(ExportDocumentType)
class ExportDocumentTypeAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "is_official", "requires_expiry", "is_active")
    list_filter = ("is_official", "requires_expiry", "is_active")
    search_fields = ("code", "name")


@admin.register(ExportDocument)
class ExportDocumentAdmin(ReadOnlyAdmin):
    list_display = (
        "reference",
        "order",
        "document_type",
        "verification_status",
        "is_customer_visible",
    )
    list_filter = ("verification_status", "is_customer_visible")
    search_fields = ("reference", "order__reference")


@admin.register(ExportComplianceChecklist)
class ExportComplianceChecklistAdmin(ReadOnlyAdmin):
    list_display = ("order", "status", "total_items", "outstanding_items", "approved_by")
    list_filter = ("status",)


@admin.register(ExportShipment)
class ExportShipmentAdmin(ReadOnlyAdmin):
    list_display = (
        "reference",
        "order",
        "provider",
        "transport_mode",
        "status",
        "estimated_arrival",
    )
    list_filter = ("transport_mode", "status")
    search_fields = ("reference", "order__reference", "tracking_reference")


@admin.register(LogisticsProvider)
class LogisticsProviderAdmin(ReadOnlyAdmin):
    list_display = ("name", "code", "contact_name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")

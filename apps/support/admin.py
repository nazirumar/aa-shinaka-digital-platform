"""Read-only admin registration for the support centre."""

from __future__ import annotations

from django.contrib import admin

from .models import SupportAttachment, SupportMessage, SupportStatusHistory, SupportTicket


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    fields = ("sender", "message", "is_internal", "created_at")
    readonly_fields = fields
    can_delete = False


@admin.register(SupportTicket)
class SupportTicketAdmin(ReadOnlyAdmin):
    list_display = (
        "reference",
        "subject",
        "customer",
        "category",
        "priority",
        "status",
        "assigned_to",
    )
    list_filter = ("status", "priority", "category")
    search_fields = ("reference", "subject", "customer__email")
    date_hierarchy = "created_at"
    inlines = [SupportMessageInline]


@admin.register(SupportMessage)
class SupportMessageAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "sender", "is_internal", "created_at")
    list_filter = ("is_internal",)


@admin.register(SupportAttachment)
class SupportAttachmentAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "original_filename", "uploaded_by", "created_at")


@admin.register(SupportStatusHistory)
class SupportStatusHistoryAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "previous_status", "new_status", "changed_by", "created_at")
    list_filter = ("new_status",)

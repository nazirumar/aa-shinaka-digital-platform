from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target_type", "target_id", "ip_address")
    list_filter = ("action", "target_type")
    search_fields = ("action", "target_type", "target_id", "note", "actor__email")
    date_hierarchy = "created_at"
    readonly_fields = (
        "actor",
        "action",
        "target_type",
        "target_id",
        "before",
        "after",
        "note",
        "ip_address",
        "user_agent",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

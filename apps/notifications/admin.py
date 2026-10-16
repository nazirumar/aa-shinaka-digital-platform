"""Read-only admin registration for the notification centre."""

from __future__ import annotations

from django.contrib import admin

from .models import Notification, NotificationDelivery, NotificationPreference


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Notification)
class NotificationAdmin(ReadOnlyAdmin):
    list_display = ("event", "category", "recipient", "is_read", "created_at")
    list_filter = ("category", "is_read", "event")
    search_fields = ("title", "recipient__email", "dedupe_key")
    date_hierarchy = "created_at"


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(ReadOnlyAdmin):
    list_display = ("user", "in_app_enabled", "email_enabled", "sms_enabled", "whatsapp_enabled")


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(ReadOnlyAdmin):
    list_display = ("notification", "channel", "status", "attempt_count", "last_attempt_at")
    list_filter = ("channel", "status")
    search_fields = ("provider_reference", "notification__recipient__email")

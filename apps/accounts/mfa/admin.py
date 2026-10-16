"""MFA admin."""

from __future__ import annotations

from django.contrib import admin

from .models import MFADevice, MFARecoveryCode


@admin.register(MFADevice)
class MFADeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "is_confirmed", "last_used_at", "created_at")
    list_filter = ("is_confirmed",)
    raw_id_fields = ("user",)
    search_fields = ("user__email",)


@admin.register(MFARecoveryCode)
class MFARecoveryCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "used_at", "created_at")
    list_filter = ("used_at",)
    raw_id_fields = ("user",)
    search_fields = ("user__email",)
    readonly_fields = ("code_hash",)

from django.contrib import admin

try:
    from apps.locations.models import LGA, NigeriaLocationImport, State
except Exception:
    from .models import LGA, NigeriaLocationImport, State  # type: ignore[no-redef]

from .models import FileScanRecord
from .upload_security import release_scan


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "zone", "is_active")
    list_filter = ("zone", "is_active")
    search_fields = ("name", "code")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(LGA)
class LGAAdmin(admin.ModelAdmin):
    list_display = ("name", "state", "code", "is_active")
    list_filter = ("state", "is_active")
    search_fields = ("name", "code")
    autocomplete_fields = ("state",)


@admin.register(NigeriaLocationImport)
class NigeriaLocationImportAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "source",
        "states_imported",
        "lgas_imported",
        "succeeded",
    )
    list_filter = ("succeeded",)
    readonly_fields = (
        "id",
        "source",
        "source_checksum",
        "states_imported",
        "lgas_imported",
        "succeeded",
        "message",
        "created_at",
    )


@admin.register(FileScanRecord)
class FileScanRecordAdmin(admin.ModelAdmin):
    """Forensics view of upload scans. Releasing a file is a capability-checked,
    audited action (see ``upload_security.release_scan``) — it cannot be done
    by editing fields here."""

    list_display = ("original_name", "kind", "status", "threat_name", "scanner", "created_at")
    list_filter = ("status", "kind", "scanner")
    search_fields = ("original_name", "sha256", "file_path", "quarantine_path")
    readonly_fields = (
        "id",
        "sha256",
        "file_path",
        "original_name",
        "size_bytes",
        "kind",
        "status",
        "scanner",
        "threat_name",
        "detail",
        "quarantine_path",
        "uploaded_by",
        "scanned_at",
        "released_at",
        "released_by",
        "created_at",
        "updated_at",
    )
    actions = ["release_selected"]

    @admin.action(description="Release selected files after review")
    def release_selected(self, request, queryset):
        released = errors = 0
        for record in queryset.exclude(
            status__in=[FileScanRecord.Status.CLEAN, FileScanRecord.Status.RELEASED]
        ):
            try:
                release_scan(record, actor=request.user, request=request)
            except Exception as exc:  # noqa: BLE001 - surfaced per-record below
                self.message_user(request, f"{record}: {exc}", level="ERROR")
                errors += 1
            else:
                released += 1
        self.message_user(request, f"{released} released, {errors} refused.")

from django.contrib import admin

try:
    from apps.locations.models import LGA, NigeriaLocationImport, State
except Exception:
    from .models import LGA, NigeriaLocationImport, State  # type: ignore[no-redef]


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

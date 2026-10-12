from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import Address, User
from .roles import sync_user_groups


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name", "role")


class CustomUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = User
    ordering = ("-date_joined",)
    list_display = ("email", "full_name", "role", "state", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active", "is_email_verified")
    search_fields = ("email", "first_name", "last_name", "phone")
    readonly_fields = ("id", "date_joined", "last_login", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone", "state")}),
        (
            "Role & status",
            {"fields": ("role", "is_email_verified", "marketing_opt_in", "last_seen_at")},
        ),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "first_name", "last_name", "role", "password1", "password2"),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Keep the role group in step with the stored role.
        sync_user_groups(obj)


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("recipient_name", "user", "city", "state", "is_default")
    list_filter = ("is_default", "state")
    search_fields = ("recipient_name", "phone", "city", "street_address", "user__email")
    autocomplete_fields = ("user", "state", "lga")

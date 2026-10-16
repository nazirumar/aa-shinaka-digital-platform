"""MFA app config."""

from django.apps import AppConfig


class MFAConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts.mfa"
    label = "accounts_mfa"

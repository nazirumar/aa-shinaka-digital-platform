"""Notification preference form (customer-controlled channels + categories)."""

from __future__ import annotations

from django import forms

from apps.accounts.forms import TailwindFormMixin

from .models import NotificationCategory


class NotificationPreferenceForm(TailwindFormMixin, forms.Form):
    in_app_enabled = forms.BooleanField(required=False, label="In-app notifications")
    email_enabled = forms.BooleanField(required=False, label="Email notifications")
    sms_enabled = forms.BooleanField(required=False, label="SMS (when configured)")
    whatsapp_enabled = forms.BooleanField(required=False, label="WhatsApp (when configured)")

    def __init__(self, *args, preference=None, **kwargs):
        super().__init__(*args, **kwargs)
        if preference is not None:
            self.fields["in_app_enabled"].initial = preference.in_app_enabled
            self.fields["email_enabled"].initial = preference.email_enabled
            self.fields["sms_enabled"].initial = preference.sms_enabled
            self.fields["whatsapp_enabled"].initial = preference.whatsapp_enabled
        # One checkbox per notification category.
        for choice in NotificationCategory:
            enabled = True
            if preference is not None and isinstance(preference.categories, dict):
                enabled = bool(preference.categories.get(choice.value, True))
            self.fields[f"category_{choice.value}"] = forms.BooleanField(
                required=False, label=choice.label, initial=enabled
            )

    def category_values(self) -> dict:
        return {
            choice.value: bool(self.cleaned_data.get(f"category_{choice.value}"))
            for choice in NotificationCategory
        }

"""Forms for the report builder, exports and schedules (Phase 11 — Tasks 12–14).

The builder is deliberately narrow: the report is a **choice** from the
allow-listed registry, the format is a choice, and every filter is either a typed
date or a value chosen from an existing record. A user can never supply a model
path, field name or SQL fragment.
"""

from __future__ import annotations

from django import forms

from apps.accounts.models import User
from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability
from apps.catalog.models import Product, Warehouse
from apps.export.models import ExportDestination
from apps.locations.models import State

from .filters import PRESETS, ReportFilters
from .models import ExportFormat, ScheduleFrequency
from .reports import available_reports


def _choices(queryset, label=lambda obj: str(obj)):
    return [("", "Any")] + [(str(obj.pk), label(obj)) for obj in queryset]


class FilterFieldsMixin(forms.Form):
    """The shared, allow-listed filter fields."""

    preset = forms.ChoiceField(
        choices=[(key, label) for key, label in PRESETS.items()],
        initial="last_30_days",
        required=False,
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    status = forms.CharField(required=False, max_length=40)
    division = forms.CharField(required=False, max_length=40)
    product_id = forms.ChoiceField(required=False, choices=[])
    warehouse_id = forms.ChoiceField(required=False, choices=[])
    state_id = forms.ChoiceField(required=False, choices=[])
    lga_id = forms.CharField(required=False, max_length=36)
    destination_id = forms.ChoiceField(required=False, choices=[])
    currency = forms.CharField(required=False, max_length=3)

    def __init__(self, *args, capabilities=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_id"].choices = _choices(Product.objects.order_by("name"))
        self.fields["warehouse_id"].choices = _choices(
            Warehouse.objects.filter(is_active=True).order_by("name")
        )
        self.fields["state_id"].choices = _choices(State.objects.order_by("name"))
        self.fields["destination_id"].choices = _choices(
            ExportDestination.objects.order_by("country__name")
        )

    def clean(self):
        data = super().clean()
        if data.get("preset") == "custom" and not (data.get("date_from") or data.get("date_to")):
            raise forms.ValidationError("Choose a start or end date for a custom range.")
        start, end = data.get("date_from"), data.get("date_to")
        if start and end and start > end:
            raise forms.ValidationError("The start date must be on or before the end date.")
        return data

    def filters(self) -> ReportFilters:
        data = self.cleaned_data
        return ReportFilters(
            preset=data.get("preset") or "last_30_days",
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            status=data.get("status", ""),
            division=data.get("division", ""),
            product_id=data.get("product_id", ""),
            warehouse_id=data.get("warehouse_id", ""),
            state_id=data.get("state_id", ""),
            lga_id=data.get("lga_id", ""),
            destination_id=data.get("destination_id", ""),
            currency=data.get("currency", ""),
        )


class ReportBuilderForm(FilterFieldsMixin):
    report = forms.ChoiceField()
    format = forms.ChoiceField(choices=ExportFormat.choices, initial=ExportFormat.CSV)

    def __init__(self, *args, capabilities=None, **kwargs):
        super().__init__(*args, capabilities=capabilities, **kwargs)
        self.capabilities = frozenset(capabilities or ())
        self.fields["report"].choices = [
            (definition.key, definition.label)
            for definition in available_reports(self.capabilities)
        ]

    def clean_report(self):
        key = self.cleaned_data["report"]
        allowed = {definition.key for definition in available_reports(self.capabilities)}
        if key not in allowed:
            raise forms.ValidationError("That report is not available to you.")
        return key


class ScheduledReportForm(FilterFieldsMixin):
    name = forms.CharField(max_length=150)
    report = forms.ChoiceField()
    format = forms.ChoiceField(choices=ExportFormat.choices, initial=ExportFormat.CSV)
    frequency = forms.ChoiceField(
        choices=ScheduleFrequency.choices, initial=ScheduleFrequency.WEEKLY
    )
    recipients = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Only staff who can build this report will receive it.",
    )

    def __init__(self, *args, capabilities=None, **kwargs):
        super().__init__(*args, capabilities=capabilities, **kwargs)
        self.capabilities = frozenset(capabilities or ())
        self.fields["report"].choices = [
            (definition.key, definition.label)
            for definition in available_reports(self.capabilities)
        ]
        self.fields["recipients"].queryset = User.objects.filter(
            is_staff=True, is_active=True
        ).order_by("email")

    def clean_report(self):
        key = self.cleaned_data["report"]
        allowed = {definition.key for definition in available_reports(self.capabilities)}
        if key not in allowed:
            raise forms.ValidationError("That report is not available to you.")
        return key

    def clean(self):
        data = super().clean()
        key = data.get("report")
        definition = next((d for d in available_reports(self.capabilities) if d.key == key), None)
        if definition is None:
            return data
        required = (
            Capability.ANALYTICS_FINANCE if definition.is_financial else Capability.REPORTS_BUILD
        )
        for recipient in data.get("recipients", []):
            if not has_capability(recipient, required):
                self.add_error(
                    "recipients",
                    f"{recipient.email} cannot access this report and will be skipped.",
                )
        return data


__all__ = ["FilterFieldsMixin", "ReportBuilderForm", "ScheduledReportForm"]

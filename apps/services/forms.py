"""Forms for the service domain (customer portal + staff dashboard).

Customer-facing forms collect intent only; every write still passes through
:mod:`apps.services.services` for validation. Staff forms are capability-gated
in the views, never in the template.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from apps.accounts.forms import TailwindFormMixin
from apps.catalog.models import UnitOfMeasure
from apps.locations.models import LGA, State

from .models import (
    ConsultancyService,
    Consultant,
    ConsultantAvailability,
    ConsultationMode,
    FarmAreaUnit,
    FarmingSeason,
    FarmingService,
    FarmProgressReport,
    FarmProject,
    FarmProjectMilestone,
    FarmVisit,
    MarketingActivity,
    MarketingCampaign,
    MarketingProposal,
    MarketingService,
    ProduceType,
    ServiceComment,
    ServicePriority,
    StorageFacility,
    StorageServiceRequest,
    StorageUnit,
)

User = get_user_model()


class ServiceForm(TailwindFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class ServiceModelForm(TailwindFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


# ---------------------------------------------------------------------------
# Customer-facing
# ---------------------------------------------------------------------------


class ConsultationBookingForm(ServiceForm):
    service = forms.ModelChoiceField(
        queryset=ConsultancyService.objects.none(), label="Consultation type"
    )
    mode = forms.ChoiceField(choices=ConsultationMode.choices, initial=ConsultationMode.ONLINE)
    preferred_start = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    state = forms.ModelChoiceField(
        queryset=State.objects.order_by("name"), required=False, label="State"
    )
    lga = forms.ModelChoiceField(queryset=LGA.objects.none(), required=False, label="LGA")
    address = forms.CharField(required=False, label="On-site address")
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="What would you like help with?",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = ConsultancyService.objects.filter(is_active=True)
        state_id = self.data.get("state") or (self.initial.get("state") if self.initial else None)
        if state_id:
            self.fields["lga"].queryset = LGA.objects.filter(state_id=state_id).order_by("name")


class FarmServiceRequestForm(ServiceForm):
    requested_service = forms.ModelChoiceField(
        queryset=FarmingService.objects.none(), required=False, label="Service needed"
    )
    farm_location = forms.CharField(max_length=240)
    state = forms.ModelChoiceField(queryset=State.objects.order_by("name"), required=False)
    lga = forms.ModelChoiceField(queryset=LGA.objects.none(), required=False)
    farm_size = forms.DecimalField(required=False, min_value=0, decimal_places=2, max_digits=12)
    area_unit = forms.ChoiceField(choices=FarmAreaUnit.choices, initial=FarmAreaUnit.HECTARE)
    crop_type = forms.CharField(max_length=120, required=False)
    season = forms.ChoiceField(choices=FarmingSeason.choices, initial=FarmingSeason.ALL_YEAR)
    expected_start_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    budget_min = forms.DecimalField(required=False, min_value=0, decimal_places=2)
    budget_max = forms.DecimalField(required=False, decimal_places=2)
    additional_requirements = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requested_service"].queryset = FarmingService.objects.filter(is_active=True)


class MarketingEnquiryForm(ServiceForm):
    service = forms.ModelChoiceField(
        queryset=MarketingService.objects.none(), required=False, label="Marketing service"
    )
    product_type = forms.CharField(max_length=150)
    available_quantity = forms.DecimalField(max_digits=12, decimal_places=3, min_value=0, initial=0)
    unit = forms.ModelChoiceField(
        queryset=UnitOfMeasure.objects.none(), required=False, label="Unit of measure"
    )
    product_location = forms.CharField(max_length=240, required=False)
    target_market = forms.CharField(max_length=200, required=False)
    marketing_requirements = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}), required=False
    )
    preferred_timeline = forms.CharField(max_length=120, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = MarketingService.objects.filter(is_active=True)
        self.fields["unit"].queryset = UnitOfMeasure.objects.filter(is_active=True)


class StorageRequestForm(ServiceForm):
    produce_type = forms.ModelChoiceField(
        queryset=ProduceType.objects.none(), required=False, label="Produce type"
    )
    quantity = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    unit = forms.ModelChoiceField(
        queryset=UnitOfMeasure.objects.none(), required=False, label="Unit of measure"
    )
    preferred_facility = forms.ModelChoiceField(
        queryset=StorageFacility.objects.none(), required=False, label="Preferred facility"
    )
    preferred_location = forms.CharField(max_length=240, required=False)
    requested_start_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    requested_end_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    special_handling = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produce_type"].queryset = ProduceType.objects.filter(is_active=True)
        self.fields["unit"].queryset = UnitOfMeasure.objects.filter(is_active=True)
        self.fields["preferred_facility"].queryset = StorageFacility.objects.filter(is_active=True)


class QuotationDecisionForm(ServiceForm):
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)


# ---------------------------------------------------------------------------
# Staff — shared
# ---------------------------------------------------------------------------


class StaffReviewForm(ServiceForm):
    priority = forms.ChoiceField(choices=ServicePriority.choices, required=False)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)


class AssignStaffForm(ServiceForm):
    staff = forms.ModelChoiceField(queryset=User.objects.none())
    role = forms.CharField(max_length=40, required=False)
    note = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = User.objects.filter(is_staff=True).order_by("email")


class CommentForm(ServiceModelForm):
    class Meta:
        model = ServiceComment
        fields = ("body", "visibility")
        widgets = {"body": forms.Textarea(attrs={"rows": 3})}


# ---------------------------------------------------------------------------
# Staff — consultancy
# ---------------------------------------------------------------------------


class ConsultantForm(ServiceModelForm):
    class Meta:
        model = Consultant
        fields = ("user", "headline", "specializations", "is_active")
        widgets = {"bio": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = User.objects.filter(is_staff=True).order_by("email")


class ConsultantAvailabilityForm(ServiceModelForm):
    class Meta:
        model = ConsultantAvailability
        fields = ("weekday", "specific_date", "start_time", "end_time", "is_active")
        widgets = {
            "specific_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }


class ConfirmAppointmentForm(ServiceForm):
    consultant = forms.ModelChoiceField(queryset=Consultant.objects.none())
    scheduled_start = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    scheduled_end = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}), required=False
    )
    meeting_url = forms.URLField(required=False)
    location = forms.CharField(max_length=240, required=False)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["consultant"].queryset = Consultant.objects.filter(is_active=True)


class ConsultationReportForm(ServiceForm):
    summary = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    findings = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), required=False)
    recommendations = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), required=False)
    file = forms.FileField(required=False)
    is_customer_visible = forms.BooleanField(required=False, initial=True)


# ---------------------------------------------------------------------------
# Staff — farming
# ---------------------------------------------------------------------------


class FarmProjectForm(ServiceModelForm):
    class Meta:
        model = FarmProject
        fields = ("name", "manager", "start_date", "end_date", "notes")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = User.objects.filter(is_staff=True).order_by("email")


class FarmProjectAgreementForm(ServiceForm):
    agreement_reference = forms.CharField(max_length=80)


class FarmMilestoneForm(ServiceModelForm):
    class Meta:
        model = FarmProjectMilestone
        fields = ("title", "description", "sequence", "due_date", "status")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }


class FarmProgressReportForm(ServiceModelForm):
    class Meta:
        model = FarmProgressReport
        fields = ("title", "summary", "progress_percent", "visit", "file", "is_customer_visible")
        widgets = {"summary": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["visit"].queryset = (
            FarmVisit.objects.filter(project=project) if project else FarmVisit.objects.none()
        )
        self.fields["visit"].required = False


class FarmVisitForm(ServiceModelForm):
    class Meta:
        model = FarmVisit
        fields = ("officer", "scheduled_date", "visit_date", "purpose", "notes", "status")
        widgets = {
            "scheduled_date": forms.DateInput(attrs={"type": "date"}),
            "visit_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


# ---------------------------------------------------------------------------
# Staff — marketing
# ---------------------------------------------------------------------------


class MarketingProposalForm(ServiceModelForm):
    class Meta:
        model = MarketingProposal
        fields = ("title", "scope", "approach")
        widgets = {
            "scope": forms.Textarea(attrs={"rows": 4}),
            "approach": forms.Textarea(attrs={"rows": 4}),
        }


class MarketingCampaignForm(ServiceModelForm):
    class Meta:
        model = MarketingCampaign
        fields = ("name", "officer", "start_date", "end_date", "targets")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "targets": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["officer"].queryset = User.objects.filter(is_staff=True).order_by("email")


class MarketingActivityForm(ServiceModelForm):
    class Meta:
        model = MarketingActivity
        fields = ("occurred_on", "title", "description", "outcome", "file")
        widgets = {
            "occurred_on": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "outcome": forms.Textarea(attrs={"rows": 3}),
        }


# ---------------------------------------------------------------------------
# Staff — storage
# ---------------------------------------------------------------------------


class StorageFacilityForm(ServiceModelForm):
    class Meta:
        model = StorageFacility
        fields = (
            "name",
            "location",
            "state",
            "lga",
            "capacity",
            "capacity_unit",
            "accepted_produce_types",
            "storage_conditions",
            "is_active",
            "notes",
        )
        widgets = {
            "storage_conditions": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "accepted_produce_types": forms.SelectMultiple(attrs={"size": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["accepted_produce_types"].queryset = ProduceType.objects.order_by("name")


class StorageUnitForm(ServiceModelForm):
    class Meta:
        model = StorageUnit
        fields = (
            "name",
            "capacity",
            "capacity_unit",
            "storage_conditions",
            "is_active",
            "sort_order",
        )


class StorageBookingForm(ServiceForm):
    facility = forms.ModelChoiceField(queryset=StorageFacility.objects.none())
    unit = forms.ModelChoiceField(queryset=StorageUnit.objects.none(), required=False)
    quantity = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, storage_request: StorageServiceRequest | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["facility"].queryset = StorageFacility.objects.filter(is_active=True)
        facility_id = None
        if self.is_bound:
            facility_id = self.data.get("facility")
        elif storage_request and storage_request.preferred_facility_id:
            facility_id = storage_request.preferred_facility_id
        self.fields["unit"].queryset = (
            StorageUnit.objects.filter(facility_id=facility_id)
            if facility_id
            else StorageUnit.objects.none()
        )
        if storage_request and not self.is_bound:
            self.fields["quantity"].initial = storage_request.quantity
            self.fields["start_date"].initial = storage_request.requested_start_date
            self.fields["end_date"].initial = storage_request.requested_end_date


class StorageCheckForm(ServiceForm):
    quantity = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    condition_notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

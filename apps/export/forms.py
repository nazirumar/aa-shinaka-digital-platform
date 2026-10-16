"""Forms for the export domain (customer portal + staff dashboard).

Customer forms collect intent only; every write still passes through
:mod:`apps.export.services` for validation. Staff forms are capability-gated in
the views, never in the template.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from apps.accounts.forms import TailwindFormMixin
from apps.catalog.models import Product, ProductListing, PublishStatus, UnitOfMeasure
from apps.locations.models import LGA

from .models import (
    ComplianceItemStatus,
    DocumentReviewDecision,
    ExportDestination,
    ExportDestinationRequirement,
    ExportDocument,
    ExportDocumentRequirement,
    ExportDocumentType,
    ExportEnquiry,
    ExportProductProfile,
    ExportQuotation,
    ExportShipment,
    ExportTradeRestriction,
    LogisticsProvider,
    RequirementType,
    RestrictionType,
    ShipmentStatus,
    TransportMode,
)
from .validators import validate_export_document

User = get_user_model()

PUBLISHED = [PublishStatus.PUBLISHED, PublishStatus.ARCHIVED]


class ExportForm(TailwindFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class ExportModelForm(TailwindFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class _DateInput(forms.DateInput):
    input_type = "date"


# ---------------------------------------------------------------------------
# Task 2 — product configuration
# ---------------------------------------------------------------------------


class ExportProductProfileForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExportProductProfile
        fields = [
            "is_export_eligible",
            "export_grade",
            "packaging_requirements",
            "min_export_quantity",
            "min_export_unit",
            "weight_unit",
            "export_availability",
            "requires_inspection",
            "inspection_notes",
            "allowed_destinations",
            "notes",
        ]
        widgets = {"specifications": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["allowed_destinations"].queryset = ExportDestination.objects.select_related(
            "country"
        )


# ---------------------------------------------------------------------------
# Customer — enquiry
# ---------------------------------------------------------------------------


class EnquiryForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExportEnquiry
        fields = [
            "destination",
            "origin_state",
            "origin_lga",
            "delivery_destination",
            "preferred_shipping_mode",
            "requested_delivery_period",
            "requested_delivery_date",
            "packaging_requirements",
            "additional_requirements",
            "priority",
        ]
        widgets = {"requested_delivery_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["destination"].queryset = ExportDestination.objects.filter(
            is_active=True, approval_status="approved"
        ).select_related("country")
        self.fields["origin_lga"].queryset = LGA.objects.select_related("state")

    def clean(self):
        cleaned = super().clean()
        state = cleaned.get("origin_state")
        lga = cleaned.get("origin_lga")
        if state and lga and lga.state_id != state.pk:
            self.add_error("origin_lga", "Choose an LGA within the selected state.")
        return cleaned


class EnquiryItemForm(TailwindFormMixin, forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.none())
    listing = forms.ModelChoiceField(queryset=ProductListing.objects.none(), required=False)
    quantity = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0)
    unit = forms.ModelChoiceField(queryset=UnitOfMeasure.objects.none(), required=False)
    packaging_requirements = forms.CharField(max_length=255, required=False)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["product"].queryset = Product.objects.filter(
            status=PublishStatus.PUBLISHED, export_profile__isnull=False
        ).select_related("category")
        self.fields["listing"].queryset = ProductListing.objects.all()
        self.fields["unit"].queryset = UnitOfMeasure.objects.filter(is_active=True)


EnquiryItemFormSet = forms.formset_factory(EnquiryItemForm, extra=1, min_num=1, validate_min=True)


# ---------------------------------------------------------------------------
# Staff — destinations
# ---------------------------------------------------------------------------


class DestinationForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExportDestination
        fields = [
            "country",
            "supported_categories",
            "requirements_summary",
            "notes",
            "last_verified_at",
        ]
        widgets = {"last_verified_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        if self.instance.pk is None:
            self.fields["country"].queryset = self.fields["country"].queryset.exclude(
                export_destinations__isnull=False
            )


class DestinationRequirementForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExportDestinationRequirement
        fields = [
            "title",
            "description",
            "requirement_type",
            "category",
            "product",
            "document_type",
            "is_mandatory",
            "source",
            "source_reference",
            "review_interval_days",
            "last_verified_at",
            "is_active",
        ]
        widgets = {"last_verified_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["requirement_type"].initial = RequirementType.DOCUMENTATION


class TradeRestrictionForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExportTradeRestriction
        fields = [
            "category",
            "product",
            "restriction_type",
            "description",
            "source",
            "source_reference",
            "last_verified_at",
            "is_active",
        ]
        widgets = {"last_verified_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["restriction_type"].initial = RestrictionType.PROHIBITED


class DocumentRequirementForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExportDocumentRequirement
        fields = [
            "document_type",
            "category",
            "product",
            "source",
            "last_verified_at",
        ]
        widgets = {"last_verified_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


# ---------------------------------------------------------------------------
# Staff — enquiries & quotations
# ---------------------------------------------------------------------------


class EnquiryNoteForm(TailwindFormMixin, forms.Form):
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class AssignmentForm(TailwindFormMixin, forms.Form):
    assignee = forms.ModelChoiceField(queryset=get_user_model().objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["assignee"].queryset = (
            get_user_model().objects.filter(is_staff=True).order_by("email")
        )


class QuotationForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExportQuotation
        fields = [
            "currency",
            "incoterm",
            "incoterm_version",
            "named_place",
            "payment_terms",
            "delivery_terms",
            "valid_until",
            "deposit_percentage",
            "exchange_rate_reference",
            "notes",
        ]
        widgets = {"valid_until": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["incoterm_version"].initial = "2020"


class QuotationItemForm(TailwindFormMixin, forms.Form):
    charge_type = forms.ChoiceField(
        choices=[
            ("product", "Product cost"),
            ("packaging", "Packaging"),
            ("transport", "Transport"),
            ("insurance", "Insurance"),
            ("handling", "Handling"),
            ("other", "Other charge"),
        ]
    )
    product = forms.ModelChoiceField(queryset=Product.objects.none(), required=False)
    description = forms.CharField(max_length=255)
    quantity = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0, initial=1)
    unit = forms.ModelChoiceField(queryset=UnitOfMeasure.objects.none(), required=False)
    unit_price = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    sort_order = forms.IntegerField(required=False, initial=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["product"].queryset = Product.objects.filter(
            status=PublishStatus.PUBLISHED
        ).select_related("category")
        self.fields["unit"].queryset = UnitOfMeasure.objects.filter(is_active=True)


QuotationItemFormSet = forms.formset_factory(
    QuotationItemForm, extra=1, min_num=1, validate_min=True
)


class ReviseQuotationForm(TailwindFormMixin, forms.Form):
    summary = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    valid_until = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))


# ---------------------------------------------------------------------------
# Staff — documents & compliance
# ---------------------------------------------------------------------------


class DocumentForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExportDocument
        fields = [
            "document_type",
            "file",
            "issuing_organization",
            "document_reference",
            "issue_date",
            "expiration_date",
            "is_customer_visible",
        ]
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "expiration_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["document_type"].queryset = ExportDocumentType.objects.filter(is_active=True)

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            validate_export_document(file)
        return file


class UserDocumentForm(TailwindFormMixin, forms.Form):
    """Customer-facing upload form (their own order only)."""

    document_type = forms.ModelChoiceField(
        queryset=ExportDocumentType.objects.filter(is_active=True)
    )
    file = forms.FileField()
    document_reference = forms.CharField(max_length=160, required=False)
    expiration_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            validate_export_document(file)
        return file


class DocumentReviewForm(TailwindFormMixin, forms.Form):
    decision = forms.ChoiceField(choices=DocumentReviewDecision.choices)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    expiration_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["decision"].initial = DocumentReviewDecision.APPROVED


class ComplianceItemForm(TailwindFormMixin, forms.Form):
    status = forms.ChoiceField(choices=ComplianceItemStatus.choices)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class ComplianceApprovalForm(TailwindFormMixin, forms.Form):
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


# ---------------------------------------------------------------------------
# Staff — shipments & logistics
# ---------------------------------------------------------------------------


class ShipmentForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExportShipment
        fields = [
            "provider",
            "transport_mode",
            "origin",
            "destination",
            "departure_date",
            "estimated_arrival",
            "tracking_reference",
            "notes",
        ]
        widgets = {
            "departure_date": forms.DateInput(attrs={"type": "date"}),
            "estimated_arrival": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        self.fields["provider"].queryset = LogisticsProvider.objects.filter(is_active=True)
        self.fields["transport_mode"].choices = TransportMode.choices
        self.fields["transport_mode"].initial = TransportMode.SEA


class ShipmentStatusForm(TailwindFormMixin, forms.Form):
    status = forms.ChoiceField(choices=ShipmentStatus.choices)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class ShipmentMilestoneForm(TailwindFormMixin, forms.Form):
    status = forms.ChoiceField(choices=ShipmentStatus.choices)
    occurred_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    location = forms.CharField(max_length=200, required=False)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class LogisticsProviderForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = LogisticsProvider
        fields = [
            "name",
            "code",
            "contact_name",
            "contact_email",
            "contact_phone",
            "tracking_url_template",
            "is_active",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


# ---------------------------------------------------------------------------
# Staff — order filters
# ---------------------------------------------------------------------------


class OrderStatusForm(TailwindFormMixin, forms.Form):
    status = forms.ChoiceField(choices=[("", "—")])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()

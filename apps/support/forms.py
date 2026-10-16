"""Support-centre forms (customer + staff)."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.accounts.forms import TailwindFormMixin

from .links import eligible_records, resolve_related
from .models import SupportRelatedType, SupportTicket
from .validators import validate_attachment


class SupportTicketForm(TailwindFormMixin, forms.ModelForm):
    """Customer 'new ticket' form with an ownership-checked related record."""

    message = forms.CharField(
        label="How can we help?",
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "Describe your enquiry…"}),
    )
    related = forms.ChoiceField(required=False, label="Related record")

    class Meta:
        model = SupportTicket
        fields = ("category", "priority", "subject")

    def __init__(self, *args, customer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        choices: list[tuple[str, str]] = [("", "— Not linked to a record —")]
        if customer is not None:
            for related_type, records in eligible_records(customer).items():
                label = SupportRelatedType(related_type).label
                for record in records:
                    choices.append(
                        (f"{related_type}|{record['id']}", f"{label}: {record['label']}")
                    )
        self.fields["related"].choices = choices

    def clean(self):
        cleaned = super().clean()
        related = cleaned.get("related") or ""
        if related:
            related_type, _, related_id = related.partition("|")
            try:
                resolve_related(self.customer, related_type, related_id)
            except ValidationError as exc:
                self.add_error("related", exc)
            else:
                cleaned["related_type"] = related_type
                cleaned["related_id"] = related_id
        else:
            cleaned["related_type"] = ""
            cleaned["related_id"] = ""
        return cleaned


class SupportReplyForm(TailwindFormMixin, forms.Form):
    message = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={"rows": 4}),
    )


class SupportStaffReplyForm(SupportReplyForm):
    is_internal = forms.BooleanField(
        required=False,
        label="Internal note (not visible to the customer)",
    )


class SupportAttachmentForm(TailwindFormMixin, forms.Form):
    file = forms.FileField(label="Attachment")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        validate_attachment(upload)
        return upload


class SupportAssignForm(TailwindFormMixin, forms.Form):
    assignee = forms.ModelChoiceField(queryset=None, label="Assign to", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields["assignee"].queryset = User.objects.filter(is_staff=True).order_by("email")


class SupportStatusForm(TailwindFormMixin, forms.Form):
    status = forms.ChoiceField(label="New status")
    reason = forms.CharField(required=False, label="Reason", max_length=255)

    def __init__(self, *args, allowed=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed is not None:
            self.fields["status"].choices = allowed

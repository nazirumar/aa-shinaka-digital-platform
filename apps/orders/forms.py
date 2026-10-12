"""Forms for the order app (public checkout/cart, quotations, staff dashboard).

Model forms reuse ``TailwindFormMixin`` so widgets match the rest of the site.
Choice fields that depend on a specific order (status transitions) or user
(addresses) are populated in ``__init__`` — nothing is hardcoded.
"""

from __future__ import annotations

from django import forms
from django.urls import reverse

from apps.accounts.forms import TailwindFormMixin
from apps.accounts.models import Address
from apps.locations.models import LGA, State

from .models import (
    OrderStatus,
    QuotationStatus,
    Shipment,
    ShipmentStatus,
    ShippingMethod,
    ShippingRate,
    ShippingZone,
)


class OrdersForm(TailwindFormMixin, forms.ModelForm):
    """Base ModelForm applying the shared Tailwind widget styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class OrdersPlainForm(TailwindFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


# ---------------------------------------------------------------------------
# Shipping configuration (staff)
# ---------------------------------------------------------------------------


class ShippingZoneForm(OrdersForm):
    states = forms.ModelMultipleChoiceField(
        queryset=State.objects.order_by("name"),
        required=False,
        widget=forms.SelectMultiple(attrs={"size": 12}),
        help_text="States served by this zone. Leave empty to configure later.",
    )

    class Meta:
        model = ShippingZone
        fields = ("name", "code", "description", "states", "is_active")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class ShippingMethodForm(OrdersForm):
    class Meta:
        model = ShippingMethod
        fields = ("name", "code", "description", "sort_order", "is_active")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class ShippingRateForm(OrdersForm):
    class Meta:
        model = ShippingRate
        fields = ("zone", "method", "fee", "free_over", "min_order_amount", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["zone"].queryset = ShippingZone.objects.order_by("name")
        self.fields["method"].queryset = ShippingMethod.objects.order_by("sort_order", "name")
        for name in ("fee", "free_over", "min_order_amount"):
            self.fields[name].required = name != "free_over"


# ---------------------------------------------------------------------------
# Order status / payment (staff)
# ---------------------------------------------------------------------------


class OrderStatusForm(OrdersPlainForm):
    status = forms.ChoiceField(choices=[])
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = order.allowed_transitions() if order is not None else frozenset()
        choices = [("", "— Select next status —")]
        choices += [(value, label) for value, label in OrderStatus.choices if value in allowed]
        self.fields["status"].choices = choices


class ConfirmPaymentForm(OrdersPlainForm):
    reference = forms.CharField(
        max_length=100,
        required=False,
        help_text="Bank transfer / POS reference or approval note.",
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class ShipmentForm(OrdersForm):
    class Meta:
        model = Shipment
        fields = ("method", "carrier", "tracking_number", "status", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].queryset = ShippingMethod.objects.filter(is_active=True)


class ShipmentStatusForm(OrdersPlainForm):
    status = forms.ChoiceField(choices=ShipmentStatus.choices)
    tracking_number = forms.CharField(max_length=120, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------


class QuotationReviewForm(OrdersPlainForm):
    status = forms.ChoiceField(choices=QuotationStatus.choices)
    response_note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class QuotationRequestForm(OrdersPlainForm):
    quantity = forms.DecimalField(
        max_digits=14, decimal_places=3, min_value="0.001", label="Quantity needed"
    )
    packaging = forms.CharField(max_length=64, required=False)
    destination_state = forms.ModelChoiceField(
        queryset=State.objects.order_by("name"), required=False, empty_label="— Select state —"
    )
    destination_lga = forms.ModelChoiceField(
        queryset=LGA.objects.none(), required=False, empty_label="— Select LGA —"
    )
    destination_note = forms.CharField(max_length=255, required=False)
    requirements = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    contact_name = forms.CharField(max_length=150)
    contact_email = forms.EmailField()
    contact_phone = forms.CharField(max_length=20, required=False)

    def __init__(self, *args, state_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        if state_id:
            self.fields["destination_lga"].queryset = LGA.objects.filter(
                state_id=state_id
            ).order_by("name")
        self.fields["destination_state"].widget.attrs.update(
            {
                "hx-get": reverse("accounts:lga_options"),
                "hx-target": "#id_destination_lga",
                "hx-trigger": "change",
                "hx-vals": "js:{state: event.target.value}",
            }
        )


# ---------------------------------------------------------------------------
# Public checkout
# ---------------------------------------------------------------------------


class CheckoutForm(OrdersPlainForm):
    address = forms.ModelChoiceField(queryset=Address.objects.none(), label="Delivery address")
    shipping_method = forms.ModelChoiceField(
        queryset=ShippingMethod.objects.none(), label="Delivery method"
    )
    customer_note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Order notes"
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and getattr(user, "is_authenticated", False):
            self.fields["address"].queryset = Address.objects.filter(
                user=user, is_active=True
            ).order_by("-is_default", "recipient_name")
        self.fields["shipping_method"].queryset = ShippingMethod.objects.filter(
            is_active=True
        ).order_by("sort_order", "name")
        self.fields["address"].widget.attrs.update(
            {
                "hx-get": reverse("orders:checkout_shipping_options"),
                "hx-target": "#shipping-options",
                "hx-swap": "outerHTML",
                "hx-trigger": "change",
            }
        )

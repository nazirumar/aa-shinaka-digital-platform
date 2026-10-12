"""Forms for the catalogue dashboard and the public shop filters.

Model forms reuse ``TailwindFormMixin`` so widgets match the rest of the site.
The public filter form is read straight from ``request.GET`` by the views; the
selectors do the querying. Nothing here hardcodes categories, units or prices.
"""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.urls import reverse

from apps.accounts.forms import TailwindFormMixin
from apps.locations.models import LGA, State

from .models import (
    Category,
    ListingPrice,
    MarketReferencePrice,
    PriceType,
    Product,
    ProductImage,
    ProductListing,
    ProductVariant,
    StockMovementKind,
    UnitOfMeasure,
    Warehouse,
    WholesalePriceTier,
)


class CatalogForm(TailwindFormMixin, forms.ModelForm):
    """Base ModelForm applying the shared Tailwind widget styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


class CategoryForm(CatalogForm):
    class Meta:
        model = Category
        fields = (
            "parent",
            "name",
            "description",
            "image",
            "is_active",
            "is_featured",
            "sort_order",
            "seo_title",
            "seo_description",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Category.objects.filter(is_active=True)
        if self.instance.pk:
            # A category may not be parented to itself or its own descendants.
            excluded = [self.instance.pk, *self.instance.descendants().values_list("id", flat=True)]
            queryset = queryset.exclude(pk__in=excluded)
        self.fields["parent"].queryset = queryset.order_by("name")
        self.fields["parent"].label = "Parent category"
        self.fields["parent"].empty_label = "— Top level —"
        self.fields["parent"].required = False


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


class ProductForm(CatalogForm):
    class Meta:
        model = Product
        fields = (
            "name",
            "category",
            "short_description",
            "description",
            "unit",
            "variety",
            "grade",
            "harvest_season",
            "tags",
            "seo_title",
            "seo_description",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "tags": forms.SelectMultiple(attrs={"size": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.order_by("name")
        self.fields["unit"].queryset = UnitOfMeasure.objects.filter(is_active=True)
        self.fields["unit"].empty_label = "— Select unit —"


ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImage,
    fields=("image", "alt_text", "listing", "sort_order"),
    extra=1,
    can_delete=True,
)


class ProductImageForm(CatalogForm):
    class Meta:
        model = ProductImage
        fields = ("image", "alt_text", "listing", "sort_order")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        product = getattr(self.instance, "product", None)
        self.fields["listing"].queryset = (
            ProductListing.objects.filter(product=product)
            if product
            else ProductListing.objects.none()
        )
        self.fields["listing"].required = False


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


class ListingForm(CatalogForm):
    class Meta:
        model = ProductListing
        fields = (
            "product",
            "state",
            "lga",
            "package_size",
            "package_unit",
            "compare_at_price",
            "low_stock_threshold",
            "origin_verification",
            "origin_note",
        )
        widgets = {"origin_note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.order_by("name")
        self.fields["state"].queryset = State.objects.filter(is_active=True).order_by("name")
        self.fields["state"].empty_label = "— Select state —"
        self.fields["lga"].queryset = LGA.objects.filter(is_active=True).order_by("name")
        self.fields["lga"].empty_label = "— Select LGA —"
        self.fields["package_unit"].queryset = UnitOfMeasure.objects.filter(is_active=True)
        self.fields["package_unit"].empty_label = "— Select unit —"
        state = self.data.get("state") or getattr(self.instance, "state_id", None)
        if state:
            self.fields["lga"].queryset = self.fields["lga"].queryset.filter(state_id=state)
        # Dependent dropdown: changing the state refreshes the LGA <option> list.
        self.fields["state"].widget.attrs.update(
            {
                "hx-get": reverse("catalog:lga_options"),
                "hx-target": "#id_lga",
                "hx-trigger": "change",
                "hx-include": "this",
            }
        )

    def clean(self):
        cleaned = super().clean()
        state = cleaned.get("state")
        lga = cleaned.get("lga")
        if state and lga and lga.state_id != state.pk:
            self.add_error("lga", "The LGA must belong to the selected state.")
        return cleaned


class VariantForm(CatalogForm):
    class Meta:
        model = ProductVariant
        fields = ("name", "notes", "sort_order", "is_active")
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class ListingPriceForm(CatalogForm):
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.none(), required=False)
    valid_from = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"],
    )
    valid_to = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"],
    )

    class Meta:
        model = ListingPrice
        fields = ("amount", "compare_at", "price_type", "variant", "valid_from", "valid_to")

    def __init__(self, *args, listing: ProductListing | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if listing is not None:
            self.fields["variant"].queryset = listing.variants.order_by("sort_order", "name")
        self.fields["price_type"].initial = PriceType.SELLING

    def clean(self):
        cleaned = super().clean()
        valid_from = cleaned.get("valid_from")
        valid_to = cleaned.get("valid_to")
        if valid_from and valid_to and valid_from > valid_to:
            self.add_error("valid_to", "'Valid from' must be before 'Valid to'.")
        return cleaned


class StockAdjustForm(TailwindFormMixin, forms.Form):
    kind = forms.ChoiceField(
        choices=StockMovementKind.choices, initial=StockMovementKind.ADJUSTMENT
    )
    delta = forms.DecimalField(
        max_digits=14,
        decimal_places=3,
        label="Quantity change",
        help_text="Use a negative value to reduce stock on hand.",
    )
    reference = forms.CharField(max_length=100, required=False)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def clean_delta(self):
        delta = self.cleaned_data["delta"]
        if delta == 0:
            raise ValidationError("Enter a non-zero quantity change.")
        return delta


class WholesaleTierForm(CatalogForm):
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.none(), required=False)

    class Meta:
        model = WholesalePriceTier
        fields = ("variant", "min_quantity", "price")

    def __init__(self, *args, listing: ProductListing | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if listing is not None:
            self.fields["variant"].queryset = listing.variants.order_by("sort_order", "name")


# ---------------------------------------------------------------------------
# Warehouses & inventory (Phase 5)
# ---------------------------------------------------------------------------


class WarehouseForm(CatalogForm):
    class Meta:
        model = Warehouse
        fields = ("name", "code", "address", "state", "lga", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["state"].queryset = State.objects.order_by("name")
        self.fields["state"].required = False
        self.fields["state"].empty_label = "— Select state —"
        self.fields["lga"].queryset = LGA.objects.order_by("state__name", "name")
        self.fields["lga"].required = False
        self.fields["lga"].empty_label = "— Select LGA —"

    def clean(self):
        cleaned = super().clean()
        state = cleaned.get("state")
        lga = cleaned.get("lga")
        if lga is not None and state is not None and lga.state_id != state.id:
            self.add_error("lga", "The LGA must belong to the selected state.")
        return cleaned


class StockReceiveForm(TailwindFormMixin, forms.Form):
    """Receive stock into a warehouse for a specific listing/variant."""

    quantity = forms.DecimalField(max_digits=14, decimal_places=3, min_value="0.001")
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none(), required=False)
    reference = forms.CharField(max_length=100, required=False)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True).order_by(
            "name"
        )


class StockTransferForm(TailwindFormMixin, forms.Form):
    """Move unreserved stock between two warehouses."""

    quantity = forms.DecimalField(max_digits=14, decimal_places=3, min_value="0.001")
    from_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none())
    to_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none())
    reference = forms.CharField(max_length=100, required=False)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        warehouses = Warehouse.objects.filter(is_active=True).order_by("name")
        self.fields["from_warehouse"].queryset = warehouses
        self.fields["to_warehouse"].queryset = warehouses

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("from_warehouse")
        destination = cleaned.get("to_warehouse")
        if source is not None and destination is not None and source.pk == destination.pk:
            self.add_error("to_warehouse", "Choose a different destination warehouse.")
        return cleaned


# ---------------------------------------------------------------------------
# Market reference prices
# ---------------------------------------------------------------------------


class MarketReferenceForm(CatalogForm):
    class Meta:
        model = MarketReferencePrice
        fields = ("product", "state", "year", "season", "price_per_unit", "unit", "source", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.order_by("name")
        self.fields["state"].queryset = State.objects.filter(is_active=True).order_by("name")
        self.fields["state"].required = False
        self.fields["state"].empty_label = "— National —"
        self.fields["unit"].queryset = UnitOfMeasure.objects.filter(is_active=True)


# ---------------------------------------------------------------------------
# Public search / filters
# ---------------------------------------------------------------------------


SORT_CHOICES = (
    ("", "Most recent"),
    ("price_asc", "Price: low to high"),
    ("price_desc", "Price: high to low"),
    ("name", "Name A–Z"),
)


class SearchForm(TailwindFormMixin, forms.Form):
    """Public filter form (queried via ``request.GET``; never persisted)."""

    q = forms.CharField(required=False, label="Search")
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True).order_by("name"),
        required=False,
        empty_label="All categories",
    )
    state = forms.ModelChoiceField(
        queryset=State.objects.filter(is_active=True).order_by("name"),
        required=False,
        empty_label="All states",
    )
    min_price = forms.DecimalField(required=False, min_value=0, label="Min price")
    max_price = forms.DecimalField(required=False, min_value=0, label="Max price")
    in_stock = forms.BooleanField(required=False, label="In stock only")
    sort = forms.ChoiceField(choices=SORT_CHOICES, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


__all__ = [
    "CategoryForm",
    "ListingForm",
    "ListingPriceForm",
    "MarketReferenceForm",
    "ProductForm",
    "ProductImageForm",
    "ProductImageFormSet",
    "SearchForm",
    "StockAdjustForm",
    "StockReceiveForm",
    "StockTransferForm",
    "VariantForm",
    "WarehouseForm",
    "WholesaleTierForm",
]

"""Catalogue management views inside the staff dashboard.

Class-based views mirroring the CMS dashboard patterns: a capability-checking
mixin, generic list/form bases, and small action views. Every write goes through
``services`` so it is validated and audited; reads come from ``selectors``.
Authorisation is always enforced server-side — templates only hide navigation.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView, View

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability
from apps.orders import selectors as order_selectors

from . import inventory, selectors, services
from .forms import (
    CategoryForm,
    ListingForm,
    ListingPriceForm,
    MarketReferenceForm,
    ProductForm,
    ProductImageForm,
    StockAdjustForm,
    StockReceiveForm,
    StockTransferForm,
    VariantForm,
    WarehouseForm,
    WholesaleTierForm,
)
from .models import (
    Category,
    ListingStatus,
    MarketReferencePrice,
    Product,
    ProductImage,
    ProductListing,
    PublishStatus,
    Warehouse,
    WholesalePriceTier,
)


class CatalogAccessMixin:
    """Require authentication plus a catalogue capability for every view."""

    capability = Capability.CATALOG_MANAGE
    active_nav = "catalog"
    breadcrumbs: list[dict] = []

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not has_capability(request.user, self.capability):
            raise PermissionDenied("You do not have permission to manage the catalogue.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("active_nav", self.active_nav)
        context.setdefault(
            "breadcrumbs",
            [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Catalog", "url": "catalog_dashboard:home"},
                *self.breadcrumbs,
            ],
        )
        return context


class InventoryAccessMixin(CatalogAccessMixin):
    """Inventory actions (stock) additionally require the inventory capability."""

    capability = Capability.INVENTORY_MANAGE
    active_nav = "catalog_inventory"


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class CatalogHomeView(CatalogAccessMixin, TemplateView):
    template_name = "dashboard/catalog/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Catalogue",
                "counts": selectors.catalog_counts(),
                "low_stock": list(selectors.low_stock_listings())[:5],
                "recent_products": selectors.all_products()[:5],
                "recent_listings": selectors.all_listings()[:5],
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Catalog"},
                ],
            }
        )
        return context


# ---------------------------------------------------------------------------
# Generic bases
# ---------------------------------------------------------------------------


class CatalogFormMixin(CatalogAccessMixin):
    """Form page that writes through the service layer (audited)."""

    template_name = "dashboard/catalog/object_form.html"
    title = ""
    success_url_name = "catalog_dashboard:home"
    breadcrumbs: list[dict] = []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": self.title,
                "title": self.title,
                "cancel_url": reverse(self.success_url_name),
            }
        )
        return context

    def get_success_url(self):
        return reverse(self.success_url_name)

    def service_save(self, form):  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def form_valid(self, form):
        try:
            self.service_save(form)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, f"{self.title.rstrip('s')} saved.")
        return redirect(self.get_success_url())


class CatalogConfirmDeleteMixin(CatalogAccessMixin, View):
    """POST-only action view that soft-deletes or archives through services."""

    success_url_name = "catalog_dashboard:home"

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        try:
            self.perform_action(request, *args, **kwargs)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, self.success_message)
        return redirect(reverse(self.success_url_name))

    def perform_action(self, request, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


class CategoryListView(CatalogAccessMixin, TemplateView):
    template_name = "dashboard/catalog/category_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        roots = list(Category.objects.filter(parent__isnull=True).order_by("sort_order", "name"))
        children = {
            category.pk: list(category.children.order_by("sort_order", "name"))
            for category in roots
        }
        context.update(
            {
                "page_title": "Categories",
                "roots": roots,
                "children": children,
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Catalog", "url": "catalog_dashboard:home"},
                    {"label": "Categories"},
                ],
            }
        )
        return context


class _CategoryFormMixin(CatalogFormMixin):
    model = Category
    form_class = CategoryForm
    success_url_name = "catalog_dashboard:category_list"

    @staticmethod
    def _kwargs(form):
        data = form.cleaned_data
        return {
            "name": data["name"],
            "parent": data.get("parent"),
            "description": data.get("description", ""),
            "image": data.get("image"),
            "is_active": data.get("is_active", True),
            "is_featured": data.get("is_featured", False),
            "sort_order": data.get("sort_order", 0) or 0,
            "seo_title": data.get("seo_title", ""),
            "seo_description": data.get("seo_description", ""),
        }


class CategoryCreateView(_CategoryFormMixin, CreateView):
    title = "New category"

    def service_save(self, form):
        services.create_category(
            **self._kwargs(form), actor=self.request.user, request=self.request
        )


class CategoryUpdateView(_CategoryFormMixin, UpdateView):
    title = "Edit category"

    def service_save(self, form):
        services.update_category(
            self.object, **self._kwargs(form), actor=self.request.user, request=self.request
        )


class CategoryDeleteView(CatalogConfirmDeleteMixin):
    success_url_name = "catalog_dashboard:category_list"
    success_message = "Category archived."

    def perform_action(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        services.archive_category(category, actor=request.user, request=request)


class CategoryReorderView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        category = get_object_or_404(Category, pk=pk)
        try:
            step = int(request.POST.get("step", "0"))
        except (TypeError, ValueError):
            step = 0
        services.reorder_category(category, step=step or 1, actor=request.user, request=request)
        return redirect(reverse("catalog_dashboard:category_list"))


class CategoryToggleView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        category = get_object_or_404(Category, pk=pk)
        services.update_category(
            category,
            is_active=not category.is_active,
            actor=request.user,
            request=request,
        )
        messages.success(request, "Category visibility updated.")
        return redirect(reverse("catalog_dashboard:category_list"))


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


class ProductListView(CatalogAccessMixin, ListView):
    template_name = "dashboard/catalog/product_list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        queryset = selectors.all_products()
        status = self.request.GET.get("status", "")
        category = self.request.GET.get("category", "")
        if status:
            queryset = queryset.filter(status=status)
        if category:
            queryset = queryset.filter(category__slug=category)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Products",
                "selected_status": self.request.GET.get("status", ""),
                "selected_category": self.request.GET.get("category", ""),
                "statuses": [
                    ("draft", "Draft"),
                    ("published", "Published"),
                    ("archived", "Archived"),
                ],
                "categories": selectors.all_categories(),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Catalog", "url": "catalog_dashboard:home"},
                    {"label": "Products"},
                ],
            }
        )
        return context


class _ProductFormMixin(CatalogFormMixin):
    model = Product
    form_class = ProductForm
    success_url_name = "catalog_dashboard:product_list"

    @staticmethod
    def _kwargs(form):
        data = form.cleaned_data
        return {
            "name": data["name"],
            "category": data["category"],
            "short_description": data.get("short_description", ""),
            "description": data.get("description", ""),
            "unit": data.get("unit"),
            "variety": data.get("variety", ""),
            "grade": data.get("grade", ""),
            "harvest_season": data.get("harvest_season", ""),
            "tags": data.get("tags"),
            "seo_title": data.get("seo_title", ""),
            "seo_description": data.get("seo_description", ""),
        }


class ProductCreateView(_ProductFormMixin, CreateView):
    title = "New product"

    def service_save(self, form):
        services.create_product(**self._kwargs(form), actor=self.request.user, request=self.request)


class ProductUpdateView(_ProductFormMixin, UpdateView):
    title = "Edit product"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["product"] = self.object
        return context

    def service_save(self, form):
        services.update_product(
            self.object, **self._kwargs(form), actor=self.request.user, request=self.request
        )


class ProductDeleteView(CatalogConfirmDeleteMixin):
    success_url_name = "catalog_dashboard:product_list"
    success_message = "Product deleted."

    def perform_action(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        services.delete_product(product, actor=request.user, request=request)


class ProductPublishView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        product = get_object_or_404(Product, pk=pk)
        status = request.POST.get("status", "")
        if status not in dict(PublishStatus.choices):
            status = PublishStatus.PUBLISHED
        try:
            services.set_product_status(product, status=status, actor=request.user, request=request)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, f"Product status set to “{status}”.")
        return redirect(reverse("catalog_dashboard:product_list"))


class ProductImageManageView(CatalogAccessMixin, TemplateView):
    template_name = "dashboard/catalog/product_images.html"

    def get_product(self):
        return get_object_or_404(Product, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.get_product()
        context.update(
            {
                "page_title": f"Images — {product.name}",
                "product": product,
                "images": selectors.product_images(product),
                "form": kwargs.get("form") or ProductImageForm(),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Catalog", "url": "catalog_dashboard:home"},
                    {"label": "Products", "url": "catalog_dashboard:product_list"},
                    {
                        "label": product.name,
                        "href": reverse("catalog_dashboard:product_edit", args=[product.pk]),
                    },
                    {"label": "Images"},
                ],
            }
        )
        return context

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        product = self.get_product()
        form = ProductImageForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            services.add_product_image(
                product,
                image=data["image"],
                alt_text=data.get("alt_text", ""),
                sort_order=data.get("sort_order", 0) or 0,
                listing=data.get("listing"),
                actor=request.user,
                request=request,
            )
            messages.success(request, "Image uploaded.")
            return redirect(reverse("catalog_dashboard:product_images", args=[product.pk]))
        return self.render_to_response(self.get_context_data(form=form))


class ProductImageDeleteView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, image_pk, *args, **kwargs) -> HttpResponse:
        photo = get_object_or_404(ProductImage, pk=image_pk, product_id=pk)
        services.remove_product_image(photo, actor=request.user, request=request)
        messages.success(request, "Image removed.")
        return redirect(reverse("catalog_dashboard:product_images", args=[pk]))


class ProductImagePrimaryView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, image_pk, *args, **kwargs) -> HttpResponse:
        product = get_object_or_404(Product, pk=pk)
        photo = get_object_or_404(ProductImage, pk=image_pk, product=product)
        try:
            services.set_primary_image(product, photo, actor=request.user, request=request)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Primary image updated.")
        return redirect(reverse("catalog_dashboard:product_images", args=[pk]))


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


class ListingListView(CatalogAccessMixin, ListView):
    template_name = "dashboard/catalog/listing_list.html"
    context_object_name = "listings"
    paginate_by = 25

    def get_queryset(self):
        queryset = selectors.all_listings()
        status = self.request.GET.get("status", "")
        state = self.request.GET.get("state", "")
        if status:
            queryset = queryset.filter(status=status)
        if state:
            queryset = queryset.filter(state__slug=state)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Listings",
                "selected_status": self.request.GET.get("status", ""),
                "selected_state": self.request.GET.get("state", ""),
                "statuses": ListingStatus.choices,
                "states": selectors.state_list(),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Catalog", "url": "catalog_dashboard:home"},
                    {"label": "Listings"},
                ],
            }
        )
        return context


class _ListingFormMixin(CatalogFormMixin):
    model = ProductListing
    form_class = ListingForm
    success_url_name = "catalog_dashboard:listing_list"

    @staticmethod
    def _kwargs(form):
        data = form.cleaned_data
        return {
            "product": data["product"],
            "state": data["state"],
            "lga": data["lga"],
            "package_size": data["package_size"],
            "package_unit": data["package_unit"],
            "compare_at_price": data.get("compare_at_price"),
            "low_stock_threshold": data.get("low_stock_threshold"),
            "origin_verification": data.get("origin_verification", "unverified"),
            "origin_note": data.get("origin_note", ""),
        }


class ListingCreateView(_ListingFormMixin, CreateView):
    title = "New listing"

    def service_save(self, form):
        self.created_listing = services.create_listing(
            **self._kwargs(form), actor=self.request.user, request=self.request
        )

    def get_success_url(self):
        listing = getattr(self, "created_listing", None)
        if listing is not None:
            return reverse("catalog_dashboard:listing_detail", args=[listing.pk])
        return super().get_success_url()


class ListingUpdateView(_ListingFormMixin, UpdateView):
    title = "Edit listing"

    def service_save(self, form):
        services.update_listing(
            self.object, **self._kwargs(form), actor=self.request.user, request=self.request
        )


class ListingDetailView(CatalogAccessMixin, TemplateView):
    template_name = "dashboard/catalog/listing_detail.html"

    def get_listing(self):
        return get_object_or_404(ProductListing, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        listing = self.get_listing()
        context.update(
            {
                "page_title": f"Listing — {listing}",
                "listing": listing,
                "prices": selectors.listing_prices(listing),
                "history": selectors.price_history(listing),
                "movements": selectors.listing_movements(listing)[:20],
                "variants": listing.variants.order_by("sort_order", "name"),
                "tiers": selectors.wholesale_tiers(listing),
                "statuses": ListingStatus.choices,
                "price_form": kwargs.get("price_form") or ListingPriceForm(listing=listing),
                "stock_form": kwargs.get("stock_form") or StockAdjustForm(),
                "variant_form": kwargs.get("variant_form") or VariantForm(),
                "tier_form": kwargs.get("tier_form") or WholesaleTierForm(listing=listing),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Catalog", "url": "catalog_dashboard:home"},
                    {"label": "Listings", "url": "catalog_dashboard:listing_list"},
                    {"label": str(listing)},
                ],
            }
        )
        return context


class ListingArchiveView(CatalogConfirmDeleteMixin):
    success_url_name = "catalog_dashboard:listing_list"
    success_message = "Listing archived."

    def perform_action(self, request, pk):
        listing = get_object_or_404(ProductListing, pk=pk)
        services.archive_listing(listing, actor=request.user, request=request)


class ListingStatusView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        listing = get_object_or_404(ProductListing, pk=pk)
        status = request.POST.get("status", "")
        if status not in ListingStatus.values:
            status = ListingStatus.ACTIVE
        try:
            services.set_listing_status(listing, status=status, actor=request.user, request=request)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, f"Listing status set to “{status}”.")
        return redirect(reverse("catalog_dashboard:listing_detail", args=[listing.pk]))


class ListingPriceView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        listing = get_object_or_404(ProductListing, pk=pk)
        form = ListingPriceForm(request.POST, listing=listing)
        if form.is_valid():
            data = form.cleaned_data
            try:
                services.set_listing_price(
                    listing,
                    amount=data["amount"],
                    compare_at=data.get("compare_at"),
                    price_type=data.get("price_type", "selling"),
                    variant=data.get("variant"),
                    valid_from=data.get("valid_from"),
                    valid_to=data.get("valid_to"),
                    actor=request.user,
                    request=request,
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Price updated.")
        else:
            messages.error(request, "Could not save the price — please check the values.")
        return redirect(reverse("catalog_dashboard:listing_detail", args=[listing.pk]))


class ListingStockView(InventoryAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        listing = get_object_or_404(ProductListing, pk=pk)
        form = StockAdjustForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                services.adjust_stock(
                    listing,
                    delta=data["delta"],
                    kind=data.get("kind", "adjustment"),
                    reference=data.get("reference", ""),
                    note=data.get("note", ""),
                    actor=request.user,
                    request=request,
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Stock adjusted.")
        else:
            messages.error(request, "Could not adjust stock — please check the values.")
        return redirect(reverse("catalog_dashboard:listing_detail", args=[listing.pk]))


class VariantCreateView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        listing = get_object_or_404(ProductListing, pk=pk)
        form = VariantForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                services.create_variant(
                    listing,
                    name=data["name"],
                    notes=data.get("notes", ""),
                    sort_order=data.get("sort_order", 0) or 0,
                    actor=request.user,
                    request=request,
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Variant added.")
        else:
            messages.error(request, "Could not add the variant — please check the values.")
        return redirect(reverse("catalog_dashboard:listing_detail", args=[listing.pk]))


class TierCreateView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        listing = get_object_or_404(ProductListing, pk=pk)
        form = WholesaleTierForm(request.POST, listing=listing)
        if form.is_valid():
            data = form.cleaned_data
            try:
                services.set_wholesale_tier(
                    listing,
                    min_quantity=data["min_quantity"],
                    price=data["price"],
                    variant=data.get("variant"),
                    actor=request.user,
                    request=request,
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Wholesale tier saved.")
        else:
            messages.error(request, "Could not save the tier — please check the values.")
        return redirect(reverse("catalog_dashboard:listing_detail", args=[listing.pk]))


class TierDeleteView(CatalogAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        tier = get_object_or_404(WholesalePriceTier, pk=pk)
        listing_id = tier.listing_id
        services.remove_wholesale_tier(tier, actor=request.user, request=request)
        messages.success(request, "Tier removed.")
        return redirect(reverse("catalog_dashboard:listing_detail", args=[listing_id]))


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


class LowStockListView(InventoryAccessMixin, ListView):
    template_name = "dashboard/catalog/low_stock.html"
    context_object_name = "listings"
    paginate_by = 25

    def get_queryset(self):
        return [listing for listing in selectors.low_stock_listings() if listing.low_stock]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Low stock",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Catalog", "url": "catalog_dashboard:home"},
                    {"label": "Low stock"},
                ],
            }
        )
        return context


# ---------------------------------------------------------------------------
# Market reference prices
# ---------------------------------------------------------------------------


class ReferenceListView(CatalogAccessMixin, ListView):
    template_name = "dashboard/catalog/reference_list.html"
    context_object_name = "references"
    paginate_by = 25

    def get_queryset(self):
        return MarketReferencePrice.objects.select_related("product", "state", "unit")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Market reference prices",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Catalog", "url": "catalog_dashboard:home"},
                    {"label": "Market references"},
                ],
            }
        )
        return context


class _ReferenceFormMixin(CatalogFormMixin):
    model = MarketReferencePrice
    form_class = MarketReferenceForm
    success_url_name = "catalog_dashboard:reference_list"

    @staticmethod
    def _kwargs(form):
        data = form.cleaned_data
        return {
            "product": data["product"],
            "state": data.get("state"),
            "year": data["year"],
            "season": data.get("season", ""),
            "price_per_unit": data["price_per_unit"],
            "unit": data["unit"],
            "source": data.get("source", ""),
            "note": data.get("note", ""),
        }


class ReferenceCreateView(_ReferenceFormMixin, CreateView):
    title = "New market reference"

    def service_save(self, form):
        services.record_market_reference(
            actor=self.request.user, request=self.request, **self._kwargs(form)
        )


class ReferenceUpdateView(_ReferenceFormMixin, UpdateView):
    title = "Edit market reference"

    def service_save(self, form):
        data = self._kwargs(form)
        product = data.pop("product")
        reference = self.object
        reference.product = product
        for field, value in data.items():
            setattr(reference, field, value)
        reference.full_clean()
        reference.save()
        messages.info(self.request, "Reference price saved.")


# ---------------------------------------------------------------------------
# Phase 5 inventory: warehouses, balances, movements, reservations
# ---------------------------------------------------------------------------


class InventoryHomeView(InventoryAccessMixin, TemplateView):
    template_name = "dashboard/inventory/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        low_stock = [listing for listing in selectors.low_stock_listings() if listing.low_stock]
        context.update(
            {
                "page_title": "Inventory",
                "counts": order_selectors.inventory_counts(),
                "warehouses": Warehouse.objects.order_by("name")[:8],
                "low_stock": low_stock[:8],
                "recent_movements": order_selectors.stock_movements(limit=10),
                "active_reservations": order_selectors.reserved_overview()[:10],
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Inventory"},
                ],
            }
        )
        return context


class WarehouseListView(InventoryAccessMixin, ListView):
    template_name = "dashboard/inventory/warehouse_list.html"
    context_object_name = "warehouses"
    paginate_by = 25

    def get_queryset(self):
        return Warehouse.objects.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Warehouses",
                "active_nav": "catalog_inventory",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Inventory", "url": "inventory_dashboard:home"},
                    {"label": "Warehouses"},
                ],
            }
        )
        return context


class _WarehouseFormMixin(InventoryAccessMixin):
    template_name = "dashboard/catalog/object_form.html"
    form_class = WarehouseForm
    success_url_name = "inventory_dashboard:warehouse_list"
    title = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": self.title,
                "title": self.title,
                "cancel_url": reverse(self.success_url_name),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Inventory", "url": "inventory_dashboard:home"},
                    {"label": "Warehouses", "url": "inventory_dashboard:warehouse_list"},
                    {"label": self.title},
                ],
            }
        )
        return context

    def get_success_url(self):
        return reverse(self.success_url_name)

    def form_valid(self, form):
        try:
            self.service_save(form)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, "Warehouse saved.")
        return redirect(self.get_success_url())

    def service_save(self, form):  # pragma: no cover
        raise NotImplementedError


def _warehouse_kwargs(form):
    data = form.cleaned_data
    return {
        "name": data["name"],
        "code": data["code"],
        "address": data.get("address", ""),
        "state": data.get("state"),
        "lga": data.get("lga"),
        "is_active": data.get("is_active", True),
    }


class WarehouseCreateView(_WarehouseFormMixin, CreateView):
    title = "New warehouse"

    def service_save(self, form):
        services.create_warehouse(
            **_warehouse_kwargs(form), actor=self.request.user, request=self.request
        )


class WarehouseUpdateView(_WarehouseFormMixin, UpdateView):
    title = "Edit warehouse"
    model = Warehouse

    def service_save(self, form):
        services.update_warehouse(
            self.object, **_warehouse_kwargs(form), actor=self.request.user, request=self.request
        )


class StockBalanceListView(InventoryAccessMixin, ListView):
    template_name = "dashboard/inventory/stock_list.html"
    context_object_name = "balances"
    paginate_by = 40

    def get_queryset(self):
        warehouse = self.request.GET.get("warehouse") or None
        query = self.request.GET.get("q", "")
        return order_selectors.stock_balances(warehouse=warehouse, query=query)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Stock levels",
                "active_nav": "catalog_inventory",
                "warehouses": Warehouse.objects.order_by("name"),
                "selected_warehouse": self.request.GET.get("warehouse", ""),
                "query": self.request.GET.get("q", ""),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Inventory", "url": "inventory_dashboard:home"},
                    {"label": "Stock levels"},
                ],
            }
        )
        return context


class StockMovementListView(InventoryAccessMixin, ListView):
    template_name = "dashboard/inventory/movement_list.html"
    context_object_name = "movements"
    paginate_by = 40

    def get_queryset(self):
        return order_selectors.stock_movements()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Stock movements",
                "active_nav": "catalog_inventory",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Inventory", "url": "inventory_dashboard:home"},
                    {"label": "Movements"},
                ],
            }
        )
        return context


class ReservationListView(InventoryAccessMixin, ListView):
    template_name = "dashboard/inventory/reservation_list.html"
    context_object_name = "reservations"
    paginate_by = 40

    def get_queryset(self):
        return order_selectors.reserved_overview()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Active reservations",
                "active_nav": "catalog_inventory",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Inventory", "url": "inventory_dashboard:home"},
                    {"label": "Reservations"},
                ],
            }
        )
        return context


class StockReceiveView(InventoryAccessMixin, FormView):
    template_name = "dashboard/inventory/stock_receive.html"
    form_class = StockReceiveForm

    def get_listing(self):
        return get_object_or_404(ProductListing, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Receive stock",
                "listing": self.get_listing(),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Inventory", "url": "inventory_dashboard:home"},
                    {"label": "Stock levels", "url": "inventory_dashboard:stock_list"},
                    {"label": "Receive"},
                ],
            }
        )
        return context

    def get_success_url(self):
        return reverse("catalog_dashboard:listing_detail", args=[self.kwargs["pk"]])

    def form_valid(self, form):
        try:
            inventory.receive_stock(
                self.get_listing(),
                quantity=form.cleaned_data["quantity"],
                warehouse=form.cleaned_data.get("warehouse"),
                reference=form.cleaned_data.get("reference", ""),
                note=form.cleaned_data.get("note", ""),
                actor=self.request.user,
                request=self.request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, "Stock received.")
        return redirect(self.get_success_url())


class StockTransferView(InventoryAccessMixin, FormView):
    template_name = "dashboard/inventory/stock_transfer.html"
    form_class = StockTransferForm

    def get_listing(self):
        return get_object_or_404(ProductListing, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Transfer stock",
                "listing": self.get_listing(),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Inventory", "url": "inventory_dashboard:home"},
                    {"label": "Stock levels", "url": "inventory_dashboard:stock_list"},
                    {"label": "Transfer"},
                ],
            }
        )
        return context

    def get_success_url(self):
        return reverse("catalog_dashboard:listing_detail", args=[self.kwargs["pk"]])

    def form_valid(self, form):
        try:
            inventory.transfer_stock(
                self.get_listing(),
                quantity=form.cleaned_data["quantity"],
                from_warehouse=form.cleaned_data["from_warehouse"],
                to_warehouse=form.cleaned_data["to_warehouse"],
                reference=form.cleaned_data.get("reference", ""),
                note=form.cleaned_data.get("note", ""),
                actor=self.request.user,
                request=self.request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, "Stock transferred.")
        return redirect(self.get_success_url())

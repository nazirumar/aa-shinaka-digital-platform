"""Staff dashboard views for orders, quotations and shipping configuration.

Every view enforces a capability server-side (``ORDERS_MANAGE`` for orders and
quotations, ``FINANCE_MANAGE`` for payment confirmation). Writes go through the
service layer so they are validated and audited.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, ListView, TemplateView, UpdateView, View

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability

from . import selectors, services
from .forms import (
    ConfirmPaymentForm,
    OrderStatusForm,
    QuotationReviewForm,
    ShipmentForm,
    ShipmentStatusForm,
    ShippingMethodForm,
    ShippingRateForm,
    ShippingZoneForm,
)
from .models import (
    Order,
    QuotationRequest,
    Shipment,
    ShipmentStatus,
    ShippingMethod,
    ShippingRate,
    ShippingZone,
)


class OrdersAccessMixin:
    capability = Capability.ORDERS_MANAGE
    active_nav = "orders"
    breadcrumbs: list[dict] = []

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not has_capability(request.user, self.capability):
            raise PermissionDenied("You do not have permission to manage orders.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("active_nav", self.active_nav)
        context.setdefault(
            "breadcrumbs",
            [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Orders", "url": "orders_dashboard:home"},
                *self.breadcrumbs,
            ],
        )
        return context


# ---------------------------------------------------------------------------
# Overview & lists
# ---------------------------------------------------------------------------


class OrderDashboardHome(OrdersAccessMixin, TemplateView):
    template_name = "dashboard/orders/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Orders",
                "counts": selectors.order_counts(),
                "recent_orders": selectors.staff_orders()[:8],
                "pending_payments": selectors.staff_orders(status="pending_payment")[:8],
                "recent_quotations": selectors.staff_quotations()[:6],
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Orders"},
                ],
            }
        )
        return context


class OrderListView(OrdersAccessMixin, ListView):
    template_name = "dashboard/orders/order_list.html"
    context_object_name = "orders"
    paginate_by = 25

    def get_queryset(self):
        return selectors.staff_orders(
            status=self.request.GET.get("status", ""),
            payment_status=self.request.GET.get("payment_status", ""),
            query=self.request.GET.get("q", ""),
            date_from=self.request.GET.get("date_from") or None,
            date_to=self.request.GET.get("date_to") or None,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import OrderStatus, PaymentStatus

        context.update(
            {
                "page_title": "All orders",
                "order_statuses": OrderStatus.choices,
                "payment_statuses": PaymentStatus.choices,
                "status": self.request.GET.get("status", ""),
                "payment_status": self.request.GET.get("payment_status", ""),
                "query": self.request.GET.get("q", ""),
                "date_from": self.request.GET.get("date_from", ""),
                "date_to": self.request.GET.get("date_to", ""),
            }
        )
        return context


class OrderDetailView(OrdersAccessMixin, TemplateView):
    template_name = "dashboard/orders/order_detail.html"

    def get_order(self):
        return get_object_or_404(
            Order.objects.select_related("user", "delivery_state", "shipping_method"),
            number=self.kwargs["number"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.get_order()
        context.update(
            {
                "order": order,
                "items": order.items.select_related("listing__product", "variant"),
                "reservations": order.reservations.select_related("warehouse", "listing"),
                "timeline": selectors.order_timeline(order),
                "shipments": order.shipments.select_related("method"),
                "status_form": OrderStatusForm(order=order),
                "payment_form": ConfirmPaymentForm(),
                "shipment_form": ShipmentForm(initial={"method": order.shipping_method}),
                "shipment_statuses": ShipmentStatus.choices,
                "page_title": f"Order {order.number}",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Orders", "url": "orders_dashboard:home"},
                    {"label": "All orders", "url": "orders_dashboard:order_list"},
                    {"label": order.number},
                ],
            }
        )
        return context


# ---------------------------------------------------------------------------
# Order actions
# ---------------------------------------------------------------------------


class _OrderActionView(OrdersAccessMixin, View):
    def get_order(self) -> Order:
        return get_object_or_404(Order, number=self.kwargs["number"])

    def success_url(self, order: Order) -> str:
        return reverse("orders_dashboard:order_detail", args=[order.number])


class OrderStatusUpdateView(_OrderActionView):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        order = self.get_order()
        form = OrderStatusForm(request.POST, order=order)
        if form.is_valid() and form.cleaned_data["status"]:
            try:
                services.transition_order(
                    order,
                    to_status=form.cleaned_data["status"],
                    actor=request.user,
                    reason=form.cleaned_data.get("reason", ""),
                    request=request,
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Order status updated.")
        else:
            messages.error(request, "Choose a valid next status.")
        return redirect(self.success_url(order))


class OrderCancelView(_OrderActionView):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        order = self.get_order()
        try:
            services.cancel_order(
                order,
                actor=request.user,
                reason=request.POST.get("reason", "Cancelled by staff."),
                request=request,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Order cancelled.")
        return redirect(self.success_url(order))


class OrderConfirmPaymentView(_OrderActionView):
    capability = Capability.FINANCE_MANAGE

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        order = self.get_order()
        form = ConfirmPaymentForm(request.POST)
        if form.is_valid():
            try:
                services.confirm_payment(
                    order,
                    actor=request.user,
                    reference=form.cleaned_data.get("reference", ""),
                    note=form.cleaned_data.get("note", ""),
                    request=request,
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "Payment approved and stock committed.")
        return redirect(self.success_url(order))


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------


class ShipmentCreateView(OrdersAccessMixin, View):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        order = get_object_or_404(Order, number=self.kwargs["number"])
        form = ShipmentForm(request.POST)
        if form.is_valid():
            shipment = services.create_shipment(
                order,
                method=form.cleaned_data.get("method"),
                carrier=form.cleaned_data.get("carrier", ""),
                tracking_number=form.cleaned_data.get("tracking_number", ""),
                notes=form.cleaned_data.get("notes", ""),
                actor=request.user,
                request=request,
            )
            status = form.cleaned_data.get("status")
            if status and status != shipment.status:
                services.update_shipment_status(
                    shipment, status=status, actor=request.user, request=request
                )
            messages.success(request, "Shipment recorded.")
        else:
            messages.error(request, "Could not save the shipment — check the fields.")
        return redirect(reverse("orders_dashboard:order_detail", args=[order.number]))


class ShipmentStatusView(OrdersAccessMixin, View):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        shipment = get_object_or_404(Shipment, pk=self.kwargs["pk"])
        form = ShipmentStatusForm(request.POST)
        if form.is_valid():
            try:
                services.update_shipment_status(
                    shipment,
                    status=form.cleaned_data["status"],
                    tracking_number=form.cleaned_data.get("tracking_number") or None,
                    notes=form.cleaned_data.get("notes"),
                    actor=request.user,
                    request=request,
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Shipment updated.")
        return redirect(reverse("orders_dashboard:order_detail", args=[shipment.order.number]))


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------


class QuotationListView(OrdersAccessMixin, ListView):
    template_name = "dashboard/orders/quotation_list.html"
    context_object_name = "quotations"
    paginate_by = 25

    def get_queryset(self):
        return selectors.staff_quotations(
            status=self.request.GET.get("status", ""), query=self.request.GET.get("q", "")
        )

    def get_context_data(self, **kwargs):
        from .models import QuotationStatus

        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Quotation requests",
                "quotation_statuses": QuotationStatus.choices,
                "status": self.request.GET.get("status", ""),
                "query": self.request.GET.get("q", ""),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Orders", "url": "orders_dashboard:home"},
                    {"label": "Quotations"},
                ],
            }
        )
        return context


class QuotationDetailView(OrdersAccessMixin, TemplateView):
    template_name = "dashboard/orders/quotation_detail.html"

    def get_quotation(self) -> QuotationRequest:
        return get_object_or_404(
            QuotationRequest.objects.select_related(
                "listing__product", "variant", "destination_state", "destination_lga", "user"
            ),
            pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        quotation = self.get_quotation()
        context.update(
            {
                "quotation": quotation,
                "form": QuotationReviewForm(
                    initial={"status": quotation.status, "response_note": quotation.response_note}
                ),
                "page_title": "Review quotation",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Orders", "url": "orders_dashboard:home"},
                    {"label": "Quotations", "url": "orders_dashboard:quotation_list"},
                    {"label": "Review"},
                ],
            }
        )
        return context


class QuotationReviewView(OrdersAccessMixin, View):
    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        quotation = get_object_or_404(QuotationRequest, pk=pk)
        form = QuotationReviewForm(request.POST)
        if form.is_valid():
            try:
                services.update_quotation(
                    quotation,
                    status=form.cleaned_data["status"],
                    response_note=form.cleaned_data.get("response_note", ""),
                    actor=request.user,
                    request=request,
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "Quotation request updated.")
        return redirect(reverse("orders_dashboard:quotation_list"))


# ---------------------------------------------------------------------------
# Shipping configuration
# ---------------------------------------------------------------------------


class _ShippingFormMixin(OrdersAccessMixin):
    template_name = "dashboard/catalog/object_form.html"
    title = ""
    success_url_name = "orders_dashboard:shipping_zone_list"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": self.title,
                "title": self.title,
                "cancel_url": reverse(self.success_url_name),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Orders", "url": "orders_dashboard:home"},
                    {"label": "Shipping"},
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
        messages.success(self.request, "Saved.")
        return redirect(self.get_success_url())

    def service_save(self, form):  # pragma: no cover
        raise NotImplementedError


class ShippingZoneListView(OrdersAccessMixin, ListView):
    template_name = "dashboard/orders/shipping_zone_list.html"
    context_object_name = "zones"
    paginate_by = 25

    def get_queryset(self):
        return selectors.shipping_zones()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Shipping zones",
                "active_nav": "orders_shipping",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Orders", "url": "orders_dashboard:home"},
                    {"label": "Shipping zones"},
                ],
            }
        )
        return context


class ShippingZoneCreateView(_ShippingFormMixin, CreateView):
    form_class = ShippingZoneForm
    title = "New shipping zone"
    success_url_name = "orders_dashboard:shipping_zone_list"

    def service_save(self, form):
        data = form.cleaned_data
        services.create_shipping_zone(
            name=data["name"],
            code=data["code"],
            description=data.get("description", ""),
            states=data.get("states"),
            is_active=data.get("is_active", True),
            actor=self.request.user,
            request=self.request,
        )


class ShippingZoneUpdateView(_ShippingFormMixin, UpdateView):
    model = ShippingZone
    form_class = ShippingZoneForm
    title = "Edit shipping zone"
    success_url_name = "orders_dashboard:shipping_zone_list"

    def service_save(self, form):
        data = form.cleaned_data
        services.update_shipping_zone(
            self.object,
            name=data["name"],
            code=data["code"],
            description=data.get("description", ""),
            states=data.get("states"),
            is_active=data.get("is_active", True),
            actor=self.request.user,
            request=self.request,
        )


class ShippingMethodListView(OrdersAccessMixin, ListView):
    template_name = "dashboard/orders/shipping_method_list.html"
    context_object_name = "methods"
    paginate_by = 25

    def get_queryset(self):
        return selectors.shipping_methods_list()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Shipping methods",
                "active_nav": "orders_shipping",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Orders", "url": "orders_dashboard:home"},
                    {"label": "Shipping methods"},
                ],
            }
        )
        return context


class ShippingMethodCreateView(_ShippingFormMixin, CreateView):
    form_class = ShippingMethodForm
    title = "New shipping method"
    success_url_name = "orders_dashboard:shipping_method_list"

    def service_save(self, form):
        data = form.cleaned_data
        services.create_shipping_method(
            name=data["name"],
            code=data["code"],
            description=data.get("description", ""),
            sort_order=data.get("sort_order", 0) or 0,
            is_active=data.get("is_active", True),
            actor=self.request.user,
            request=self.request,
        )


class ShippingMethodUpdateView(_ShippingFormMixin, UpdateView):
    model = ShippingMethod
    form_class = ShippingMethodForm
    title = "Edit shipping method"
    success_url_name = "orders_dashboard:shipping_method_list"

    def service_save(self, form):
        data = form.cleaned_data
        services.update_shipping_method(
            self.object,
            name=data["name"],
            code=data["code"],
            description=data.get("description", ""),
            sort_order=data.get("sort_order", 0) or 0,
            is_active=data.get("is_active", True),
            actor=self.request.user,
            request=self.request,
        )


class ShippingRateListView(OrdersAccessMixin, ListView):
    template_name = "dashboard/orders/shipping_rate_list.html"
    context_object_name = "rates"
    paginate_by = 25

    def get_queryset(self):
        return selectors.shipping_rates()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Shipping rates",
                "active_nav": "orders_shipping",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Orders", "url": "orders_dashboard:home"},
                    {"label": "Shipping rates"},
                ],
            }
        )
        return context


class ShippingRateCreateView(_ShippingFormMixin, CreateView):
    form_class = ShippingRateForm
    title = "New shipping rate"
    success_url_name = "orders_dashboard:shipping_rate_list"

    def service_save(self, form):
        data = form.cleaned_data
        services.create_shipping_rate(
            zone=data["zone"],
            method=data["method"],
            fee=data["fee"],
            free_over=data.get("free_over"),
            min_order_amount=data.get("min_order_amount") or "0.00",
            is_active=data.get("is_active", True),
            actor=self.request.user,
            request=self.request,
        )


class ShippingRateUpdateView(_ShippingFormMixin, UpdateView):
    model = ShippingRate
    form_class = ShippingRateForm
    title = "Edit shipping rate"
    success_url_name = "orders_dashboard:shipping_rate_list"

    def service_save(self, form):
        data = form.cleaned_data
        services.update_shipping_rate(
            self.object,
            fee=data["fee"],
            free_over=data.get("free_over"),
            min_order_amount=data.get("min_order_amount") or "0.00",
            is_active=data.get("is_active", True),
            actor=self.request.user,
            request=self.request,
        )

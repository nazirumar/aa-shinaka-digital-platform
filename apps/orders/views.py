"""Public/customer views for cart, checkout, orders and quotations.

Thin views: writes go through ``services``, reads through ``selectors``. Prices
and stock are always resolved server-side. Guest carts are allowed; checkout and
the order portal require authentication (ASSUMPTION-07 — no guest checkout).
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import Address
from apps.catalog.models import ProductListing, ProductVariant
from apps.locations.models import State

from . import selectors, services
from .forms import CheckoutForm, QuotationRequestForm
from .models import OrderStatus

PAGE_SIZE = 20


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _quantity_from_post(request: HttpRequest) -> Decimal:
    raw = request.POST.get("quantity", "1")
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid quantity.") from exc


def _address_for(user, address_id):
    if not address_id:
        return None
    return Address.objects.filter(user=user, pk=address_id).first()


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


def _cart_context(request: HttpRequest) -> dict:
    cart = services.get_active_cart(request)
    summary = selectors.cart_totals(cart)
    return {"cart": cart, "summary": summary, "page_title": "Your cart"}


def cart_detail(request: HttpRequest) -> HttpResponse:
    return render(request, "orders/cart.html", _cart_context(request))


@require_POST
def cart_add(request: HttpRequest, pk) -> HttpResponse:
    listing = get_object_or_404(
        ProductListing.objects.select_related("product", "state", "lga", "package_unit"),
        pk=pk,
    )
    variant = None
    variant_id = request.POST.get("variant") or ""
    if variant_id:
        variant = get_object_or_404(ProductVariant, pk=variant_id, listing=listing)
    try:
        cart = services.get_active_cart(request, create=True)
        services.add_to_cart(
            cart,
            listing=listing,
            variant=variant,
            quantity=_quantity_from_post(request),
            request=request,
        )
    except ValidationError as exc:
        if _is_htmx(request):
            return render(
                request,
                "orders/partials/cart_feedback.html",
                {"error": "; ".join(exc.messages)},
                status=400,
            )
        messages.error(request, "; ".join(exc.messages))
        return redirect(listing.get_absolute_url())
    if _is_htmx(request):
        return render(request, "orders/partials/cart_feedback.html", _cart_context(request))
    messages.success(request, "Added to your cart.")
    return redirect(reverse("orders:cart"))


@require_POST
def cart_item_update(request: HttpRequest, pk) -> HttpResponse:
    cart = services.get_active_cart(request)
    if cart is None:
        messages.info(request, "Your cart is empty.")
        return redirect(reverse("orders:cart"))
    item = get_object_or_404(cart.items.select_related("listing", "variant"), pk=pk)
    try:
        services.update_cart_item(
            cart, item, quantity=_quantity_from_post(request), request=request
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    if _is_htmx(request):
        return render(request, "orders/partials/cart_body.html", _cart_context(request))
    return redirect(reverse("orders:cart"))


@require_POST
def cart_item_remove(request: HttpRequest, pk) -> HttpResponse:
    cart = services.get_active_cart(request)
    if cart is None:
        messages.info(request, "Your cart is empty.")
        return redirect(reverse("orders:cart"))
    item = get_object_or_404(cart.items.select_related("listing"), pk=pk)
    services.remove_cart_item(cart, item)
    messages.success(request, "Item removed.")
    if _is_htmx(request):
        return render(request, "orders/partials/cart_body.html", _cart_context(request))
    return redirect(reverse("orders:cart"))


@require_POST
def cart_clear(request: HttpRequest) -> HttpResponse:
    cart = services.get_active_cart(request)
    if cart is not None:
        services.clear_cart(cart)
    messages.success(request, "Cart cleared.")
    if _is_htmx(request):
        return render(request, "orders/partials/cart_body.html", _cart_context(request))
    return redirect(reverse("orders:cart"))


@require_GET
def cart_summary(request: HttpRequest) -> HttpResponse:
    return render(request, "orders/partials/cart_summary.html", _cart_context(request))


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


def _shipping_options(request: HttpRequest, state_id=None) -> list[dict]:
    state = State.objects.filter(pk=state_id).first() if state_id else None
    cart = services.get_active_cart(request)
    subtotal = selectors.cart_totals(cart)["subtotal"]
    return [
        {**option, "fee_for_order": option["rate"].fee_for(subtotal)}
        for option in selectors.shipping_options_for_state(state)
    ]


@login_required
@require_GET
def checkout_shipping_options(request: HttpRequest) -> HttpResponse:
    address = _address_for(request.user, request.GET.get("address"))
    state_id = address.state_id if address is not None else request.GET.get("state")
    options = _shipping_options(request, state_id)
    return render(
        request,
        "orders/partials/shipping_options.html",
        {"shipping_options": options},
    )


@login_required
def checkout(request: HttpRequest) -> HttpResponse:
    cart = services.get_active_cart(request)
    if cart is None or not cart.items.exists():
        messages.info(request, "Your cart is empty.")
        return redirect(reverse("orders:cart"))

    summary = selectors.cart_totals(cart)
    address_obj = None

    if request.method == "POST":
        form = CheckoutForm(request.POST, user=request.user)
        if form.is_valid():
            token = request.POST.get("checkout_token") or uuid.uuid4().hex
            try:
                order = services.place_order(
                    user=request.user,
                    cart=cart,
                    address=form.cleaned_data["address"],
                    shipping_method=form.cleaned_data["shipping_method"],
                    customer_note=form.cleaned_data.get("customer_note", ""),
                    checkout_token=token,
                    request=request,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                request.session.pop("checkout_token", None)
                messages.success(
                    request,
                    f"Order {order.number} placed — we'll confirm once payment is verified.",
                )
                return redirect(reverse("orders:order_detail", args=[order.number]))
        address_obj = _address_for(request.user, request.POST.get("address"))
    else:
        form = CheckoutForm(user=request.user)
        address_obj = _address_for(request.user, request.GET.get("address"))

    if address_obj is None:
        address_obj = form.fields["address"].queryset.first()

    checkout_token = request.session.get("checkout_token")
    if not checkout_token:
        checkout_token = uuid.uuid4().hex
        request.session["checkout_token"] = checkout_token

    return render(
        request,
        "orders/checkout.html",
        {
            "form": form,
            "summary": summary,
            "page_title": "Checkout",
            "selected_address": address_obj,
            "has_addresses": form.fields["address"].queryset.exists(),
            "shipping_options": _shipping_options(
                request, address_obj.state_id if address_obj else None
            ),
            "checkout_token": checkout_token,
        },
    )


# ---------------------------------------------------------------------------
# Customer order portal
# ---------------------------------------------------------------------------


@login_required
def order_list(request: HttpRequest) -> HttpResponse:
    orders = selectors.orders_for_user(request.user)
    status = request.GET.get("status", "")
    if status:
        orders = orders.filter(status=status)
    page = Paginator(orders, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/order_list.html",
        {
            "orders": page,
            "page_obj": page,
            "page_title": "Your orders",
            "status": status,
            "order_statuses": OrderStatus.choices,
        },
    )


@login_required
def order_detail(request: HttpRequest, number: str) -> HttpResponse:
    order = selectors.order_for_user(request.user, number)
    if order is None:
        messages.error(request, "Order not found.")
        return redirect(reverse("orders:order_list"))
    from . import paystack

    return render(
        request,
        "orders/order_detail.html",
        {
            "order": order,
            "items": order.items.select_related("listing__product"),
            "timeline": selectors.order_timeline(order),
            "page_title": f"Order {order.number}",
            "can_cancel": order.status in services.CANCELLABLE_STATUSES,
            "can_submit_payment": order.status
            in {
                OrderStatus.PENDING_PAYMENT,
                OrderStatus.PAYMENT_REVIEW,
            },
            "online_payment_available": paystack.is_enabled(),
            "invoice": getattr(order, "invoice", None),
            "shipments": order.shipments.select_related("method").all(),
        },
    )


@login_required
@require_POST
def order_cancel(request: HttpRequest, number: str) -> HttpResponse:
    order = selectors.order_for_user(request.user, number)
    if order is None:
        messages.error(request, "Order not found.")
        return redirect(reverse("orders:order_list"))
    try:
        services.cancel_order(
            order,
            actor=request.user,
            reason=request.POST.get("reason", "Cancelled by customer."),
            request=request,
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Order cancelled.")
    return redirect(reverse("orders:order_detail", args=[number]))


@login_required
@require_POST
def order_payment_review(request: HttpRequest, number: str) -> HttpResponse:
    order = selectors.order_for_user(request.user, number)
    if order is None:
        messages.error(request, "Order not found.")
        return redirect(reverse("orders:order_list"))
    try:
        services.submit_payment_review(
            order,
            actor=request.user,
            note=request.POST.get("note", ""),
            request=request,
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "We'll review your payment and confirm shortly.")
    return redirect(reverse("orders:order_detail", args=[number]))


# ---------------------------------------------------------------------------
# Quotation requests
# ---------------------------------------------------------------------------


def quotation_create(request: HttpRequest, listing_pk) -> HttpResponse:
    listing = get_object_or_404(
        ProductListing.objects.select_related("product", "state"), pk=listing_pk
    )
    if request.method == "POST":
        form = QuotationRequestForm(request.POST, state_id=request.POST.get("destination_state"))
        if form.is_valid():
            services.create_quotation_request(
                user=request.user if request.user.is_authenticated else None,
                listing=listing,
                quantity=form.cleaned_data["quantity"],
                packaging=form.cleaned_data.get("packaging", ""),
                destination_state=form.cleaned_data.get("destination_state"),
                destination_lga=form.cleaned_data.get("destination_lga"),
                destination_note=form.cleaned_data.get("destination_note", ""),
                requirements=form.cleaned_data.get("requirements", ""),
                contact_name=form.cleaned_data["contact_name"],
                contact_email=form.cleaned_data["contact_email"],
                contact_phone=form.cleaned_data.get("contact_phone", ""),
                request=request,
            )
            messages.success(request, "Quotation request submitted. Our team will respond shortly.")
            return redirect(listing.get_absolute_url())
    else:
        form = QuotationRequestForm(
            initial={
                "quantity": 1,
                "contact_name": getattr(request.user, "full_name", ""),
                "contact_email": getattr(request.user, "email", ""),
                "contact_phone": getattr(request.user, "phone", ""),
            }
        )
    return render(
        request,
        "orders/quotation_form.html",
        {"form": form, "listing": listing, "page_title": "Request a bulk quotation"},
    )


@login_required
def quotation_list(request: HttpRequest) -> HttpResponse:
    quotations = selectors.quotations_for_user(request.user)
    return render(
        request,
        "orders/quotation_list.html",
        {"quotations": quotations, "page_title": "Quotation requests"},
    )

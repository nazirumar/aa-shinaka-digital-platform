"""Customer-facing payment views (Phase 6).

Thin views: all writes go through :mod:`apps.orders.payments`; reads go through
:mod:`apps.orders.selectors`. Nothing here trusts the browser redirect — a
payment only becomes ``paid`` after a server-side Paystack verification whose
amount and currency match the stored order total.

Access rule: a customer may only see their own payments, invoices and receipts.
Staff with the finance/orders capability may view any of them.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability

from . import payments as payment_services
from . import selectors
from .models import Order
from .payment_forms import BankTransferForm
from .payment_models import PaymentState

# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------


def _is_finance_staff(user) -> bool:
    return has_capability(user, Capability.FINANCE_MANAGE) or has_capability(
        user, Capability.ORDERS_MANAGE
    )


def _lookup_order(request, number) -> Order | None:
    """Return the order when the caller owns it or is finance/orders staff."""
    order = Order.objects.filter(number=number).select_related("user").first()
    if order is None:
        return None
    if order.user_id == getattr(request.user, "id", None):
        return order
    return order if _is_finance_staff(request.user) else None


# ---------------------------------------------------------------------------
# Paystack checkout
# ---------------------------------------------------------------------------


@login_required
def payment_start(request, number):
    """Start (or resume) a hosted Paystack checkout for an order."""
    order = _lookup_order(request, number)
    if order is None:
        messages.error(request, "Order not found.")
        return redirect("orders:order_list")
    if order.user_id != request.user.id:
        raise PermissionDenied("You cannot pay for this order.")
    try:
        payment = payment_services.initialize_payment(
            order, actor=request.user, request=request, channel=request.POST.get("channel", "")
        )
    except (PermissionError, PermissionDenied):
        messages.error(request, "You cannot pay for this order.")
        return redirect("orders:order_detail", number=order.number)
    except Exception as exc:
        if isinstance(exc, ValidationError) or getattr(exc, "messages", None) is not None:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            raise
        return redirect("orders:order_detail", number=order.number)

    url = payment_services.latest_authorization_url(payment)
    if not url:
        messages.info(request, "We could not open the payment page. Please try again.")
        return redirect("orders:payment_detail", pk=payment.pk)
    return redirect(url)


@login_required
def payment_callback(request, number):
    """Paystack redirect target. Re-verifies server-side before trusting it."""
    order = _lookup_order(request, number)
    if order is None:
        messages.error(request, "Order not found.")
        return redirect("orders:order_list")

    reference = request.GET.get("reference") or request.GET.get("trxref") or ""
    queryset = order.payments.filter(provider="paystack")
    payment = None
    if reference:
        payment = (
            queryset.filter(reference=reference).first()
            or queryset.filter(provider_reference=reference).first()
        )
    if payment is None:
        payment = queryset.order_by("-created_at").first()
    if payment is None:
        messages.error(request, "We could not find a payment for this order.")
        return redirect("orders:order_detail", number=order.number)

    try:
        payment_services.verify_payment(payment, request=request, source="callback")
    except ValidationError as exc:  # verification unavailable / rejected
        messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
    except Exception:  # provider/network errors are non-fatal on the callback
        messages.warning(
            request, "We could not confirm your payment yet. Please refresh in a moment."
        )
    else:
        payment.refresh_from_db()
        if payment.status in {PaymentState.PAID, PaymentState.PARTIALLY_REFUNDED}:
            messages.success(request, "Payment confirmed. Thank you!")
        elif payment.requires_review:
            messages.info(request, "Payment received — our finance team will verify it shortly.")
        elif payment.status == PaymentState.FAILED:
            messages.error(request, "The payment was not successful.")
        else:
            messages.info(request, "Your payment is still being processed.")
    return redirect("orders:order_detail", number=order.number)


# ---------------------------------------------------------------------------
# Customer payment portal
# ---------------------------------------------------------------------------


@login_required
def payment_list(request):
    return render(
        request,
        "orders/payments/payment_list.html",
        {"payments": selectors.payments_for_user(request.user), "page_title": "Your payments"},
    )


@login_required
def payment_detail(request, pk):
    payment = selectors.payment_for_user(request.user, pk)
    if payment is None:
        return redirect("orders:payment_list")
    return render(
        request,
        "orders/payments/payment_detail.html",
        {
            "payment": payment,
            "refunds": selectors.refunds_for_payment(payment),
            "receipt": getattr(payment, "receipt", None),
            "page_title": f"Payment {payment.reference}",
        },
    )


@login_required
def bank_transfer_submit(request, number):
    order = _lookup_order(request, number)
    if order is None:
        messages.error(request, "Order not found.")
        return redirect("orders:order_list")

    if request.method == "POST":
        form = BankTransferForm(request.POST, request.FILES, order=order)
        if form.is_valid():
            try:
                payment_services.record_bank_transfer(
                    order,
                    actor=request.user,
                    bank_account=form.cleaned_data["bank_account"],
                    transfer_reference=form.cleaned_data["transfer_reference"],
                    claimed_amount=form.cleaned_data["claimed_amount"],
                    transfer_date=form.cleaned_data.get("transfer_date"),
                    proof=form.cleaned_data.get("proof"),
                    request=request,
                )
            except Exception as exc:
                messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
            else:
                messages.success(request, "Thank you — finance will verify your transfer.")
                return redirect("orders:order_detail", number=order.number)
    else:
        form = BankTransferForm(order=order)
    return render(
        request,
        "orders/payments/bank_transfer_form.html",
        {
            "order": order,
            "form": form,
            "bank_accounts": selectors.active_bank_accounts(currency=order.currency),
            "page_title": f"Bank transfer — {order.number}",
        },
    )


# ---------------------------------------------------------------------------
# Invoices & receipts
# ---------------------------------------------------------------------------


@login_required
def invoice_list(request):
    return render(
        request,
        "orders/invoices/invoice_list.html",
        {"invoices": selectors.invoices_for_user(request.user), "page_title": "Your invoices"},
    )


@login_required
def invoice_detail(request, number):
    invoice = selectors.invoice_for_user(request.user, number)
    if invoice is None:
        return redirect("orders:invoice_list")
    return render(
        request,
        "orders/invoices/invoice_detail.html",
        {
            "invoice": invoice,
            "order": invoice.order,
            "items": invoice.order.items.select_related("listing__product"),
            "page_title": f"Invoice {invoice.number}",
        },
    )


@login_required
def invoice_pdf(request, number):
    from . import documents

    invoice = selectors.invoice_for_user(request.user, number)
    if invoice is None:
        return redirect("orders:invoice_list")
    pdf = documents.render_invoice_pdf(invoice, invoice.order.items.all())
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{invoice.number}.pdf"'
    return response


@login_required
def receipt_detail(request, number):
    receipt = selectors.receipt_for_user(request.user, number)
    if receipt is None:
        return redirect("orders:payment_list")
    return render(
        request,
        "orders/invoices/receipt_detail.html",
        {
            "receipt": receipt,
            "payment": receipt.payment,
            "page_title": f"Receipt {receipt.number}",
        },
    )


@login_required
def receipt_pdf(request, number):
    from . import documents

    receipt = selectors.receipt_for_user(request.user, number)
    if receipt is None:
        return redirect("orders:payment_list")
    pdf = documents.receipt_pdf(receipt)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{receipt.number}.pdf"'
    return response


# ---------------------------------------------------------------------------
# Provider webhook
# ---------------------------------------------------------------------------


@csrf_exempt
def paystack_webhook(request):
    """Signature-verified Paystack webhook endpoint.

    Uses ``request.body`` (raw bytes) because the HMAC is computed over the exact
    payload. Returns 401 for a bad signature, 400 for a malformed payload and
    200 for accepted or duplicate deliveries so Paystack stops retrying.
    """
    if request.method != "POST":
        return HttpResponse(status=405)
    raw = request.body
    signature = request.headers.get("x-paystack-signature", "")
    try:
        payment_services.process_webhook(raw_body=raw, signature=signature, request=request)
    except PermissionDenied:
        return HttpResponse(status=401)
    except (ValidationError, ValueError):
        return HttpResponse(status=400)
    except Exception:  # pragma: no cover - defensive: never leak internals
        return HttpResponse(status=500)
    return HttpResponse(status=200)

"""Finance dashboard views (``/dashboard/finance/...``).

Every view enforces the ``FINANCE_MANAGE`` capability server-side. Writes go
through the service layer (:mod:`apps.orders.payments`) so they are validated,
idempotent and audited — never in the template.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, ListView, TemplateView, UpdateView, View

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability

from . import payments, selectors
from .payment_forms import (
    BankTransferReviewForm,
    CompanyBankAccountForm,
    RefundRequestForm,
)
from .payment_models import (
    BankTransferStatus,
    BankTransferSubmission,
    CompanyBankAccount,
    Invoice,
    InvoiceState,
    Payment,
    PaymentState,
    Refund,
    RefundState,
)


class FinanceAccessMixin:
    capability = Capability.FINANCE_MANAGE
    active_nav = "finance"
    breadcrumbs: list[dict] = []

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not has_capability(request.user, self.capability):
            raise PermissionDenied("You do not have permission to manage finance.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("active_nav", self.active_nav)
        context.setdefault(
            "breadcrumbs",
            [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Finance", "url": "finance_dashboard:home"},
                *self.breadcrumbs,
            ],
        )
        return context


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class FinanceDashboardHome(FinanceAccessMixin, TemplateView):
    template_name = "dashboard/finance/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Finance",
                "overview": selectors.finance_overview(),
                "revenue_by_day": selectors.revenue_by_day(days=30),
                "recent_payments": selectors.staff_payments()[:8],
                "pending_transfers": selectors.staff_bank_transfers(
                    status=BankTransferStatus.SUBMITTED
                )[:5],
                "refunds_pending": selectors.staff_refunds(status=RefundState.REQUESTED)[:5],
            }
        )
        return context


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


class PaymentListView(FinanceAccessMixin, ListView):
    template_name = "dashboard/finance/payment_list.html"
    context_object_name = "payments"
    paginate_by = 25

    def get_queryset(self):
        return selectors.staff_payments(
            status=self.request.GET.get("status", ""),
            provider=self.request.GET.get("provider", ""),
            query=self.request.GET.get("q", ""),
            review=self.request.GET.get("review") == "1",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Payments",
                "statuses": PaymentState.choices,
                "status": self.request.GET.get("status", ""),
                "provider": self.request.GET.get("provider", ""),
                "query": self.request.GET.get("q", ""),
                "review_only": self.request.GET.get("review") == "1",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Finance", "url": "finance_dashboard:home"},
                    {"label": "Payments"},
                ],
            }
        )
        return context


class PaymentDetailView(FinanceAccessMixin, TemplateView):
    template_name = "dashboard/finance/payment_detail.html"

    def get_payment(self) -> Payment:
        return get_object_or_404(
            Payment.objects.select_related("order", "customer"), pk=self.kwargs["pk"]
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.get_payment()
        context.update(
            {
                "payment": payment,
                "attempts": payment.attempts.all(),
                "refunds": selectors.refunds_for_payment(payment),
                "webhook_events": payment.webhook_events.order_by("-received_at")[:20],
                "receipt": getattr(payment, "receipt", None),
                "refund_form": RefundRequestForm(payment=payment),
                "page_title": f"Payment {payment.reference}",
                "refund_total": payment.refunds.filter(status=RefundState.COMPLETED).aggregate(
                    total=Sum("amount")
                )["total"]
                or 0,
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Finance", "url": "finance_dashboard:home"},
                    {"label": "Payments", "url": "finance_dashboard:payment_list"},
                    {"label": payment.reference},
                ],
            }
        )
        return context


class PaymentReconcileView(FinanceAccessMixin, View):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        payment = get_object_or_404(Payment, pk=self.kwargs["pk"])
        try:
            result = payments.reconcile_payment(payment)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            if result["action"] == "verified":
                messages.success(request, "Payment re-verified with Paystack.")
            else:
                messages.info(request, f"No change ({result.get('action')}).")
        return redirect(reverse("finance_dashboard:payment_detail", args=[payment.pk]))


# ---------------------------------------------------------------------------
# Bank transfers
# ---------------------------------------------------------------------------


class BankTransferListView(FinanceAccessMixin, ListView):
    template_name = "dashboard/finance/bank_transfer_list.html"
    context_object_name = "transfers"
    paginate_by = 25

    def get_queryset(self):
        return selectors.staff_bank_transfers(
            status=self.request.GET.get("status", ""), query=self.request.GET.get("q", "")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Bank transfers",
                "statuses": BankTransferStatus.choices,
                "status": self.request.GET.get("status", ""),
                "query": self.request.GET.get("q", ""),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Finance", "url": "finance_dashboard:home"},
                    {"label": "Bank transfers"},
                ],
            }
        )
        return context


class BankTransferDetailView(FinanceAccessMixin, TemplateView):
    template_name = "dashboard/finance/bank_transfer_detail.html"

    def get_transfer(self) -> BankTransferSubmission:
        return get_object_or_404(
            BankTransferSubmission.objects.select_related(
                "payment__order", "payment__customer", "bank_account"
            ),
            pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transfer = self.get_transfer()
        context.update(
            {
                "transfer": transfer,
                "payment": transfer.payment,
                "order": transfer.payment.order,
                "review_form": BankTransferReviewForm(),
                "page_title": f"Transfer {transfer.transfer_reference}",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Finance", "url": "finance_dashboard:home"},
                    {"label": "Bank transfers", "url": "finance_dashboard:bank_transfer_list"},
                    {"label": transfer.transfer_reference},
                ],
            }
        )
        return context


class BankTransferReviewView(FinanceAccessMixin, View):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        transfer = get_object_or_404(BankTransferSubmission, pk=self.kwargs["pk"])
        form = BankTransferReviewForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Check the review form.")
            return redirect(reverse("finance_dashboard:bank_transfer_detail", args=[transfer.pk]))
        approve = form.cleaned_data["decision"] == "approve"
        try:
            payments.review_bank_transfer(
                transfer,
                actor=request.user,
                approve=approve,
                notes=form.cleaned_data.get("notes", ""),
                settlement_confirmed=form.cleaned_data.get("settlement_confirmed", False),
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(
                request,
                "Transfer approved and order settled." if approve else "Transfer rejected.",
            )
        return redirect(reverse("finance_dashboard:bank_transfer_detail", args=[transfer.pk]))


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------


class RefundListView(FinanceAccessMixin, ListView):
    template_name = "dashboard/finance/refund_list.html"
    context_object_name = "refunds"
    paginate_by = 25

    def get_queryset(self):
        return selectors.staff_refunds(status=self.request.GET.get("status", ""))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Refunds",
                "statuses": RefundState.choices,
                "status": self.request.GET.get("status", ""),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Finance", "url": "finance_dashboard:home"},
                    {"label": "Refunds"},
                ],
            }
        )
        return context


class RefundDetailView(FinanceAccessMixin, TemplateView):
    template_name = "dashboard/finance/refund_detail.html"

    def get_refund(self) -> Refund:
        return get_object_or_404(
            Refund.objects.select_related("payment__order", "payment__customer"),
            pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        refund = self.get_refund()
        context.update(
            {
                "refund": refund,
                "payment": refund.payment,
                "order": refund.payment.order,
                "page_title": f"Refund {refund.reference}",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Finance", "url": "finance_dashboard:home"},
                    {"label": "Refunds", "url": "finance_dashboard:refund_list"},
                    {"label": refund.reference},
                ],
            }
        )
        return context


class RefundRequestView(FinanceAccessMixin, View):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        payment = get_object_or_404(Payment, pk=self.kwargs["pk"])
        form = RefundRequestForm(request.POST, payment=payment)
        if not form.is_valid():
            messages.error(request, "Enter a valid refund amount.")
            return redirect(reverse("finance_dashboard:payment_detail", args=[payment.pk]))
        try:
            refund = payments.request_refund(
                payment,
                actor=request.user,
                amount=form.cleaned_data["amount"],
                reason=form.cleaned_data.get("reason", ""),
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
            return redirect(reverse("finance_dashboard:payment_detail", args=[payment.pk]))
        messages.success(request, "Refund requested — approve it to send to the provider.")
        return redirect(reverse("finance_dashboard:refund_detail", args=[refund.pk]))


class RefundApproveView(FinanceAccessMixin, View):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        refund = get_object_or_404(Refund, pk=self.kwargs["pk"])
        try:
            refund = payments.approve_refund(refund, actor=request.user, request=request)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(
                request,
                "Refund approved and sent to the provider."
                if refund.status == RefundState.PROCESSING
                else "Refund approved.",
            )
        return redirect(reverse("finance_dashboard:refund_detail", args=[refund.pk]))


class RefundCompleteView(FinanceAccessMixin, View):
    """Mark an offline/bank refund settled (Paystack refunds complete via webhook)."""

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        refund = get_object_or_404(Refund, pk=self.kwargs["pk"])
        try:
            refund = payments.complete_refund(refund, request=request)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(request, "Refund marked as completed.")
        return redirect(reverse("finance_dashboard:refund_detail", args=[refund.pk]))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


class InvoiceListView(FinanceAccessMixin, ListView):
    template_name = "dashboard/finance/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 25

    def get_queryset(self):
        return selectors.staff_invoices(status=self.request.GET.get("status", ""))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Invoices",
                "statuses": InvoiceState.choices,
                "status": self.request.GET.get("status", ""),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Finance", "url": "finance_dashboard:home"},
                    {"label": "Invoices"},
                ],
            }
        )
        return context


class InvoiceDetailView(FinanceAccessMixin, TemplateView):
    template_name = "dashboard/finance/invoice_detail.html"

    def get_invoice(self) -> Invoice:
        return get_object_or_404(
            Invoice.objects.select_related("order"), number=self.kwargs["number"]
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.get_invoice()
        context.update(
            {
                "invoice": invoice,
                "order": invoice.order,
                "items": invoice.order.items.select_related("listing__product"),
                "page_title": f"Invoice {invoice.number}",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Finance", "url": "finance_dashboard:home"},
                    {"label": "Invoices", "url": "finance_dashboard:invoice_list"},
                    {"label": invoice.number},
                ],
            }
        )
        return context


# ---------------------------------------------------------------------------
# Company bank accounts
# ---------------------------------------------------------------------------


class BankAccountListView(FinanceAccessMixin, ListView):
    template_name = "dashboard/finance/bank_account_list.html"
    context_object_name = "accounts"

    def get_queryset(self):
        return selectors.staff_bank_accounts()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Company bank accounts",
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Finance", "url": "finance_dashboard:home"},
                    {"label": "Bank accounts"},
                ],
            }
        )
        return context


class BankAccountCreateView(FinanceAccessMixin, CreateView):
    template_name = "dashboard/finance/bank_account_form.html"
    form_class = CompanyBankAccountForm

    def form_valid(self, form):
        try:
            payments.create_bank_account(
                actor=self.request.user,
                bank_name=form.cleaned_data["bank_name"],
                account_name=form.cleaned_data["account_name"],
                account_number=form.cleaned_data["account_number"],
                currency=form.cleaned_data["currency"],
                instructions=form.cleaned_data.get("instructions", ""),
                sort_order=form.cleaned_data.get("sort_order", 0),
                request=self.request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(self.request, "; ".join(getattr(exc, "messages", [str(exc)])))
            return self.form_invalid(form)
        messages.success(self.request, "Bank account added.")
        return redirect("finance_dashboard:bank_account_list")


class BankAccountUpdateView(FinanceAccessMixin, UpdateView):
    template_name = "dashboard/finance/bank_account_form.html"
    form_class = CompanyBankAccountForm

    def get_queryset(self):
        return CompanyBankAccount.objects.all()

    def form_valid(self, form):
        self.object = form.save(commit=False)
        try:
            payments.update_bank_account(
                self.object,
                actor=self.request.user,
                bank_name=form.cleaned_data["bank_name"],
                account_name=form.cleaned_data["account_name"],
                account_number=form.cleaned_data["account_number"],
                currency=form.cleaned_data["currency"],
                instructions=form.cleaned_data.get("instructions", ""),
                sort_order=form.cleaned_data.get("sort_order", 0),
                is_active=form.cleaned_data["is_active"],
                request=self.request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(self.request, "; ".join(getattr(exc, "messages", [str(exc)])))
            return self.form_invalid(form)
        messages.success(self.request, "Bank account updated.")
        return redirect("finance_dashboard:bank_account_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit bank account"
        return context


class BankAccountToggleView(FinanceAccessMixin, View):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        account = get_object_or_404(CompanyBankAccount, pk=self.kwargs["pk"])
        try:
            payments.set_bank_account_active(
                account,
                actor=request.user,
                is_active=not account.is_active,
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(request, "Bank account updated.")
        return redirect("finance_dashboard:bank_account_list")

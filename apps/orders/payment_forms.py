"""Forms for Phase 6 payments: bank transfers, refunds, bank account config.

Widgets reuse the shared ``TailwindFormMixin`` so the finance and customer
screens match the rest of the site. QuerySets that depend on configuration
(active bank accounts) are set in ``__init__`` — nothing is hardcoded.
"""

from __future__ import annotations

from decimal import Decimal

from django import forms

from .forms import OrdersForm, OrdersPlainForm
from .payment_models import CompanyBankAccount

BANK_TRANSFER_DECISIONS = [
    ("approve", "Approve — funds confirmed"),
    ("reject", "Reject"),
]


class BankTransferForm(OrdersPlainForm):
    """Customer claim of a manual bank transfer (never a settlement)."""

    bank_account = forms.ModelChoiceField(
        queryset=CompanyBankAccount.objects.none(),
        label="Company bank account",
        empty_label="— Select the account you paid —",
    )
    transfer_reference = forms.CharField(
        max_length=120,
        label="Transfer reference / teller number",
        help_text="The reference shown on your bank receipt or transfer confirmation.",
    )
    claimed_amount = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01"), label="Amount transferred"
    )
    transfer_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}), label="Date of transfer"
    )
    proof = forms.FileField(
        required=False,
        label="Proof of payment (optional)",
        help_text="A receipt image or PDF. This does not confirm payment on its own.",
    )

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = CompanyBankAccount.objects.filter(is_active=True).order_by(
            "sort_order", "bank_name"
        )
        if order is not None:
            accounts = accounts.filter(currency=order.currency)
        self.fields["bank_account"].queryset = accounts


class BankTransferReviewForm(OrdersPlainForm):
    decision = forms.ChoiceField(choices=BANK_TRANSFER_DECISIONS, label="Decision")
    settlement_confirmed = forms.BooleanField(
        required=False,
        label="I have confirmed the funds in the company bank statement",
        help_text="Approving without confirmed settlement is not allowed.",
    )
    notes = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Review notes"
    )


class RefundRequestForm(OrdersPlainForm):
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01"), label="Refund amount"
    )
    reason = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Reason"
    )

    def __init__(self, *args, payment=None, **kwargs):
        super().__init__(*args, **kwargs)
        if payment is not None:
            self.fields["amount"].initial = payment.settled_amount
            self.fields[
                "amount"
            ].help_text = f"Maximum refundable: {payment.currency} {payment.settled_amount:,.2f}."


class CompanyBankAccountForm(OrdersForm):
    class Meta:
        model = CompanyBankAccount
        fields = (
            "bank_name",
            "account_name",
            "account_number",
            "currency",
            "instructions",
            "sort_order",
            "is_active",
        )
        widgets = {"instructions": forms.Textarea(attrs={"rows": 3})}


class PaystackChannelForm(OrdersPlainForm):
    """Optional channel preference when starting a Paystack checkout."""

    channel = forms.ChoiceField(
        choices=[
            ("", "Any available method"),
            ("card", "Card"),
            ("bank", "Bank"),
            ("ussd", "USSD"),
            ("bank_transfer", "Bank transfer (Paystack)"),
            ("qr", "QR code"),
            ("mobile_money", "Mobile money"),
        ],
        required=False,
    )


__all__ = [
    "BankTransferForm",
    "BankTransferReviewForm",
    "CompanyBankAccountForm",
    "PaystackChannelForm",
    "RefundRequestForm",
]

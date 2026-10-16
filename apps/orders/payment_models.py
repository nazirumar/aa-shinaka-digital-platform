"""Phase 6 payment, refund, invoice and receipt models.

These live in the ``orders`` domain (cart → checkout → order → payment →
fulfilment). The provider-independent order boundary from Phase 5 is preserved:
``apps.orders.services.confirm_payment`` / ``settle_order`` remain the only way an
order becomes paid, and Phase 6 calls into them after an authoritative provider
verification.

Money is always ``Decimal``. Amounts are converted to a provider's smallest
currency unit **only** inside ``apps.orders.paystack`` (the API boundary).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.accounts.models import User

from .models import UUIDTimeStampedModel

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PaymentProvider(models.TextChoices):
    PAYSTACK = "paystack", "Paystack"
    BANK_TRANSFER = "bank_transfer", "Bank transfer"
    MANUAL = "manual", "Manual / offline"


class PaymentState(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    ABANDONED = "abandoned", "Abandoned"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"


# Payment states in which a payment still counts as an open/attempted payment.
OPEN_PAYMENT_STATES = frozenset({PaymentState.PENDING, PaymentState.PROCESSING})

# Payment states that represent captured funds eligible for a refund.
REFUNDABLE_PAYMENT_STATES = frozenset({PaymentState.PAID, PaymentState.PARTIALLY_REFUNDED})


class PaymentMethod(models.TextChoices):
    CARD = "card", "Card"
    BANK = "bank", "Bank"
    USSD = "ussd", "USSD"
    TRANSFER = "transfer", "Bank transfer"
    QR = "qr", "QR code"
    MOBILE_MONEY = "mobile_money", "Mobile money"
    MANUAL = "manual", "Manual"
    OTHER = "other", "Other"


class PaymentAttemptStatus(models.TextChoices):
    INITIALIZED = "initialized", "Initialized"
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    ABANDONED = "abandoned", "Abandoned"


class WebhookEventStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"
    IGNORED = "ignored", "Ignored"


class BankTransferStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    UNDER_REVIEW = "under_review", "Under review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class RefundState(models.TextChoices):
    REQUESTED = "requested", "Requested"
    APPROVED = "approved", "Approved"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    REJECTED = "rejected", "Rejected"


class RefundProviderState(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    REVERSED = "reversed", "Reversed"


class InvoiceState(models.TextChoices):
    UNPAID = "unpaid", "Unpaid"
    PARTIALLY_PAID = "partially_paid", "Partially paid"
    PAID = "paid", "Paid"
    REFUNDED = "refunded", "Refunded"
    VOID = "void", "Void"


# ---------------------------------------------------------------------------
# Company bank accounts (Task 7 — configured by authorised finance staff only)
# ---------------------------------------------------------------------------


class CompanyBankAccount(UUIDTimeStampedModel):
    """A verified AA Shinaka settlement account shown for manual transfers."""

    bank_name = models.CharField(max_length=120)
    account_name = models.CharField(max_length=150)
    account_number = models.CharField(max_length=34)
    currency = models.CharField(max_length=3, default="NGN")
    instructions = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["sort_order", "bank_name"]
        verbose_name = "Company bank account"
        verbose_name_plural = "Company bank accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["bank_name", "account_number", "currency"],
                name="uniq_bank_account",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.bank_name} · {self.account_number}"


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


class PaymentPurpose(models.TextChoices):
    """What a payment represents against its target (Phase 8 export orders)."""

    FULL = "full", "Full payment"
    DEPOSIT = "deposit", "Deposit"
    BALANCE = "balance", "Balance"
    OTHER = "other", "Other"


class Payment(UUIDTimeStampedModel):
    """A single attempt to settle one order through one provider."""

    order = models.ForeignKey(
        "orders.Order",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    service_quotation = models.ForeignKey(
        "services.ServiceQuotation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    export_order = models.ForeignKey(
        "export.ExportOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    training_enrollment = models.ForeignKey(
        "training.Enrollment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    purpose = models.CharField(
        max_length=12, choices=PaymentPurpose.choices, default=PaymentPurpose.FULL, blank=True
    )
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="payments")
    reference = models.CharField(max_length=80, unique=True, db_index=True)
    provider = models.CharField(
        max_length=20,
        choices=PaymentProvider.choices,
        default=PaymentProvider.PAYSTACK,
        db_index=True,
    )
    method = models.CharField(max_length=20, choices=PaymentMethod.choices, blank=True)
    currency = models.CharField(max_length=3, default="NGN")
    expected_amount = models.DecimalField(max_digits=14, decimal_places=2)
    verified_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=PaymentState.choices,
        default=PaymentState.PENDING,
        db_index=True,
    )
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    channel = models.CharField(max_length=40, blank=True)
    requires_review = models.BooleanField(default=False, db_index=True)
    review_reason = models.CharField(max_length=200, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        constraints = [
            models.CheckConstraint(
                condition=Q(expected_amount__gte=0), name="chk_payment_expected_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(verified_amount__isnull=True) | Q(verified_amount__gte=0),
                name="chk_payment_verified_nonneg",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        order__isnull=False,
                        service_quotation__isnull=True,
                        export_order__isnull=True,
                        training_enrollment__isnull=True,
                    )
                    | models.Q(
                        order__isnull=True,
                        service_quotation__isnull=False,
                        export_order__isnull=True,
                        training_enrollment__isnull=True,
                    )
                    | models.Q(
                        order__isnull=True,
                        service_quotation__isnull=True,
                        export_order__isnull=False,
                        training_enrollment__isnull=True,
                    )
                    | models.Q(
                        order__isnull=True,
                        service_quotation__isnull=True,
                        export_order__isnull=True,
                        training_enrollment__isnull=False,
                    )
                ),
                name="chk_payment_single_target",
            ),
        ]
        indexes = [
            models.Index(fields=["order", "status"]),
            models.Index(fields=["service_quotation", "status"]),
            models.Index(fields=["export_order", "status"]),
            models.Index(fields=["training_enrollment", "status"]),
            models.Index(fields=["provider", "provider_reference"]),
            models.Index(fields=["status", "requires_review"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} ({self.get_provider_display()})"

    @property
    def settled_amount(self):
        """The amount actually captured (verified) or expected if not yet paid."""
        return self.verified_amount if self.verified_amount is not None else self.expected_amount

    @property
    def is_settled(self) -> bool:
        return self.status in REFUNDABLE_PAYMENT_STATES


class PaymentAttempt(UUIDTimeStampedModel):
    """A provider round-trip for a payment (one per initialise/hosted checkout)."""

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="attempts")
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    authorization_url = models.URLField(max_length=500, blank=True)
    access_code = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=16,
        choices=PaymentAttemptStatus.choices,
        default=PaymentAttemptStatus.INITIALIZED,
        db_index=True,
    )
    failure_code = models.CharField(max_length=80, blank=True)
    failure_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Payment attempt"
        verbose_name_plural = "Payment attempts"

    def __str__(self) -> str:
        return f"Attempt · {self.payment.reference} · {self.status}"


class PaymentWebhookEvent(UUIDTimeStampedModel):
    """Durable provider webhook record used for deduplication and replay."""

    provider = models.CharField(max_length=20, default=PaymentProvider.PAYSTACK)
    event_id = models.CharField(max_length=160)
    event_type = models.CharField(max_length=80, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=WebhookEventStatus.choices,
        default=WebhookEventStatus.RECEIVED,
        db_index=True,
    )
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    payment = models.ForeignKey(
        Payment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="webhook_events",
    )

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "Payment webhook event"
        verbose_name_plural = "Payment webhook events"
        constraints = [
            models.UniqueConstraint(fields=["provider", "event_id"], name="uniq_webhook_event"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_type} [{self.status}]"


# ---------------------------------------------------------------------------
# Bank transfers (Task 7)
# ---------------------------------------------------------------------------


class BankTransferSubmission(UUIDTimeStampedModel):
    """A customer's claimed manual bank transfer, reviewed by finance."""

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="bank_transfers")
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="bank_transfers")
    bank_account = models.ForeignKey(
        CompanyBankAccount,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submissions",
    )
    bank_name_snapshot = models.CharField(max_length=120, blank=True)
    account_number_snapshot = models.CharField(max_length=34, blank=True)
    transfer_reference = models.CharField(max_length=120, db_index=True)
    claimed_amount = models.DecimalField(max_digits=14, decimal_places=2)
    transfer_date = models.DateField(null=True, blank=True)
    proof = models.FileField(upload_to="payment_proofs/%Y/%m/", blank=True)
    status = models.CharField(
        max_length=16,
        choices=BankTransferStatus.choices,
        default=BankTransferStatus.SUBMITTED,
        db_index=True,
    )
    settlement_confirmed = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Bank transfer submission"
        verbose_name_plural = "Bank transfer submissions"
        constraints = [
            models.CheckConstraint(
                condition=Q(claimed_amount__gte=0), name="chk_banktransfer_amount_nonneg"
            ),
            # A single bank transaction must not settle more than one order.
            models.UniqueConstraint(
                fields=["transfer_reference", "account_number_snapshot"],
                condition=Q(status=BankTransferStatus.APPROVED),
                name="uniq_approved_bank_transfer",
            ),
        ]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self) -> str:
        return f"Transfer {self.transfer_reference} · {self.get_status_display()}"


# ---------------------------------------------------------------------------
# Refunds (Task 9)
# ---------------------------------------------------------------------------


class Refund(UUIDTimeStampedModel):
    """A finance-approved reversal against a settled payment."""

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    reference = models.CharField(max_length=80, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=RefundState.choices,
        default=RefundState.REQUESTED,
        db_index=True,
    )
    provider_status = models.CharField(
        max_length=16, choices=RefundProviderState.choices, blank=True
    )
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    requested_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="refunds_requested"
    )
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="refunds_approved"
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Refund"
        verbose_name_plural = "Refunds"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="chk_refund_amount_positive"),
            models.UniqueConstraint(
                fields=["provider_reference"],
                condition=~Q(provider_reference=""),
                name="uniq_refund_provider_reference",
            ),
        ]
        indexes = [models.Index(fields=["payment", "status"])]

    def __str__(self) -> str:
        return f"Refund {self.reference} · {self.amount}"


# ---------------------------------------------------------------------------
# Invoices & receipts (Task 8)
# ---------------------------------------------------------------------------

INVOICE_IMMUTABLE_FIELDS = (
    "number",
    "currency",
    "customer_name",
    "customer_email",
    "customer_phone",
    "billing_address",
    "subtotal",
    "shipping_amount",
    "discount_amount",
    "tax_amount",
    "total",
)


class Invoice(UUIDTimeStampedModel):
    """An issued, immutable order invoice with a billing snapshot."""

    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="invoice")
    number = models.CharField(max_length=32, unique=True, db_index=True)
    currency = models.CharField(max_length=3, default="NGN")
    customer_name = models.CharField(max_length=150)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20, blank=True)
    billing_address = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    shipping_amount = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    total = models.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    status = models.CharField(
        max_length=20,
        choices=InvoiceState.choices,
        default=InvoiceState.UNPAID,
        db_index=True,
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0), name="chk_invoice_total_nonneg"),
        ]
        indexes = [models.Index(fields=["status", "-created_at"])]

    _IMMUTABLE_FIELDS = (
        "number",
        "currency",
        "customer_name",
        "customer_email",
        "customer_phone",
        "billing_address",
        "subtotal",
        "shipping_amount",
        "discount_amount",
        "tax_amount",
        "total",
    )

    def save(self, *args, **kwargs):  # type: ignore[override]
        if not self._state.adding and self.issued_at is not None:
            previous = type(self).objects.filter(pk=self.pk).values(*self._IMMUTABLE_FIELDS).first()
            if previous is not None:
                for field in self._IMMUTABLE_FIELDS:
                    if str(getattr(self, field)) != str(previous[field]):
                        raise ValidationError(
                            "Issued invoices are immutable; issue a credit note instead."
                        )
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.number


class Receipt(UUIDTimeStampedModel):
    """Proof of a verified payment; one receipt per payment, immutable once issued."""

    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="receipt")
    number = models.CharField(max_length=32, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Receipt"
        verbose_name_plural = "Receipts"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="chk_receipt_amount_nonneg"),
        ]

    def save(self, *args, **kwargs):  # type: ignore[override]
        if not self._state.adding and self.issued_at is not None:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("number", "amount", "currency", "payment_id")
                .first()
            )
            if previous is not None:
                if (
                    self.number != previous["number"]
                    or str(self.amount) != str(previous["amount"])
                    or self.currency != previous["currency"]
                    or self.payment_id != previous["payment_id"]
                ):
                    raise ValidationError("Issued receipts are immutable.")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.number


__all__ = [
    "BankTransferStatus",
    "BankTransferSubmission",
    "CompanyBankAccount",
    "Invoice",
    "InvoiceState",
    "OPEN_PAYMENT_STATES",
    "Payment",
    "PaymentAttempt",
    "PaymentAttemptStatus",
    "PaymentMethod",
    "PaymentProvider",
    "PaymentState",
    "PaymentWebhookEvent",
    "REFUNDABLE_PAYMENT_STATES",
    "Receipt",
    "Refund",
    "RefundProviderState",
    "RefundState",
    "WebhookEventStatus",
]

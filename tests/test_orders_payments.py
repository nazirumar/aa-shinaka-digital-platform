"""Phase 6 tests: Paystack payments, webhooks, bank transfers, refunds,
invoices/receipts, reconciliation and finance permissions.

Paystack is never called for real: the API boundary in
``apps.orders.paystack`` is monkeypatched, and the webhook secret is a test
value. Money is always ``Decimal``; provider amounts are converted to kobo only
at that boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
from decimal import Decimal

import pytest
from catalog_helpers import make_sellable_product
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone
from orders_helpers import make_address, make_shipping

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.orders import documents, payments, paystack, selectors, services
from apps.orders.models import (
    Cart,
    Order,
    OrderStatus,
    PaymentStatus,
    ReservationStatus,
)
from apps.orders.payment_models import (
    BankTransferStatus,
    CompanyBankAccount,
    InvoiceState,
    Payment,
    PaymentProvider,
    PaymentState,
    Receipt,
    RefundState,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _catalog_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def finance_user(db) -> User:
    user = User.objects.create_user(
        email="finance@example.com",
        password="test-pass-12345",
        first_name="Femi",
        last_name="Ade",
        role=UserRole.FINANCE_OFFICER,
        is_staff=True,
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def other_customer(db) -> User:
    user = User.objects.create_user(
        email="other@example.com",
        password="test-pass-12345",
        role=UserRole.CUSTOMER,
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def paystack_enabled(settings):
    settings.PAYSTACK_ENABLED = True
    settings.PAYSTACK_SECRET_KEY = "sk_test_1234567890"
    settings.PAYSTACK_WEBHOOK_SECRET = ""
    settings.PAYSTACK_CURRENCY = "NGN"
    return settings


@pytest.fixture
def fake_paystack(monkeypatch):
    """Patch the two Paystack round-trips and expose a controllable state bag."""
    state: dict = {}

    def fake_initialize(**kwargs):
        state["initialize"] = kwargs
        return {
            "authorization_url": "https://checkout.paystack.test/abc123",
            "access_code": "acc_test_code",
            "reference": kwargs["reference"],
        }

    def fake_verify(reference):
        state["verified_reference"] = reference
        payload = dict(state.get("verify_payload") or {})
        payload.setdefault("reference", reference)
        payload.setdefault("status", "success")
        return payload

    monkeypatch.setattr(paystack, "initialize_transaction", fake_initialize)
    monkeypatch.setattr(paystack, "verify_transaction", fake_verify)
    return state


def _login(client, user) -> None:
    assert client.login(email=user.email, password="test-pass-12345")


_order_seq = itertools.count(1)


def _place_order(customer, *, quantity="2", stock="20.000", price="25000.00", fee="1500.00"):
    seq = next(_order_seq)
    _, listing = make_sellable_product(stock=stock, price=price)
    zone, method, rate = make_shipping(
        listing.state,
        name=f"Standard delivery {seq}",
        code=f"standard-{seq}",
        fee=fee,
    )
    address = make_address(customer, state=listing.state)
    cart = Cart.objects.create(user=customer)
    services.add_to_cart(cart, listing=listing, quantity=quantity)
    order = services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token=f"tok-{seq}",
    )
    return order, listing


def _kobo(amount) -> int:
    return int((Decimal(str(amount)) * 100).to_integral_value())


def _verify_payload(order, payment, *, status="success", amount=None, currency=None):
    return {
        "id": 99887766,
        "reference": payment.reference,
        "status": status,
        "amount": _kobo(order.grand_total) if amount is None else amount,
        "currency": currency or order.currency,
        "channel": "card",
    }


def _sign(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha512).hexdigest()


def _post_webhook(client, secret: str, payload: dict, *, signature: str | None = None):
    raw = json.dumps(payload).encode("utf-8")
    sig = signature if signature is not None else _sign(raw, secret)
    return client.post(
        reverse("orders:paystack_webhook"),
        data=raw,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=sig,
    )


def _charge_success_event(order, payment, *, event_id="evt_charge_1"):
    return {
        "event": "charge.success",
        "id": event_id,
        "data": _verify_payload(order, payment),
    }


# ---------------------------------------------------------------------------
# Initialisation & hosted checkout
# ---------------------------------------------------------------------------


def test_initialize_payment_creates_processing_payment(customer, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)

    payment = payments.initialize_payment(order, actor=customer)

    assert payment.provider == PaymentProvider.PAYSTACK
    assert payment.status == PaymentState.PROCESSING
    assert payment.expected_amount == order.grand_total
    assert fake_paystack["initialize"]["amount_kobo"] == _kobo(order.grand_total)
    assert fake_paystack["initialize"]["currency"] == "NGN"
    attempt = payment.attempts.get()
    assert attempt.authorization_url == "https://checkout.paystack.test/abc123"
    assert payments.latest_authorization_url(payment) == "https://checkout.paystack.test/abc123"


def test_initialize_payment_reuses_open_payment(customer, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)

    first = payments.initialize_payment(order, actor=customer)
    second = payments.initialize_payment(order, actor=customer)

    assert first.pk == second.pk
    assert Payment.objects.filter(order=order).count() == 1


def test_customer_cannot_pay_someone_elses_order(customer, other_customer, paystack_enabled):
    order, _ = _place_order(customer)

    with pytest.raises(PermissionDenied):
        payments.initialize_payment(order, actor=other_customer)


def test_initialize_payment_disabled_when_paystack_off(customer, settings):
    settings.PAYSTACK_ENABLED = False
    order, _ = _place_order(customer)

    with pytest.raises(ValidationError):
        payments.initialize_payment(order, actor=customer)


# ---------------------------------------------------------------------------
# Verification (server side, never the browser)
# ---------------------------------------------------------------------------


def test_verify_success_settles_order_and_issues_receipt(customer, paystack_enabled, fake_paystack):
    order, listing = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)

    payments.verify_payment(payment)

    order.refresh_from_db()
    listing.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == PaymentState.PAID
    assert payment.verified_amount == order.grand_total
    assert payment.verified_at is not None
    assert order.status == OrderStatus.CONFIRMED
    assert order.payment_status == PaymentStatus.PAID
    assert order.reservations.get().status == ReservationStatus.COMMITTED
    assert listing.stock_on_hand == Decimal("18.000")
    assert Receipt.objects.filter(payment=payment).count() == 1


def test_verify_is_idempotent(customer, paystack_enabled, fake_paystack):
    order, listing = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)

    payments.verify_payment(payment)
    payments.verify_payment(payment)

    payment.refresh_from_db()
    assert Receipt.objects.filter(payment=payment).count() == 1
    listing.refresh_from_db()
    assert listing.stock_on_hand == Decimal("18.000")


def test_verify_underpayment_is_flagged_not_paid(customer, paystack_enabled, fake_paystack):
    order, listing = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(
        order, payment, amount=_kobo(order.grand_total) - 100
    )

    payments.verify_payment(payment)

    order.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == PaymentState.FAILED
    assert payment.requires_review is True
    assert order.payment_status == PaymentStatus.PENDING
    assert order.status == OrderStatus.PENDING_PAYMENT
    assert not Receipt.objects.filter(payment=payment).exists()


def test_verify_currency_mismatch_is_flagged(customer, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment, currency="USD")

    payments.verify_payment(payment)

    payment.refresh_from_db()
    assert payment.status == PaymentState.FAILED
    assert payment.requires_review is True
    assert "Currency mismatch" in payment.review_reason


def test_callback_view_does_not_trust_browser_amount(
    client, customer, paystack_enabled, fake_paystack
):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    # The provider says the capture was smaller than the order total.
    fake_paystack["verify_payload"] = _verify_payload(order, payment, amount=100)
    _login(client, customer)

    response = client.get(
        reverse("orders:payment_callback", args=[order.number]),
        {"reference": payment.reference, "amount": "1"},
    )

    assert response.status_code == 302
    order.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == PaymentState.FAILED
    assert order.payment_status == PaymentStatus.PENDING


def test_verify_late_payment_after_expiry_flags_review(customer, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    Order.objects.filter(pk=order.pk).update(
        expires_at=timezone.now() - timezone.timedelta(hours=1)
    )
    services.expire_orders()
    order.refresh_from_db()
    assert order.status == OrderStatus.EXPIRED

    fake_paystack["verify_payload"] = _verify_payload(order, payment)
    payments.verify_payment(payment)

    order.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == PaymentState.PAID
    assert payment.requires_review is True
    # A late payment must never auto-complete the order.
    assert order.status == OrderStatus.EXPIRED
    assert order.payment_status == PaymentStatus.PENDING


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def test_webhook_rejects_bad_signature(client, paystack_enabled):
    payload = {"event": "charge.success", "id": "evt_bad", "data": {}}

    response = _post_webhook(client, "wrong-secret", payload)

    assert response.status_code == 401


def test_webhook_accepts_valid_signature_and_settles(
    client, customer, paystack_enabled, fake_paystack
):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)

    response = _post_webhook(
        client, paystack_enabled.PAYSTACK_SECRET_KEY, _charge_success_event(order, payment)
    )

    assert response.status_code == 200
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == PaymentStatus.PAID
    assert payment.status == PaymentState.PAID


def test_webhook_duplicate_delivery_is_idempotent(
    client, customer, paystack_enabled, fake_paystack
):
    order, listing = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    event = _charge_success_event(order, payment)

    _post_webhook(client, paystack_enabled.PAYSTACK_SECRET_KEY, event)
    _post_webhook(client, paystack_enabled.PAYSTACK_SECRET_KEY, event)

    payment.refresh_from_db()
    listing.refresh_from_db()
    assert Receipt.objects.filter(payment=payment).count() == 1
    assert listing.stock_on_hand == Decimal("18.000")
    from apps.orders.payment_models import PaymentWebhookEvent

    assert PaymentWebhookEvent.objects.count() == 1


def test_webhook_late_payment_flags_review_without_completing(
    client, customer, paystack_enabled, fake_paystack
):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    Order.objects.filter(pk=order.pk).update(
        expires_at=timezone.now() - timezone.timedelta(hours=1)
    )
    services.expire_orders()

    response = _post_webhook(
        client, paystack_enabled.PAYSTACK_SECRET_KEY, _charge_success_event(order, payment)
    )

    assert response.status_code == 200
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.status == OrderStatus.EXPIRED
    assert order.payment_status == PaymentStatus.PENDING
    assert payment.status == PaymentState.PAID
    assert payment.requires_review is True


def test_webhook_malformed_payload_is_rejected(client, paystack_enabled):
    raw = b"not-json"
    response = client.post(
        reverse("orders:paystack_webhook"),
        data=raw,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=_sign(raw, paystack_enabled.PAYSTACK_SECRET_KEY),
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Bank transfers
# ---------------------------------------------------------------------------


def _bank_account(finance_user) -> CompanyBankAccount:
    return payments.create_bank_account(
        actor=finance_user,
        bank_name="Zenith Bank",
        account_name="AA Shinaka Ltd",
        account_number="1012345678",
        currency="NGN",
    )


def test_record_bank_transfer_does_not_settle(customer, finance_user):
    order, listing = _place_order(customer)
    account = _bank_account(finance_user)

    submission = payments.record_bank_transfer(
        order,
        actor=customer,
        bank_account=account,
        transfer_reference="TRF-0001",
        claimed_amount=order.grand_total,
    )

    order.refresh_from_db()
    listing.refresh_from_db()
    payment = submission.payment
    assert submission.status == BankTransferStatus.SUBMITTED
    assert payment.status == PaymentState.PROCESSING
    assert order.payment_status == PaymentStatus.PENDING
    assert order.status == OrderStatus.PAYMENT_REVIEW
    assert listing.stock_on_hand == Decimal("20.000")
    assert not Receipt.objects.filter(payment=payment).exists()


def test_bank_transfer_approval_requires_settlement_confirmation(customer, finance_user):
    order, _ = _place_order(customer)
    account = _bank_account(finance_user)
    submission = payments.record_bank_transfer(
        order,
        actor=customer,
        bank_account=account,
        transfer_reference="TRF-0002",
        claimed_amount=order.grand_total,
    )

    with pytest.raises(ValidationError):
        payments.review_bank_transfer(
            submission, actor=finance_user, approve=True, settlement_confirmed=False
        )

    submission.refresh_from_db()
    assert submission.status == BankTransferStatus.SUBMITTED


def test_finance_approval_settles_bank_transfer_order(customer, finance_user):
    order, listing = _place_order(customer)
    account = _bank_account(finance_user)
    submission = payments.record_bank_transfer(
        order,
        actor=customer,
        bank_account=account,
        transfer_reference="TRF-0003",
        claimed_amount=order.grand_total,
    )

    payments.review_bank_transfer(
        submission,
        actor=finance_user,
        approve=True,
        settlement_confirmed=True,
        notes="Seen on statement",
    )

    order.refresh_from_db()
    listing.refresh_from_db()
    submission.refresh_from_db()
    assert submission.status == BankTransferStatus.APPROVED
    assert submission.reviewed_by == finance_user
    assert order.payment_status == PaymentStatus.PAID
    assert order.status == OrderStatus.CONFIRMED
    assert listing.stock_on_hand == Decimal("18.000")
    assert Receipt.objects.filter(payment=submission.payment).count() == 1


def test_customer_cannot_review_bank_transfer(customer, finance_user):
    order, _ = _place_order(customer)
    account = _bank_account(finance_user)
    submission = payments.record_bank_transfer(
        order,
        actor=customer,
        bank_account=account,
        transfer_reference="TRF-0004",
        claimed_amount=order.grand_total,
    )

    with pytest.raises(PermissionDenied):
        payments.review_bank_transfer(
            submission, actor=customer, approve=True, settlement_confirmed=True
        )


def test_one_transfer_reference_cannot_settle_two_orders(customer, finance_user):
    account = _bank_account(finance_user)
    order_a, _ = _place_order(customer)
    order_b, _ = _place_order(customer)

    first = payments.record_bank_transfer(
        order_a,
        actor=customer,
        bank_account=account,
        transfer_reference="TRF-DUP",
        claimed_amount=order_a.grand_total,
    )
    second = payments.record_bank_transfer(
        order_b,
        actor=customer,
        bank_account=account,
        transfer_reference="TRF-DUP",
        claimed_amount=order_b.grand_total,
    )

    payments.review_bank_transfer(
        first, actor=finance_user, approve=True, settlement_confirmed=True
    )

    with pytest.raises(ValidationError):
        payments.review_bank_transfer(
            second, actor=finance_user, approve=True, settlement_confirmed=True
        )

    order_b.refresh_from_db()
    assert order_b.payment_status == PaymentStatus.PENDING


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------


def test_refund_requires_finance_capability(customer, staff_user, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)
    payments.verify_payment(payment)

    with pytest.raises(PermissionDenied):
        payments.request_refund(payment, actor=staff_user, amount="10.00")


def test_refund_cannot_exceed_captured_funds(
    customer, finance_user, paystack_enabled, fake_paystack
):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)
    payments.verify_payment(payment)

    with pytest.raises(ValidationError):
        payments.request_refund(
            payment, actor=finance_user, amount=order.grand_total + Decimal("1.00")
        )

    assert payment.refunds.count() == 0


def test_partial_refund_marks_payment_partially_refunded(
    customer, finance_user, settings, paystack_enabled, fake_paystack
):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)
    payments.verify_payment(payment)

    # Force the offline path so no live Paystack refund call is attempted.
    settings.PAYSTACK_ENABLED = False
    refund = payments.request_refund(payment, actor=finance_user, amount="5000.00")
    payments.approve_refund(refund, actor=finance_user)
    refund = payments.complete_refund(refund)

    payment.refresh_from_db()
    order.refresh_from_db()
    assert refund.status == RefundState.COMPLETED
    assert payment.status == PaymentState.PARTIALLY_REFUNDED
    assert order.payment_status == "partially_refunded"


def test_full_refund_refunds_order(
    customer, finance_user, settings, paystack_enabled, fake_paystack
):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)
    payments.verify_payment(payment)

    settings.PAYSTACK_ENABLED = False
    refund = payments.request_refund(payment, actor=finance_user, amount=order.grand_total)
    payments.approve_refund(refund, actor=finance_user)
    payments.complete_refund(refund)

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == PaymentState.REFUNDED
    assert order.payment_status == "refunded"
    assert order.status == OrderStatus.REFUNDED


# ---------------------------------------------------------------------------
# Invoices & receipts
# ---------------------------------------------------------------------------


def test_invoice_is_issued_when_order_is_placed(customer):
    order, _ = _place_order(customer)

    invoice = order.invoice
    assert invoice.status == InvoiceState.UNPAID
    assert invoice.total == order.grand_total
    assert invoice.customer_email == customer.email
    assert invoice.issued_at is not None


def test_invoice_is_marked_paid_after_verified_payment(customer, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)

    payments.verify_payment(payment)

    order.invoice.refresh_from_db()
    assert order.invoice.status == InvoiceState.PAID


def test_issued_invoice_is_immutable(customer):
    order, _ = _place_order(customer)
    invoice = order.invoice

    invoice.total = Decimal("1.00")
    with pytest.raises(ValidationError):
        invoice.save()


def test_receipt_requires_verified_payment(customer):
    order, _ = _place_order(customer)
    payment = Payment.objects.create(
        order=order,
        customer=customer,
        reference="AS-PAY-MANUAL-1",
        provider=PaymentProvider.MANUAL,
        currency="NGN",
        expected_amount=order.grand_total,
        status=PaymentState.PENDING,
    )

    with pytest.raises(ValidationError):
        payments.issue_receipt(payment)


def test_invoice_pdf_is_valid_pdf(client, customer):
    order, _ = _place_order(customer)
    _login(client, customer)

    response = client.get(reverse("orders:invoice_pdf", args=[order.invoice.number]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-1.4")


def test_customer_cannot_open_another_customers_invoice(client, customer, other_customer):
    order, _ = _place_order(customer)
    _login(client, other_customer)

    response = client.get(reverse("orders:invoice_detail", args=[order.invoice.number]))

    assert response.status_code in {302, 403, 404}
    if response.status_code == 302:
        assert response.url == reverse("orders:invoice_list")


def test_customer_cannot_open_another_customers_payment(
    client, customer, other_customer, paystack_enabled, fake_paystack
):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    _login(client, other_customer)

    response = client.get(reverse("orders:payment_detail", args=[payment.pk]))

    assert response.status_code in (302, 403)
    assert selectors.payment_for_user(other_customer, payment.pk) is None


# ---------------------------------------------------------------------------
# Finance dashboard & metrics
# ---------------------------------------------------------------------------


def test_finance_dashboard_requires_finance_capability(client, staff_user):
    _login(client, staff_user)

    response = client.get(reverse("finance_dashboard:home"))

    assert response.status_code == 403


def test_finance_dashboard_renders_for_finance_officer(client, finance_user):
    _login(client, finance_user)

    response = client.get(reverse("finance_dashboard:home"))

    assert response.status_code == 200


def test_finance_overview_counts_only_verified_payments(customer, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    # A second order with only an open (unverified) payment.
    order2, _ = _place_order(customer)
    payments.initialize_payment(order2, actor=customer)

    fake_paystack["verify_payload"] = _verify_payload(order, payment)
    payments.verify_payment(payment)

    overview = selectors.finance_overview()
    assert overview["gross_revenue"] == order.grand_total
    assert overview["net_revenue"] == order.grand_total
    assert overview["payments_pending"] >= 1


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_reconcile_verifies_a_pending_payment(customer, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)

    result = payments.reconcile_payment(payment)

    assert result["action"] == "verified"
    order.refresh_from_db()
    assert order.payment_status == PaymentStatus.PAID


def test_reconcile_pending_payments_summary(customer, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)

    summary = payments.reconcile_pending_payments(older_than_minutes=0)

    assert summary["checked"] >= 1
    assert summary["verified"] >= 1


def test_documents_render_receipt_pdf(customer, paystack_enabled, fake_paystack):
    order, _ = _place_order(customer)
    payment = payments.initialize_payment(order, actor=customer)
    fake_paystack["verify_payload"] = _verify_payload(order, payment)
    payments.verify_payment(payment)

    receipt = payment.receipt
    assert documents.receipt_pdf(receipt).startswith(b"%PDF-1.4")

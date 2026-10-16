"""Phase 12 end-to-end tests (Scenarios A-F).

Each test walks a representative cross-module path with the real service layer
and, where it matters, the real HTTP views. Regression coverage for every edge
case lives in the per-phase test files; these prove the happy paths still join
up across modules before launch.

Payments never leave test mode: the Paystack HTTP boundary is monkeypatched and
the webhook secret is a test value. Money is always ``Decimal``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from catalog_helpers import make_category, make_product, make_sellable_product
from django.urls import reverse
from export_helpers import (
    make_destination,
    make_enquiry,
    make_export_order,
    make_export_product,
)
from orders_helpers import make_address, make_shipping
from services_helpers import issue_quotation, make_quotation, make_request
from training_helpers import make_course, make_session

from apps.accounts.models import UserRole
from apps.accounts.roles import sync_user_groups
from apps.analytics.models import ReportExport
from apps.orders import payments as order_payments
from apps.orders import paystack
from apps.orders.models import Order, OrderStatus, PaymentStatus
from apps.orders.payment_models import Payment, PaymentState
from apps.services import services as service_services
from apps.services.models import ServiceType
from apps.support import services as support_services
from apps.support.models import SupportStatus
from apps.training import payments as training_payments
from apps.training.models import Enrollment, EnrollmentPaymentStatus

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _e2e_media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def paystack_enabled(settings):
    settings.PAYSTACK_ENABLED = True
    settings.PAYSTACK_SECRET_KEY = "sk_test_e2e_1234567890"
    settings.PAYSTACK_WEBHOOK_SECRET = ""
    settings.PAYSTACK_CURRENCY = "NGN"
    return settings


@pytest.fixture
def fake_paystack(monkeypatch):
    """Patch the two Paystack round-trips; no network is ever used."""
    state: dict = {}

    def fake_initialize(**kwargs):
        state["initialize"] = kwargs
        return {
            "authorization_url": "https://checkout.paystack.test/e2e",
            "access_code": "acc_test_e2e",
            "reference": kwargs["reference"],
        }

    def fake_verify(reference):
        payload = dict(state.get("verify_payload") or {})
        payload.setdefault("reference", reference)
        payload.setdefault("status", "success")
        return payload

    monkeypatch.setattr(paystack, "initialize_transaction", fake_initialize)
    monkeypatch.setattr(paystack, "verify_transaction", fake_verify)
    return state


@pytest.fixture
def training_manager(db):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(
        email="trainer@example.com",
        password="test-pass-12345",
        first_name="Tobi",
        last_name="Adeyemi",
        role=UserRole.TRAINING_MANAGER,
        is_staff=True,
    )
    sync_user_groups(user)
    return user


def _login(client, user) -> None:
    assert client.login(email=user.email, password="test-pass-12345")


def _sign(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha512).hexdigest()


def _post_charge_success(client, order: Order, payment: Payment, secret: str, event_id: str):
    payload = {
        "event": "charge.success",
        "id": event_id,
        "data": {
            "id": 555000111,
            "reference": payment.reference,
            "status": "success",
            "amount": int((Decimal(str(order.grand_total)) * 100).to_integral_value()),
            "currency": order.currency,
            "channel": "card",
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    return client.post(
        reverse("orders:paystack_webhook"),
        data=raw,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=_sign(raw, secret),
    )


# ---------------------------------------------------------------------------
# Scenario A — browse -> cart -> checkout -> pay -> order confirmed
# ---------------------------------------------------------------------------


def test_scenario_a_product_purchase(client, customer, paystack_enabled, fake_paystack):
    _, listing = make_sellable_product(stock="20.000", price="25000.00")
    _, method, rate = make_shipping(listing.state, fee="1500.00", code="e2e-a")
    address = make_address(customer, state=listing.state)

    # 1. Browse the public catalogue detail page.
    assert (
        client.get(reverse("catalog:product_detail", args=[listing.product.slug])).status_code
        == 200
    )

    # 2. Login, add to cart, place the order at checkout.
    _login(client, customer)
    client.post(reverse("orders:cart_add", args=[listing.pk]), {"quantity": "2"})
    response = client.post(
        reverse("orders:checkout"),
        {
            "address": str(address.pk),
            "shipping_method": str(method.pk),
            "checkout_token": "e2e-a-token",
        },
    )

    order = Order.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("orders:order_detail", args=[order.number])
    # Totals are computed server-side and ignore any client-supplied price.
    assert order.grand_total == Decimal("50000.00") + Decimal("1500.00")

    # Pay: initialise at the provider, then settle through the signed webhook.
    payment = order_payments.initialize_payment(order, actor=customer)
    webhook = _post_charge_success(
        client, order, payment, paystack_enabled.PAYSTACK_SECRET_KEY, "evt_e2e_a"
    )
    assert webhook.status_code == 200

    order.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == PaymentState.PAID
    assert order.status == OrderStatus.CONFIRMED
    assert order.payment_status == PaymentStatus.PAID

    # The customer can re-open the paid order in the portal.
    assert client.get(reverse("orders:order_detail", args=[order.number])).status_code == 200


# ---------------------------------------------------------------------------
# Scenario B — consultancy request to issued quotation
# ---------------------------------------------------------------------------


def test_scenario_b_consultancy_request_to_quotation(client, customer, administrator):
    request_obj = make_request(customer, service_type=ServiceType.CONSULTANCY, description="Soil")

    service_services.review_service_request(request_obj, actor=administrator)
    quotation = make_quotation(customer, actor=administrator, service_request=request_obj)
    issue_quotation(quotation, actor=administrator)

    request_obj.refresh_from_db()
    # Reviewing moves it to under review; issuing the quotation advances it.
    assert request_obj.status == "quoted"

    _login(client, customer)
    assert (
        client.get(
            reverse("services:request_detail", kwargs={"reference": request_obj.reference})
        ).status_code
        == 200
    )
    assert client.get(reverse("services:quotation_list")).status_code == 200


# ---------------------------------------------------------------------------
# Scenario C — export enquiry, quotation and order
# ---------------------------------------------------------------------------


def test_scenario_c_export_enquiry_to_order(client, customer, administrator, owner):
    category = make_category(name="Export grains")
    product = make_product(category, name="Sesame seeds")
    destination = make_destination(actor=administrator)
    make_export_product(product, actor=administrator, destinations=[destination])

    enquiry = make_enquiry(customer, destination=destination, product=product, actor=customer)
    order = make_export_order(
        enquiry, actor=administrator, approver=owner, customer=customer, product=product
    )

    _login(client, customer)
    assert client.get(reverse("export:home")).status_code == 200
    assert client.get(reverse("export:order_detail", args=[order.reference])).status_code == 200


# ---------------------------------------------------------------------------
# Scenario D — training enrollment and payment
# ---------------------------------------------------------------------------


def test_scenario_d_training_enrollment(
    client, customer, training_manager, paystack_enabled, fake_paystack
):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="15000")

    # Browse the published course publicly.
    assert (
        client.get(reverse("training:course_detail", kwargs={"slug": course.slug})).status_code
        == 200
    )

    # Enroll through the public view.
    _login(client, customer)
    response = client.post(reverse("training:enroll", kwargs={"pk": session.pk}))
    assert response.status_code == 302

    enrollment = Enrollment.objects.get(student=customer, session=session)

    payment = order_payments.initialize_training_payment(
        enrollment, actor=customer, amount=enrollment.balance_due
    )
    training_payments.settle_training_payment(payment, source="e2e")

    enrollment.refresh_from_db()
    assert enrollment.payment_status == EnrollmentPaymentStatus.PAID

    assert client.get(reverse("training_account:enrollment_list")).status_code == 200
    assert (
        client.get(
            reverse(
                "training_account:enrollment_detail", kwargs={"reference": enrollment.reference}
            )
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# Scenario E — support ticket lifecycle
# ---------------------------------------------------------------------------


def test_scenario_e_support_ticket_lifecycle(client, customer, administrator):
    ticket = support_services.create_ticket(
        customer=customer, subject="Broken order", message="My delivery arrived damaged."
    )

    # Customer views the ticket and replies.
    _login(client, customer)
    assert (
        client.get(
            reverse("support:ticket_detail", kwargs={"reference": ticket.reference})
        ).status_code
        == 200
    )
    reply = client.post(
        reverse("support:ticket_reply", kwargs={"reference": ticket.reference}),
        {"message": "Here are more details."},
    )
    assert reply.status_code == 302

    # A support manager replies from the staff dashboard.
    _login(client, administrator)
    staff_reply = client.post(
        reverse("support_dashboard:ticket_reply", kwargs={"reference": ticket.reference}),
        {"message": "We are investigating.", "is_internal": ""},
    )
    assert staff_reply.status_code == 302

    ticket.refresh_from_db()
    assert ticket.status in {SupportStatus.IN_PROGRESS, SupportStatus.WAITING_FOR_CUSTOMER}

    # The customer closes the ticket.
    _login(client, customer)
    close = client.post(reverse("support:ticket_close", kwargs={"reference": ticket.reference}))
    assert close.status_code == 302


# ---------------------------------------------------------------------------
# Scenario F — analytics reporting
# ---------------------------------------------------------------------------


def test_scenario_f_manager_generates_and_downloads_report(client, administrator):
    _login(client, administrator)

    assert client.get(reverse("analytics:executive")).status_code == 200
    assert client.get(reverse("analytics:page", args=["sales"])).status_code == 200

    response = client.post(
        reverse("analytics:report_generate"),
        {"report": "inventory_stock", "format": "csv", "preset": "all_time"},
    )
    assert response.status_code == 302

    export = ReportExport.objects.get()
    download = client.get(reverse("analytics:report_download", args=[export.pk]))
    assert download.status_code == 200
    assert b"".join(download.streaming_content)

"""Phase 12 production security tests (checklist items 1-20).

These assert the *boundaries* that matter before launch: authentication
hardening, object-level authorization, the payment kill switch, storage privacy
and the production settings module. Regression coverage for the earlier phases
lives in their own files and is run together by ``pytest``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from django.urls import reverse

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.django_db


def _sign(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha512).hexdigest()


def _post_webhook(client, secret: str, payload: dict):
    raw = json.dumps(payload).encode("utf-8")
    return client.post(
        reverse("orders:paystack_webhook"),
        data=raw,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=_sign(raw, secret),
    )


# ---------------------------------------------------------------------------
# State-changing endpoints must not be reachable by GET (CSRF/CSRF-less DoS)
# ---------------------------------------------------------------------------


def test_staff_action_rejects_get(client, administrator):
    client.force_login(administrator)
    url = reverse("export_dashboard:destination_approve", args=[uuid.uuid4()])

    response = client.get(url)

    assert response.status_code == 405


def test_staff_action_requires_authentication(client):
    url = reverse("export_dashboard:destination_approve", args=[uuid.uuid4()])

    response = client.get(url)

    assert response.status_code == 302


def test_course_publish_rejects_get(client, administrator):
    client.force_login(administrator)
    url = reverse("training_dashboard:course_publish", args=[uuid.uuid4()])

    assert client.get(url).status_code == 405


# ---------------------------------------------------------------------------
# Payment boundary
# ---------------------------------------------------------------------------


def test_webhook_rejects_bad_signature(client, settings):
    settings.PAYSTACK_ENABLED = True
    settings.PAYSTACK_SECRET_KEY = "sk_test_security"

    raw = json.dumps({"event": "charge.success", "id": "evt_bad"}).encode()
    response = client.post(
        reverse("orders:paystack_webhook"),
        data=raw,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE="not-a-valid-signature",
    )

    assert response.status_code == 401


def test_webhook_honours_disabled_kill_switch(client, settings):
    """A validly-signed event must not be applied while Paystack is disabled."""
    from apps.orders.payment_models import PaymentWebhookEvent, WebhookEventStatus

    settings.PAYSTACK_ENABLED = False
    settings.PAYSTACK_SECRET_KEY = "sk_test_security"
    settings.PAYSTACK_WEBHOOK_SECRET = ""

    response = _post_webhook(
        client,
        settings.PAYSTACK_SECRET_KEY,
        {"event": "charge.success", "id": "evt_kill_switch", "data": {"reference": "nope"}},
    )

    assert response.status_code == 200
    event = PaymentWebhookEvent.objects.get(event_id="evt_kill_switch")
    assert event.status == WebhookEventStatus.IGNORED


def test_webhook_rejects_non_post(client):
    response = client.get(reverse("orders:paystack_webhook"))

    assert response.status_code == 405


# ---------------------------------------------------------------------------
# Authorization boundaries
# ---------------------------------------------------------------------------


def test_customer_cannot_access_finance_dashboard(client, customer):
    client.force_login(customer)

    response = client.get(reverse("finance_dashboard:home"))

    assert response.status_code in (302, 403, 404)


def test_customer_cannot_access_analytics(client, customer):
    client.force_login(customer)

    response = client.get(reverse("analytics:executive"))

    assert response.status_code == 403


def test_report_download_requires_login(client):
    url = reverse("analytics:report_download", args=[uuid.uuid4()])

    response = client.get(url)

    assert response.status_code == 302


def test_customer_cannot_access_staff_dashboard(client, customer):
    """The staff area is gated by capability, never by the frontend alone."""
    client.force_login(customer)

    response = client.get(reverse("dashboard:home"))

    assert response.status_code in (302, 403, 404)


def test_another_customer_cannot_open_my_order(client, customer):
    from catalog_helpers import make_sellable_product
    from orders_helpers import make_address, make_shipping

    from apps.accounts.models import User, UserRole
    from apps.accounts.roles import sync_user_groups
    from apps.orders import services as order_services
    from apps.orders.models import Cart

    _, listing = make_sellable_product(stock="5.000")
    _, method, _ = make_shipping(listing.state, code="sec-std", name="Security std")
    address = make_address(customer, state=listing.state)
    cart = Cart.objects.create(user=customer)
    order_services.add_to_cart(cart, listing=listing, quantity="1")
    order = order_services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token="sec-idor-token",
    )

    intruder = User.objects.create_user(
        email="intruder@example.com", password="test-pass-12345", role=UserRole.CUSTOMER
    )
    sync_user_groups(intruder)
    client.force_login(intruder)

    response = client.get(reverse("orders:order_detail", args=[order.number]))

    assert response.status_code in (302, 403, 404)


# ---------------------------------------------------------------------------
# Session / cookie policy
# ---------------------------------------------------------------------------


def test_csrf_cookie_is_httponly():
    from django.conf import settings

    assert settings.CSRF_COOKIE_HTTPONLY is True


def test_csrf_rejects_tokenless_post():
    from django.test import Client as TestClient

    csrf_client = TestClient(enforce_csrf_checks=True)
    response = csrf_client.post(reverse("accounts:login"), {"username": "x", "password": "y"})

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Production settings module
# ---------------------------------------------------------------------------

_PROD_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings.prod",
    "DJANGO_SECRET_KEY": "k" * 60,
    "DJANGO_ALLOWED_HOSTS": "example.com",
    "CSRF_TRUSTED_ORIGINS": "https://example.com",
    "CACHE_URL": "redis://localhost:6379/2",
    "DATABASE_URL": "postgres://u:p@localhost:5432/db",
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_HOST": "smtp.example.com",
}


def _run_manage(args, extra_env):
    env = {**os.environ, **extra_env}
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )


def test_production_settings_are_secure():
    result = _run_manage(["check", "--deploy", "--fail-level", "ERROR"], _PROD_ENV)

    assert result.returncode == 0, result.stdout + result.stderr


def test_production_settings_reject_short_secret():
    env = {**_PROD_ENV, "DJANGO_SECRET_KEY": "short"}

    result = _run_manage(["check"], env)

    assert result.returncode != 0


def test_production_settings_reject_locmem_cache():
    env = {**_PROD_ENV, "CACHE_URL": "locmem://"}
    result = _run_manage(["check"], env)

    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Storage privacy helpers
# ---------------------------------------------------------------------------


def test_unknown_document_kind_is_denied(customer):
    from apps.accounts.documents import service_file

    # An unknown kind is never resolvable to a file.
    assert service_file(customer, "totally-unknown", uuid.uuid4()) is None


# ---------------------------------------------------------------------------
# Inventory integrity
# ---------------------------------------------------------------------------


def test_paid_order_cancelled_via_status_transition_restocks(customer):
    from decimal import Decimal

    from catalog_helpers import make_sellable_product
    from orders_helpers import make_address, make_shipping

    from apps.orders import services as order_services
    from apps.orders.models import Cart, OrderStatus

    _, listing = make_sellable_product(stock="10.000", price="1000.00")
    _, method, _ = make_shipping(listing.state, code="restock-std", name="Restock std")
    address = make_address(customer, state=listing.state)
    cart = Cart.objects.create(user=customer)
    order_services.add_to_cart(cart, listing=listing, quantity="3")
    order = order_services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token="restock-token",
    )

    order_services.settle_order(order, actor=customer)
    listing.refresh_from_db()
    assert listing.stock_on_hand == Decimal("7.000")

    # Cancelling a paid order through the generic transition must return stock.
    order_services.transition_order(order, to_status=OrderStatus.CANCELLED, actor=customer)

    listing.refresh_from_db()
    assert listing.stock_on_hand == Decimal("10.000")


# ---------------------------------------------------------------------------
# Webhook robustness (idempotency, missing signature)
# ---------------------------------------------------------------------------


def test_webhook_missing_signature_is_rejected(client, settings):
    settings.PAYSTACK_ENABLED = True
    settings.PAYSTACK_SECRET_KEY = "sk_test_nosig"
    settings.PAYSTACK_WEBHOOK_SECRET = ""

    raw = json.dumps({"event": "charge.success", "id": "evt_nosig"}).encode()
    response = client.post(
        reverse("orders:paystack_webhook"), data=raw, content_type="application/json"
    )

    assert response.status_code == 401


def test_duplicate_webhook_event_is_recorded_once(client, customer, monkeypatch, settings):
    from decimal import Decimal

    from catalog_helpers import make_sellable_product
    from orders_helpers import make_address, make_shipping

    from apps.orders import payments as order_payments
    from apps.orders import paystack as paystack_module
    from apps.orders import services as order_services
    from apps.orders.models import Cart, PaymentStatus
    from apps.orders.payment_models import PaymentState, PaymentWebhookEvent

    settings.PAYSTACK_ENABLED = True
    settings.PAYSTACK_SECRET_KEY = "sk_test_dup"
    settings.PAYSTACK_WEBHOOK_SECRET = ""

    _, listing = make_sellable_product(stock="5.000", price="1000.00")
    _, method, _ = make_shipping(listing.state, code="dup-std", name="Dup std")
    address = make_address(customer, state=listing.state)
    cart = Cart.objects.create(user=customer)
    order_services.add_to_cart(cart, listing=listing, quantity="1")
    order = order_services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token="dup-token",
    )

    monkeypatch.setattr(
        paystack_module,
        "initialize_transaction",
        lambda **kwargs: {
            "authorization_url": "https://checkout.paystack.test/dup",
            "access_code": "acc_dup",
            "reference": kwargs["reference"],
        },
    )
    payment = order_payments.initialize_payment(order, actor=customer)

    def fake_verify(reference):
        return {
            "reference": reference,
            "status": "success",
            "amount": int((Decimal(str(order.grand_total)) * 100).to_integral_value()),
            "currency": order.currency,
            "channel": "card",
        }

    monkeypatch.setattr(paystack_module, "verify_transaction", fake_verify)

    event = {
        "event": "charge.success",
        "id": "evt_dup_1",
        "data": {
            "id": 990001,
            "reference": payment.reference,
            "status": "success",
            "amount": int((Decimal(str(order.grand_total)) * 100).to_integral_value()),
            "currency": order.currency,
            "channel": "card",
        },
    }

    first = _post_webhook(client, "sk_test_dup", event)
    second = _post_webhook(client, "sk_test_dup", event)

    # Both deliveries are acknowledged (so the provider stops retrying), but the
    # event is recorded exactly once, so its effect is applied at most once.
    assert first.status_code == 200
    assert second.status_code == 200
    assert PaymentWebhookEvent.objects.filter(event_id="evt_dup_1").count() == 1

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == PaymentState.PAID
    assert order.payment_status == PaymentStatus.PAID


# ---------------------------------------------------------------------------
# Production settings fail-fast (additional rejections)
# ---------------------------------------------------------------------------


def test_production_settings_reject_empty_allowed_hosts():
    env = {**_PROD_ENV, "DJANGO_ALLOWED_HOSTS": ""}
    result = _run_manage(["check"], env)

    assert result.returncode != 0


def test_production_settings_reject_non_https_csrf_origin():
    env = {**_PROD_ENV, "CSRF_TRUSTED_ORIGINS": "http://example.com"}
    result = _run_manage(["check"], env)

    assert result.returncode != 0


def test_production_settings_reject_console_email():
    env = {**_PROD_ENV, "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend"}
    result = _run_manage(["check"], env)

    assert result.returncode != 0

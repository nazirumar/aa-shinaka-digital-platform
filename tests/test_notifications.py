"""Phase 10 notification-centre tests (Tasks 4-8).

Covers idempotent emission, category muting, ownership isolation, read state,
safe redirect handling, real email delivery (only recorded once the backend
confirms it) and the inert SMS/WhatsApp channels.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

from apps.notifications import services
from apps.notifications.channels import (
    ChannelNotConfigured,
    SmsChannel,
    WhatsAppChannel,
    get_channel,
)
from apps.notifications.context_processors import unread_notifications
from apps.notifications.models import (
    Notification,
    NotificationCategory,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationPreference,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


def _emit(user, **overrides):
    payload = {
        "recipient": user,
        "category": NotificationCategory.ORDERS,
        "event": "test.event",
        "title": "Test notification",
        "message": "Something happened.",
    }
    payload.update(overrides)
    return services.emit(**payload)


# ---------------------------------------------------------------------------
# Emission & idempotency
# ---------------------------------------------------------------------------
def test_emit_creates_notification_and_in_app_delivery(customer):
    notification = _emit(customer, dedupe_key="emit-1")

    assert notification is not None
    assert Notification.objects.filter(recipient=customer, dedupe_key="emit-1").count() == 1
    delivery = NotificationDelivery.objects.get(notification=notification)
    assert delivery.channel == NotificationChannel.IN_APP
    assert delivery.status == NotificationDeliveryStatus.DELIVERED


def test_emit_is_idempotent_on_dedupe_key(customer):
    first = _emit(customer, dedupe_key="dup-key")
    second = _emit(customer, dedupe_key="dup-key")

    assert first.pk == second.pk
    assert Notification.objects.filter(recipient=customer).count() == 1


def test_emit_without_recipient_returns_none():
    assert _emit(None, dedupe_key="no-recipient") is None


def test_muted_category_is_not_stored(customer):
    services.update_preference(customer, categories={NotificationCategory.ORDERS: False})

    assert _emit(customer, dedupe_key="muted") is None
    assert Notification.objects.filter(recipient=customer).count() == 0


def test_unknown_absolute_url_is_discarded(customer):
    notification = _emit(
        customer,
        dedupe_key="unsafe",
        url="https://evil.example.com/steal",
    )

    assert notification.url == ""
    assert services.safe_url("https://evil.example.com") == ""
    assert services.safe_url("//evil.example.com") == ""
    assert services.safe_url("javascript:alert(1)") == ""
    assert services.safe_url("/account/orders/") == "/account/orders/"


# ---------------------------------------------------------------------------
# Read state
# ---------------------------------------------------------------------------
def test_mark_read_is_ownership_scoped(customer):
    other = User.objects.create_user(email="other@example.com", password="test-pass-12345")
    notification = _emit(customer, dedupe_key="read-1")

    assert services.mark_read(notification, user=other) is False
    notification.refresh_from_db()
    assert notification.is_read is False

    assert services.mark_read(notification, user=customer) is True
    notification.refresh_from_db()
    assert notification.is_read is True
    assert notification.read_at is not None


def test_unread_count_and_mark_all(customer):
    _emit(customer, dedupe_key="c-1")
    _emit(customer, dedupe_key="c-2")

    assert services.unread_count(customer) == 2
    assert services.mark_all_read(customer) == 2
    assert services.unread_count(customer) == 0


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------
def test_email_delivery_is_recorded_only_after_backend_confirms(customer, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.NOTIFICATION_EMAIL_ENABLED = True

    notification = _emit(customer, dedupe_key="mail-1", manage_email=True)
    delivery = NotificationDelivery.objects.get(
        notification=notification, channel=NotificationChannel.EMAIL
    )
    assert delivery.status == NotificationDeliveryStatus.PENDING

    assert services.deliver_pending_for(notification) == 1
    assert len(mail.outbox) == 1
    delivery.refresh_from_db()
    assert delivery.status == NotificationDeliveryStatus.DELIVERED
    assert delivery.attempt_count == 1


def test_email_channel_skipped_when_disabled(customer, settings):
    settings.NOTIFICATION_EMAIL_ENABLED = False

    notification = _emit(customer, dedupe_key="mail-2", manage_email=True)
    delivery = NotificationDelivery.objects.get(
        notification=notification, channel=NotificationChannel.EMAIL
    )
    assert delivery.status == NotificationDeliveryStatus.SKIPPED


def test_sms_and_whatsapp_are_inert_until_configured():
    assert SmsChannel().is_configured() is False
    assert WhatsAppChannel().is_configured() is False
    with pytest.raises(ChannelNotConfigured):
        SmsChannel().send(object())
    with pytest.raises(ChannelNotConfigured):
        WhatsAppChannel().send(object())


def test_failed_delivery_is_never_silently_dropped(customer):
    notification = _emit(customer, dedupe_key="fail-1")
    delivery = NotificationDelivery.objects.create(
        notification=notification,
        channel=NotificationChannel.SMS,
        status=NotificationDeliveryStatus.PENDING,
    )

    assert services.deliver_delivery(delivery.pk, max_attempts=1) is False
    delivery.refresh_from_db()
    assert delivery.status == NotificationDeliveryStatus.FAILED
    assert delivery.error_detail


def test_get_channel_returns_singleton_adapters():
    assert get_channel(NotificationChannel.IN_APP) is get_channel(NotificationChannel.IN_APP)


# ---------------------------------------------------------------------------
# Context processor & preferences
# ---------------------------------------------------------------------------
def test_context_processor_exposes_unread_count(customer):
    _emit(customer, dedupe_key="ctx-1")

    request = type("Request", (), {"user": customer})()
    assert unread_notifications(request)["unread_notifications_count"] == 1

    anonymous = type("Request", (), {"user": type("Anon", (), {"is_authenticated": False})()})()
    assert unread_notifications(anonymous)["unread_notifications_count"] == 0


def test_preferences_post_persists_categories(client, customer):
    client.force_login(customer)

    response = client.post(
        reverse("notifications:preferences"),
        {"in_app_enabled": "on", "email_enabled": "on", "category_orders": "on"},
    )

    assert response.status_code == 302
    preference = NotificationPreference.objects.get(user=customer)
    assert preference.in_app_enabled is True
    assert preference.categories["orders"] is True
    assert preference.categories["support"] is False


# ---------------------------------------------------------------------------
# Views: login + ownership isolation
# ---------------------------------------------------------------------------
def test_center_requires_login(client):
    response = client.get(reverse("notifications:center"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_center_lists_only_the_signed_in_customers_notifications(client, customer):
    other = User.objects.create_user(email="other2@example.com", password="test-pass-12345")
    _emit(other, dedupe_key="o-1", title="Other secret", message="not yours")
    _emit(customer, dedupe_key="m-1", title="My notification", message="mine")

    client.force_login(customer)
    response = client.get(reverse("notifications:center"))

    assert response.status_code == 200
    assert b"My notification" in response.content
    assert b"Other secret" not in response.content


def test_cannot_mark_another_customers_notification_read(client, customer):
    other = User.objects.create_user(email="other3@example.com", password="test-pass-12345")
    notification = _emit(other, dedupe_key="o-2")

    client.force_login(customer)
    response = client.post(reverse("notifications:mark_read", args=[notification.pk]))

    assert response.status_code == 404
    notification.refresh_from_db()
    assert notification.is_read is False


# ---------------------------------------------------------------------------
# Domain integration: placing a real order mirrors into the in-app feed
# ---------------------------------------------------------------------------
def test_placing_an_order_creates_an_in_app_notification(customer, settings, tmp_path):
    from catalog_helpers import make_sellable_product
    from orders_helpers import make_address, make_shipping

    from apps.orders import services
    from apps.orders.models import Cart

    settings.MEDIA_ROOT = tmp_path
    _, listing = make_sellable_product(stock="20.000", price="25000.00")
    _, method, _ = make_shipping(listing.state, fee="1500.00")
    address = make_address(customer, state=listing.state)
    cart = Cart.objects.create(user=customer)
    services.add_to_cart(cart, listing=listing, quantity="2")

    order = services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token="tok-notify",
    )

    assert (
        Notification.objects.filter(
            recipient=customer, event="order.created", dedupe_key=f"order-created:{order.pk}"
        ).count()
        == 1
    )

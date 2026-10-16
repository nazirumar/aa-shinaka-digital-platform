"""Phase 10 support-centre tests (Tasks 9-12).

Covers the ticket lifecycle, server-side ownership checks on linked records,
the status state machine, reopen window, internal-note visibility, the staff
reply notification and capability gating of the staff dashboard.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.notifications.models import Notification, NotificationCategory
from apps.orders.models import Order
from apps.support import services
from apps.support.models import (
    SupportMessage,
    SupportRelatedType,
    SupportStatus,
    SupportStatusHistory,
    SupportTicket,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


def make_ticket(customer, **overrides):
    payload = {"customer": customer, "subject": "Broken order", "message": "Please help"}
    payload.update(overrides)
    return services.create_ticket(**payload)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
def test_create_ticket_records_history_and_opener(customer):
    ticket = make_ticket(customer)

    assert ticket.status == SupportStatus.OPEN
    assert ticket.reference.startswith("AS-ST")
    assert SupportMessage.objects.filter(ticket=ticket, sender=customer).count() == 1
    assert SupportStatusHistory.objects.filter(ticket=ticket).count() == 1


def test_ticket_requires_subject_and_message(customer):
    with pytest.raises(ValidationError):
        services.create_ticket(customer=customer, subject="   ", message="hi")
    with pytest.raises(ValidationError):
        services.create_ticket(customer=customer, subject="ok", message="")


def test_linked_record_must_belong_to_the_customer(customer):
    other = User.objects.create_user(email="other@example.com", password="test-pass-12345")
    Order.objects.create(number="AS-9001", user=other)

    with pytest.raises(ValidationError):
        make_ticket(
            customer,
            related_type=SupportRelatedType.PRODUCT_ORDER,
            related_id="AS-0001",
        )


def test_customer_can_link_their_own_order(customer):
    Order.objects.create(number="AS-0002", user=customer)

    ticket = make_ticket(
        customer,
        related_type=SupportRelatedType.PRODUCT_ORDER,
        related_id="AS-0002",
    )

    assert ticket.related_type == SupportRelatedType.PRODUCT_ORDER
    assert ticket.related_id == "AS-0002"


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
def test_state_machine_rejects_invalid_transition(customer):
    ticket = make_ticket(customer)

    with pytest.raises(ValidationError):
        services.change_status(ticket, new_status=SupportStatus.REOPENED, actor=customer)


def test_staff_reply_moves_ticket_to_waiting_and_notifies(customer, staff_user):
    ticket = make_ticket(customer)

    services.add_staff_message(ticket, sender=staff_user, message="Looking into it")

    ticket.refresh_from_db()
    assert ticket.status == SupportStatus.WAITING_FOR_CUSTOMER
    assert (
        Notification.objects.filter(
            recipient=customer, category=NotificationCategory.SUPPORT
        ).count()
        == 1
    )


def test_internal_note_is_not_visible_to_customer_and_does_not_notify(customer, staff_user):
    ticket = make_ticket(customer)
    services.add_staff_message(
        ticket, sender=staff_user, message="Internal only note", is_internal=True
    )

    assert (
        Notification.objects.filter(
            recipient=customer, category=NotificationCategory.SUPPORT
        ).count()
        == 0
    )
    # The customer-scoped selector hides internal notes.
    from apps.support import selectors

    visible = selectors.messages_for(ticket, include_internal=False)
    assert visible.filter(is_internal=True).count() == 0


def test_customer_reply_moves_ticket_back_into_progress(customer, staff_user):
    ticket = make_ticket(customer)
    services.add_staff_message(ticket, sender=staff_user, message="Any update?")
    ticket.refresh_from_db()
    assert ticket.status == SupportStatus.WAITING_FOR_CUSTOMER

    services.add_customer_message(ticket, sender=customer, message="Here is the detail")

    ticket.refresh_from_db()
    assert ticket.status == SupportStatus.IN_PROGRESS


def test_state_machine_rejects_unknown_transition_server_side(customer):
    ticket = make_ticket(customer)
    with pytest.raises(ValidationError):
        services.change_status(ticket, new_status=SupportStatus.REOPENED, actor=customer)


def test_reopen_within_window(customer):
    ticket = make_ticket(customer)
    services.change_status(ticket, new_status=SupportStatus.RESOLVED, actor=customer)

    services.reopen_ticket(ticket, actor=customer)

    ticket.refresh_from_db()
    assert ticket.status == SupportStatus.REOPENED


def test_reopen_beyond_window_is_rejected(customer):
    from datetime import timedelta

    from django.utils import timezone

    ticket = make_ticket(customer)
    services.change_status(ticket, new_status=SupportStatus.RESOLVED, actor=customer)
    SupportTicket.objects.filter(pk=ticket.pk).update(
        resolved_at=timezone.now() - timedelta(days=60)
    )
    ticket.refresh_from_db()

    with pytest.raises(ValidationError):
        services.reopen_ticket(ticket, actor=customer)


# ---------------------------------------------------------------------------
# Views: ownership isolation
# ---------------------------------------------------------------------------
def test_ticket_pages_require_login(client):
    response = client.get(reverse("support:home"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_cannot_view_another_customers_ticket(client, customer):
    other = User.objects.create_user(email="other2@example.com", password="test-pass-12345")
    ticket = make_ticket(other, subject="Private issue")

    client.force_login(customer)
    response = client.get(reverse("support:ticket_detail", args=[ticket.reference]))

    assert response.status_code == 404


def test_customer_cannot_download_another_customers_attachment(client, customer):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.support.models import SupportAttachment

    other = User.objects.create_user(email="other3@example.com", password="test-pass-12345")
    ticket = make_ticket(other)
    attachment = SupportAttachment.objects.create(
        ticket=ticket,
        file=SimpleUploadedFile("note.txt", b"secret"),
        original_filename="note.txt",
    )

    client.force_login(customer)
    response = client.get(reverse("support:attachment_download", args=[attachment.pk]))

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Staff dashboard capability gating
# ---------------------------------------------------------------------------
def test_staff_dashboard_denies_non_support_staff(client, customer):
    client.force_login(customer)
    assert client.get(reverse("support_dashboard:home")).status_code == 403


def test_sales_officer_can_use_support_queue(client, staff_user):
    client.force_login(staff_user)
    response = client.get(reverse("support_dashboard:home"))
    assert response.status_code == 200


def test_priority_change_requires_approve_capability(client, customer, staff_user, administrator):
    ticket = make_ticket(customer)

    client.force_login(staff_user)  # SUPPORT_MANAGE only
    response = client.post(
        reverse("support_dashboard:ticket_priority", args=[ticket.reference]),
        {"priority": "urgent"},
    )
    assert response.status_code == 403
    ticket.refresh_from_db()
    assert ticket.priority == "normal"

    client.force_login(administrator)  # SUPPORT_APPROVE via ALL
    response = client.post(
        reverse("support_dashboard:ticket_priority", args=[ticket.reference]),
        {"priority": "urgent"},
    )
    assert response.status_code == 302
    ticket.refresh_from_db()
    assert ticket.priority == "urgent"

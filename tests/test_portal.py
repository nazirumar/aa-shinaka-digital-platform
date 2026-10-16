"""Phase 10 unified customer-portal tests (Tasks 1-3, 13-16).

Covers the document centre (ownership-scoped central download), the aggregated
activity timeline and the capability-gated staff customer overview.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.orders.models import Order
from apps.services.models import ServiceAttachment, ServiceRequest, ServiceType

User = get_user_model()
pytestmark = pytest.mark.django_db


def _service_request(customer, title="Consultancy request"):
    return ServiceRequest.objects.create(
        customer=customer, service_type=ServiceType.CONSULTANCY, title=title
    )


# ---------------------------------------------------------------------------
# Documents centre
# ---------------------------------------------------------------------------
def test_document_pages_require_login(client):
    for name in ("account:documents", "account:activity"):
        response = client.get(reverse(name))
        assert response.status_code == 302
        assert reverse("accounts:login") in response.url


def test_documents_lists_only_owned_files(client, customer, media_root):
    from django.core.files.uploadedfile import SimpleUploadedFile as Upload

    other = User.objects.create_user(email="other@example.com", password="test-pass-12345")
    mine = ServiceAttachment.objects.create(
        request=_service_request(customer),
        file=Upload("mine.txt", b"mine"),
        label="My soil report",
    )
    theirs = ServiceAttachment.objects.create(
        request=_service_request(other),
        file=Upload("theirs.txt", b"theirs"),
        label="Their private report",
    )

    client.force_login(customer)
    response = client.get(reverse("account:documents"))

    assert response.status_code == 200
    assert b"My soil report" in response.content
    assert b"Their private report" not in response.content
    assert mine.pk != theirs.pk


def test_document_download_is_ownership_scoped(client, customer, media_root):
    other = User.objects.create_user(email="other2@example.com", password="test-pass-12345")
    attachment = ServiceAttachment.objects.create(
        request=_service_request(other),
        file=SimpleUploadedFile("report.txt", b"secret data"),
        label="Report",
    )

    client.force_login(customer)
    response = client.get(
        reverse("account:document_download", args=["service-attachment", attachment.pk])
    )
    assert response.status_code == 404

    client.force_login(other)
    response = client.get(
        reverse("account:document_download", args=["service-attachment", attachment.pk])
    )
    assert response.status_code == 200


def test_unknown_document_kind_is_not_found(client, customer):
    client.force_login(customer)
    response = client.get(reverse("account:document_download", args=["not-a-kind", "1"]))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Activity timeline
# ---------------------------------------------------------------------------
def test_activity_timeline_is_ownership_scoped(client, customer):
    other = User.objects.create_user(email="other3@example.com", password="test-pass-12345")
    Order.objects.create(number="AS-MINE", user=customer)
    Order.objects.create(number="AS-THEIRS", user=other)

    client.force_login(customer)
    response = client.get(reverse("account:activity"))

    assert response.status_code == 200
    assert b"AS-MINE" in response.content
    assert b"AS-THEIRS" not in response.content


def test_dashboard_metrics_render_for_customer(client, customer):
    client.force_login(customer)
    response = client.get(reverse("account:dashboard"))

    assert response.status_code == 200
    assert b"Your activity at a glance" in response.content


# ---------------------------------------------------------------------------
# Staff customer overview
# ---------------------------------------------------------------------------
def test_customer_overview_requires_capability(client, customer):
    client.force_login(customer)
    assert client.get(reverse("customers_dashboard:list")).status_code == 403


def test_customer_overview_lists_customers(client, staff_user, customer):
    client.force_login(staff_user)
    response = client.get(reverse("customers_dashboard:list"))

    assert response.status_code == 200
    assert customer.email.encode() in response.content


def test_customer_overview_finance_section_is_gated(client, customer, staff_user, administrator):
    client.force_login(staff_user)  # CUSTOMERS_VIEW but not FINANCE_MANAGE
    response = client.get(reverse("customers_dashboard:detail", args=[customer.pk]))
    assert response.status_code == 200
    assert b"Payments (finance)" not in response.content

    client.force_login(administrator)  # has FINANCE_MANAGE
    response = client.get(reverse("customers_dashboard:detail", args=[customer.pk]))
    assert b"Payments (finance)" in response.content

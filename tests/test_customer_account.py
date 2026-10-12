"""Customer profile and address tests (checklist items 11-12)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import Address

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_account_pages_require_login(client):
    for url_name in (
        "account:dashboard",
        "account:profile",
        "account:addresses",
        "account:security",
    ):
        response = client.get(reverse(url_name))
        assert response.status_code == 302
        assert reverse("accounts:login") in response.url


def test_dashboard_renders_for_customer(client, customer):
    client.force_login(customer)

    response = client.get(reverse("account:dashboard"))

    assert response.status_code == 200
    assert b"Welcome back" in response.content


def test_profile_edit(client, customer, state):
    client.force_login(customer)

    response = client.post(
        reverse("account:profile"),
        {
            "first_name": "Chioma",
            "last_name": "Okafor-Eze",
            "phone": "08099999999",
            "state": state.pk,
            "marketing_opt_in": "on",
        },
    )

    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.last_name == "Okafor-Eze"
    assert customer.phone == "08099999999"
    assert customer.marketing_opt_in is True


def _address_payload(state, lga, **overrides):
    payload = {
        "label": "Home",
        "recipient_name": "Chioma Okafor",
        "phone": "08030000000",
        "state": state.pk,
        "lga": lga.pk,
        "city": "Zaria",
        "street_address": "12 Market Road",
        "landmark": "Near central mosque",
        "postal_code": "810001",
    }
    payload.update(overrides)
    return payload


def test_create_address_is_default_when_first(client, customer, state, lga):
    client.force_login(customer)

    response = client.post(reverse("account:address_add"), _address_payload(state, lga))

    assert response.status_code == 302
    address = Address.objects.get(user=customer)
    assert address.is_default is True
    assert address.lga == lga


def test_lga_must_belong_to_state(client, customer, state, lga):
    from apps.core.models import LGA, State
    from apps.locations.models import Country

    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria"})
    other_state = State.objects.create(name="Lagos", code="LA", zone="SW", country=ng)
    client.force_login(customer)

    response = client.post(
        reverse("account:address_add"),
        _address_payload(other_state, lga),
    )

    assert response.status_code == 200
    assert not Address.objects.filter(user=customer).exists()
    assert LGA.objects.filter(state=other_state).count() == 0


def test_set_default_address(client, customer, state, lga):
    client.force_login(customer)
    first = Address.objects.create(
        user=customer,
        recipient_name="A",
        phone="1",
        state=state,
        lga=lga,
        city="Zaria",
        street_address="1",
        is_default=True,
    )
    second = Address.objects.create(
        user=customer,
        recipient_name="B",
        phone="2",
        state=state,
        lga=lga,
        city="Zaria",
        street_address="2",
    )

    client.post(reverse("account:address_default", args=[second.pk]))

    first.refresh_from_db()
    second.refresh_from_db()
    assert second.is_default is True
    assert first.is_default is False


def test_delete_address(client, customer, state, lga):
    client.force_login(customer)
    address = Address.objects.create(
        user=customer,
        recipient_name="A",
        phone="1",
        state=state,
        lga=lga,
        city="Zaria",
        street_address="1",
    )

    client.post(reverse("account:address_delete", args=[address.pk]))

    assert not Address.objects.filter(pk=address.pk).exists()


def test_cannot_access_another_customers_address(client, customer, state, lga):
    other = User.objects.create_user(email="other@example.com", password="test-pass-12345")
    address = Address.objects.create(
        user=other,
        recipient_name="Other",
        phone="1",
        state=state,
        lga=lga,
        city="Zaria",
        street_address="1",
    )
    client.force_login(customer)

    assert client.get(reverse("account:address_edit", args=[address.pk])).status_code == 404
    assert client.post(reverse("account:address_delete", args=[address.pk])).status_code == 404
    assert client.post(reverse("account:address_default", args=[address.pk])).status_code == 404
    assert Address.objects.filter(pk=address.pk).exists()


def test_duplicate_default_address_is_prevented(client, customer, state, lga):
    client.force_login(customer)
    client.post(reverse("account:address_add"), _address_payload(state, lga))

    # Second address without is_default should not become default.
    client.post(
        reverse("account:address_add"),
        _address_payload(state, lga, label="Office", street_address="9 Office Way"),
    )

    assert Address.objects.filter(user=customer, is_default=True).count() == 1
    assert Address.objects.filter(user=customer).count() == 2

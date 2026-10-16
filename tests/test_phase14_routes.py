"""Phase 14 — route inventory / no-server-error crawl.

A representative crawl across the public site, the customer portal and the staff
dashboard. It asserts that every listed route resolves without a server error
(5xx), and that the key public pages and the two portal home pages return 200.
Detailed behaviour for each workflow is covered by the per-phase suites; this
test is the consolidated "is every entry point wired up?" check used during
staging verification.

Paths are literal (not ``reverse``) so the test also catches accidental template
or URL regressions at the exact URLs documented in ``README.md``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

PUBLIC_OK = [
    "/",
    "/about/",
    "/contact/",
    "/services/",
    "/news/",
    "/faqs/",
    "/shop/",
    "/training/",
    "/cart/",
    "/accounts/register/",
    "/accounts/password-reset/",
    "/robots.txt",
    "/sitemap.xml",
    "/healthz/",
    "/states/",
]

CUSTOMER_PAGES = [
    "/account/",
    "/account/profile/",
    "/account/addresses/",
    "/account/security/",
    "/account/notifications/",
    "/account/support/",
    "/account/services/",
    "/account/export/",
    "/account/training/",
    "/orders/",
    "/payments/",
    "/quotations/",
]

STAFF_PAGES = [
    "/dashboard/",
    "/dashboard/audit/",
    "/dashboard/staff/",
    "/dashboard/services/",
    "/dashboard/orders/",
    "/dashboard/inventory/",
    "/dashboard/finance/",
    "/dashboard/catalog/",
    "/dashboard/export/",
    "/dashboard/training/",
    "/dashboard/support/",
    "/dashboard/customers/",
    "/dashboard/executive/",
    "/dashboard/analytics/",
    "/dashboard/reports/",
    "/dashboard/security/uploads/",
]


@pytest.mark.parametrize("path", PUBLIC_OK)
def test_public_pages_ok(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", CUSTOMER_PAGES)
def test_customer_pages_no_server_error(client, customer, path):
    client.force_login(customer)
    response = client.get(path)
    assert response.status_code < 500, f"{path} returned {response.status_code}"
    # A logged-in customer must never be bounced to the login page on their own
    # portal pages.
    assert response.status_code != 302, f"{path} unexpectedly redirected"


@pytest.mark.parametrize("path", STAFF_PAGES)
def test_staff_pages_no_server_error(client, owner, path):
    client.force_login(owner)
    response = client.get(path)
    assert response.status_code < 500, f"{path} returned {response.status_code}"
    assert response.status_code != 302, f"{path} unexpectedly redirected"


def test_customer_dashboard_is_200(client, customer):
    client.force_login(customer)
    assert client.get("/account/").status_code == 200


def test_staff_dashboard_is_200(client, owner):
    client.force_login(owner)
    assert client.get("/dashboard/").status_code == 200


def test_anonymous_cannot_open_staff_dashboard(client):
    response = client.get("/dashboard/")
    assert response.status_code in (302, 403)


def test_public_registration_only_creates_customer(client):
    """Guard against a regression that lets public signup become staff."""
    response = client.post(
        "/accounts/register/",
        {
            "email": "route-check@example.com",
            "first_name": "Route",
            "last_name": "Check",
            "phone": "08000000000",
            "password1": "very-secret-pass-42",
            "password2": "very-secret-pass-42",
            "accept_terms": "on",
        },
    )
    assert response.status_code == 302
    from apps.accounts.models import User, UserRole

    user = User.objects.get(email="route-check@example.com")
    assert user.role == UserRole.CUSTOMER
    assert user.is_staff is False

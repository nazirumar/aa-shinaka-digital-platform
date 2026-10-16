"""Phase 11 tests: analytics dashboards, report builder, exports and scheduling.

Analytics never writes to a business table, so arrangements may create records
directly; the behaviour under test (report generation, scheduling, delivery,
retention) goes through ``apps.analytics.services``. Money is always ``Decimal``
and currencies are never combined.
"""

from __future__ import annotations

import io
import itertools
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest
from catalog_helpers import make_sellable_product
from django.core import management
from django.urls import reverse
from django.utils import timezone
from orders_helpers import make_address, make_shipping

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.analytics import charts, data_quality, exports, reports, selectors, services
from apps.analytics.filters import ReportFilters
from apps.analytics.models import (
    DeliveryStatus,
    ExecutionStatus,
    ReportDelivery,
    ReportExecution,
    ReportExport,
    ScheduledReport,
)
from apps.dashboard.models import AuditLog
from apps.orders import services as order_services
from apps.orders.models import Cart
from apps.orders.payment_models import Payment, PaymentMethod, PaymentProvider, PaymentState

pytestmark = pytest.mark.django_db

_seq = itertools.count(1)


@pytest.fixture(autouse=True)
def _analytics_env(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


def _make_user(role, email, *, is_staff=True) -> User:
    user = User.objects.create_user(
        email=email,
        password="test-pass-12345",
        first_name="Test",
        last_name="User",
        role=role,
        is_staff=is_staff,
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def customer(db) -> User:
    return _make_user(UserRole.CUSTOMER, "an-customer@example.com", is_staff=False)


@pytest.fixture
def consultant(db) -> User:
    return _make_user(UserRole.CONSULTANT, "an-consultant@example.com")


@pytest.fixture
def sales_officer(db) -> User:
    return _make_user(UserRole.SALES_OFFICER, "an-sales@example.com")


@pytest.fixture
def finance_officer(db) -> User:
    return _make_user(UserRole.FINANCE_OFFICER, "an-finance@example.com")


@pytest.fixture
def content_editor(db) -> User:
    return _make_user(UserRole.CONTENT_EDITOR, "an-editor@example.com")


def _paid_order(customer, *, currency="NGN", amount="1000.00", verified=True):
    seq = next(_seq)
    _, listing = make_sellable_product(name=f"AnMaize {seq}", price="1000.00", stock="50.000")
    _, method, _ = make_shipping(listing.state, name=f"Std {seq}", code=f"an-std-{seq}")
    address = make_address(customer, state=listing.state)
    cart = Cart.objects.create(user=customer)
    order_services.add_to_cart(cart, listing=listing, quantity="1")
    order = order_services.place_order(
        user=customer,
        cart=cart,
        address=address,
        shipping_method=method,
        checkout_token=f"an-tok-{seq}",
    )
    payment = Payment.objects.create(
        order=order,
        customer=customer,
        reference=f"an-ref-{seq}",
        provider=PaymentProvider.MANUAL,
        method=PaymentMethod.BANK,
        currency=currency,
        expected_amount=Decimal(amount),
        verified_amount=Decimal(amount) if verified else None,
        status=PaymentState.PAID,
        verified_at=timezone.now() if verified else None,
    )
    return order, payment


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_dashboard_requires_login(client):
    response = client.get(reverse("analytics:executive"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_customer_is_forbidden(client, customer):
    assert client.login(email=customer.email, password="test-pass-12345")

    assert client.get(reverse("analytics:executive")).status_code == 403


def test_consultant_can_view_executive(client, consultant):
    assert client.login(email=consultant.email, password="test-pass-12345")

    assert client.get(reverse("analytics:executive")).status_code == 200


def test_consultant_cannot_view_finance_page(client, consultant):
    assert client.login(email=consultant.email, password="test-pass-12345")

    assert client.get(reverse("analytics:page", args=["finance"])).status_code == 403


def test_finance_officer_can_view_finance_page(client, finance_officer):
    assert client.login(email=finance_officer.email, password="test-pass-12345")

    assert client.get(reverse("analytics:page", args=["finance"])).status_code == 200


def test_consultant_cannot_access_builder(client, consultant):
    assert client.login(email=consultant.email, password="test-pass-12345")

    assert client.get(reverse("analytics:report_builder")).status_code == 403


def test_sales_officer_can_access_builder(client, sales_officer):
    assert client.login(email=sales_officer.email, password="test-pass-12345")

    assert client.get(reverse("analytics:report_builder")).status_code == 200


def test_sales_officer_cannot_schedule(client, sales_officer):
    assert client.login(email=sales_officer.email, password="test-pass-12345")

    assert client.get(reverse("analytics:scheduled_list")).status_code == 403


def test_finance_officer_can_schedule(client, finance_officer):
    assert client.login(email=finance_officer.email, password="test-pass-12345")

    assert client.get(reverse("analytics:scheduled_list")).status_code == 200


def test_unknown_page_is_404(client, sales_officer):
    assert client.login(email=sales_officer.email, password="test-pass-12345")

    assert client.get(reverse("analytics:page", args=["nonsense"])).status_code == 404


@pytest.mark.parametrize(
    "page",
    ["sales", "finance", "inventory", "services", "export", "training", "customers", "support"],
)
def test_every_page_renders_for_administrator(client, administrator, page):
    assert client.login(email=administrator.email, password="test-pass-12345")

    response = client.get(reverse("analytics:page", args=[page]))

    assert response.status_code == 200
    assert response.context["page"] == page


def test_data_quality_page_renders(client, sales_officer):
    assert client.login(email=sales_officer.email, password="test-pass-12345")

    response = client.get(reverse("analytics:data_quality"))

    assert response.status_code == 200
    assert response.context["summary"]["check_count"] >= 1


def test_api_endpoint_returns_json(client, sales_officer):
    assert client.login(email=sales_officer.email, password="test-pass-12345")

    response = client.get(reverse("analytics:api", args=["sales"]))

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == "sales"
    assert "kpis" in payload and "charts" in payload


# ---------------------------------------------------------------------------
# Selectors: money is per-currency and never combined
# ---------------------------------------------------------------------------


def test_receipts_are_grouped_per_currency(customer):
    _paid_order(customer, currency="NGN", amount="1000.00")
    _paid_order(customer, currency="USD", amount="2000.00")

    rows = selectors.receipts_by_currency()

    assert {row["currency"]: row["total"] for row in rows} == {
        "NGN": Decimal("1000.00"),
        "USD": Decimal("2000.00"),
    }


def test_verified_receipts_is_single_currency(customer):
    _paid_order(customer, currency="NGN", amount="1000.00")
    _paid_order(customer, currency="USD", amount="2000.00")

    assert selectors.verified_receipts(currency="NGN") == Decimal("1000.00")
    assert selectors.verified_receipts(currency="USD") == Decimal("2000.00")


def test_unverified_payment_is_not_a_receipt(customer):
    _paid_order(customer, currency="NGN", amount="500.00", verified=False)

    assert selectors.verified_receipts(currency="NGN") == Decimal("0.00")


def test_confirmed_refunds_reduce_only_the_matching_currency(customer):
    _, payment = _paid_order(customer, currency="NGN", amount="1000.00")
    from apps.orders.payment_models import Refund, RefundState

    Refund.objects.create(
        payment=payment,
        reference="an-refund-1",
        amount=Decimal("250.00"),
        status=RefundState.COMPLETED,
        processed_at=timezone.now(),
    )

    assert selectors.confirmed_refunds(currency="NGN") == Decimal("250.00")
    assert selectors.confirmed_refunds(currency="USD") == Decimal("0.00")


def test_charts_payloads_are_json_safe(sales_officer):
    payload = charts.sales_charts(filters=ReportFilters(preset="all_time"))

    assert "trend" in payload and "status" in payload
    for chart in payload.values():
        assert set(chart) >= {"type", "labels", "datasets", "empty"}


# ---------------------------------------------------------------------------
# Report registry and builder
# ---------------------------------------------------------------------------


def test_get_report_unknown_key_returns_none():
    assert reports.get_report("does-not-exist") is None


def test_available_reports_hides_finance_without_capability():
    keys = {d.key for d in reports.available_reports({"analytics.view", "reports.build"})}

    assert "inventory_stock" in keys
    assert "finance_receipts" not in keys


def test_available_reports_includes_finance_with_capability():
    keys = {d.key for d in reports.available_reports({"analytics.finance", "reports.build"})}

    assert "finance_receipts" in keys


def test_builder_rejects_report_outside_capabilities(client, consultant, sales_officer):
    assert client.login(email=sales_officer.email, password="test-pass-12345")

    response = client.post(
        reverse("analytics:report_builder"),
        {"report": "finance_receipts", "format": "csv", "preset": "all_time"},
    )

    assert response.status_code == 200
    assert response.context["preview"] is None
    assert response.context["form"].errors


def test_builder_preview_renders_rows(client, sales_officer, customer):
    _paid_order(customer, currency="NGN", amount="1000.00")
    assert client.login(email=sales_officer.email, password="test-pass-12345")

    response = client.post(
        reverse("analytics:report_builder"),
        {"report": "inventory_stock", "format": "csv", "preset": "all_time"},
    )

    assert response.status_code == 200
    preview = response.context["preview"]
    assert preview is not None
    assert preview["display_columns"]


def test_generate_export_and_download(client, sales_officer, customer):
    _paid_order(customer, currency="NGN", amount="1000.00")
    assert client.login(email=sales_officer.email, password="test-pass-12345")

    response = client.post(
        reverse("analytics:report_generate"),
        {"report": "inventory_stock", "format": "csv", "preset": "all_time"},
    )

    assert response.status_code == 302
    export = ReportExport.objects.get()
    assert export.status == ExecutionStatus.SUCCEEDED
    assert export.file

    download = client.get(reverse("analytics:report_download", args=[export.pk]))
    assert download.status_code == 200
    assert b"Product" in b"".join(download.streaming_content)


def test_download_is_denied_for_another_user(client, sales_officer, consultant, customer):
    _paid_order(customer, currency="NGN", amount="1000.00")
    assert client.login(email=sales_officer.email, password="test-pass-12345")
    client.post(
        reverse("analytics:report_generate"),
        {"report": "inventory_stock", "format": "csv", "preset": "all_time"},
    )
    export = ReportExport.objects.get()

    assert client.login(email=consultant.email, password="test-pass-12345")
    # Consultant lacks reports.build entirely.
    assert client.get(reverse("analytics:report_download", args=[export.pk])).status_code == 403


def test_history_is_scoped_to_owner_without_manage(client, sales_officer, consultant, customer):
    mine = ReportExport.objects.create(
        report_key="inventory_stock", export_format="csv", requested_by=sales_officer
    )
    theirs = ReportExport.objects.create(
        report_key="inventory_stock", export_format="csv", requested_by=consultant
    )

    assert client.login(email=sales_officer.email, password="test-pass-12345")
    response = client.get(reverse("analytics:report_history"))

    assert response.status_code == 200
    assert mine in response.context["exports"]
    assert theirs not in response.context["exports"]


def test_finance_officer_sees_every_export(client, sales_officer, finance_officer):
    other = ReportExport.objects.create(
        report_key="inventory_stock", export_format="csv", requested_by=sales_officer
    )
    assert client.login(email=finance_officer.email, password="test-pass-12345")

    response = client.get(reverse("analytics:report_history"))

    assert other in response.context["exports"]


def test_financial_report_generation_is_audited(client, finance_officer, customer):
    _paid_order(customer, currency="NGN", amount="1000.00")
    assert client.login(email=finance_officer.email, password="test-pass-12345")

    client.post(
        reverse("analytics:report_generate"),
        {"report": "finance_receipts", "format": "csv", "preset": "all_time"},
    )

    assert AuditLog.objects.filter(action="report.financial.generated").exists()


# ---------------------------------------------------------------------------
# Exports: formats and safety
# ---------------------------------------------------------------------------


def test_formula_injection_guard():
    assert exports.guard("=1+1") == "'=1+1"
    assert exports.guard("+sum(A1)") == "'+sum(A1)"
    assert exports.guard("@cmd") == "'@cmd"
    assert exports.guard("normal") == "normal"


def test_generate_csv_xlsx_and_pdf():
    columns = reports.get_report("inventory_stock").columns
    rows = [
        {
            "product": "=EVIL",
            "packaging": "50kg",
            "warehouse": "Main",
            "on_hand": 10,
            "reserved": 2,
            "available": 8,
            "unit": "kg",
        }
    ]

    csv_bytes = exports.generate(
        columns, rows, export_format="csv", title="Stock", subtitle="", footer=""
    )
    assert csv_bytes.startswith(b"\xef\xbb\xbf") or b"product" in csv_bytes.lower()
    assert b"'=EVIL" in csv_bytes

    xlsx_bytes = exports.generate(
        columns, rows, export_format="xlsx", title="Stock", subtitle="", footer=""
    )
    assert zipfile.is_zipfile(io.BytesIO(xlsx_bytes))

    pdf_bytes = exports.generate(
        columns, rows, export_format="pdf", title="Stock", subtitle="", footer=""
    )
    assert pdf_bytes.startswith(b"%PDF-")


def test_cleanup_expired_exports(customer):
    export = ReportExport.objects.create(
        report_key="inventory_stock",
        export_format="csv",
        status=ExecutionStatus.SUCCEEDED,
        expires_at=timezone.now() - timedelta(days=1),
    )
    export.file.save("old.csv", io.BytesIO(b"a,b\n"), save=True)

    cleaned = services.cleanup_expired_exports()

    export.refresh_from_db()
    assert cleaned == 1
    assert export.status == ExecutionStatus.EXPIRED
    assert not export.file


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------


def test_settled_payment_missing_verification_is_flagged(customer):
    _paid_order(customer, currency="NGN", amount="750.00", verified=False)

    results = {row["key"]: row for row in data_quality.run_checks()}

    assert results["settled_payment_without_verified_at"]["count"] >= 1
    assert results["settled_payment_without_verified_at"]["ok"] is False


# ---------------------------------------------------------------------------
# Scheduling and delivery
# ---------------------------------------------------------------------------


def test_scheduled_create_view(client, finance_officer):
    assert client.login(email=finance_officer.email, password="test-pass-12345")

    response = client.post(
        reverse("analytics:scheduled_create"),
        {
            "name": "Weekly stock",
            "report": "inventory_stock",
            "format": "csv",
            "frequency": "weekly",
            "preset": "all_time",
        },
    )

    assert response.status_code == 302
    schedule = ScheduledReport.objects.get()
    assert schedule.report_key == "inventory_stock"
    assert schedule.is_enabled is True


def test_delivery_skips_unauthorised_recipient(finance_officer, content_editor):
    definition = reports.get_report("inventory_stock")
    schedule = services.create_scheduled_report(
        name="Stock digest",
        definition=definition,
        filters=ReportFilters(preset="all_time"),
        frequency="daily",
        export_format="csv",
        recipients=[finance_officer, content_editor],
        user=finance_officer,
    )

    execution = services.execute_scheduled_report(schedule)

    assert execution is not None
    deliveries = {d.recipient_id: d.status for d in ReportDelivery.objects.all()}
    assert deliveries[finance_officer.pk] == DeliveryStatus.SENT
    assert deliveries[content_editor.pk] == DeliveryStatus.SKIPPED


def test_schedule_runs_at_most_once_per_period(finance_officer):
    definition = reports.get_report("inventory_stock")
    schedule = services.create_scheduled_report(
        name="Once",
        definition=definition,
        filters=ReportFilters(preset="all_time"),
        frequency="daily",
        export_format="csv",
        recipients=[finance_officer],
        user=finance_officer,
    )
    fixed = timezone.now() - timedelta(hours=1)
    ScheduledReport.objects.filter(pk=schedule.pk).update(next_run_at=fixed)
    schedule.refresh_from_db()

    first = services.execute_scheduled_report(schedule, now=fixed)
    ScheduledReport.objects.filter(pk=schedule.pk).update(next_run_at=fixed)
    schedule.refresh_from_db()
    second = services.execute_scheduled_report(schedule, now=fixed)

    assert first is not None
    assert second is None
    assert ReportExecution.objects.count() == 1


def test_run_due_schedules(finance_officer):
    definition = reports.get_report("inventory_stock")
    schedule = services.create_scheduled_report(
        name="Due",
        definition=definition,
        filters=ReportFilters(preset="all_time"),
        frequency="daily",
        export_format="csv",
        recipients=[finance_officer],
        user=finance_officer,
    )
    ScheduledReport.objects.filter(pk=schedule.pk).update(
        next_run_at=timezone.now() - timedelta(days=1)
    )

    assert services.run_due_schedules() == 1


def test_run_scheduled_reports_command(finance_officer):
    definition = reports.get_report("inventory_stock")
    schedule = services.create_scheduled_report(
        name="Command",
        definition=definition,
        filters=ReportFilters(preset="all_time"),
        frequency="daily",
        export_format="csv",
        recipients=[finance_officer],
        user=finance_officer,
    )
    ScheduledReport.objects.filter(pk=schedule.pk).update(
        next_run_at=timezone.now() - timedelta(days=1)
    )

    management.call_command("run_scheduled_reports")

    assert ReportExecution.objects.filter(scheduled_report=schedule).exists()


def test_scheduled_toggle_and_run_now(client, finance_officer):
    definition = reports.get_report("inventory_stock")
    schedule = services.create_scheduled_report(
        name="Toggle",
        definition=definition,
        filters=ReportFilters(preset="all_time"),
        frequency="daily",
        export_format="csv",
        recipients=[finance_officer],
        user=finance_officer,
    )
    assert client.login(email=finance_officer.email, password="test-pass-12345")

    pause = client.post(
        reverse("analytics:scheduled_toggle", args=[schedule.pk]), {"enabled": "false"}
    )
    assert pause.status_code == 302
    schedule.refresh_from_db()
    assert schedule.is_enabled is False

    run = client.post(reverse("analytics:scheduled_run_now", args=[schedule.pk]))
    assert run.status_code == 302
    assert ReportExecution.objects.filter(scheduled_report=schedule).exists()

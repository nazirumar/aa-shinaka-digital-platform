"""Phase 8 — agricultural export management & international trade.

Behaviour under test flows through ``apps.export.services`` (writes,
transitions, compliance gates, permissions), ``apps.orders.payments`` (the
verified payment path) and the real URL/view layer for the customer portal and
staff dashboard. Reads are checked against ``apps.export.selectors``.

Money and quantities are ``Decimal``. Destinations may only be activated by an
approver. Official document types are configurable records — never fabricated.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from catalog_helpers import make_category, make_product
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone
from export_helpers import (
    make_destination,
    make_enquiry,
    make_export_country,
    make_export_order,
    make_export_product,
    make_quotation,
)

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.export import selectors, services
from apps.export.models import (
    ApprovalStatus,
    DocumentVerificationStatus,
    ExportDestination,
    ExportDocumentType,
    ExportEnquiry,
    ExportEnquiryStatus,
    ExportOrder,
    ExportOrderStatus,
    ExportQuotationStatus,
    RestrictionType,
    ShipmentStatus,
    TransportMode,
)
from apps.orders import paystack
from apps.orders.payment_models import Payment, PaymentState

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _user(email: str, role: str, **extra) -> User:
    user = User.objects.create_user(
        email=email, role=role, password="test-pass-12345", is_staff=True, **extra
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def export_officer(db) -> User:
    """Has ``EXPORT_MANAGE`` but not ``EXPORT_APPROVE``."""
    return _user("officer@example.com", UserRole.EXPORT_OFFICER, first_name="Efe", last_name="Ogbe")


@pytest.fixture
def other_customer(db) -> User:
    user = User.objects.create_user(
        email="other@example.com",
        role=UserRole.CUSTOMER,
        password="test-pass-12345",
        first_name="Ada",
        last_name="Nwosu",
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def category(db):
    return make_category(name="Grains")


@pytest.fixture
def product(category):
    return make_product(category, name="Maize")


@pytest.fixture
def destination(administrator) -> ExportDestination:
    return make_destination(actor=administrator)


@pytest.fixture
def ready_product(product, destination, administrator):
    make_export_product(product, actor=administrator, destinations=[destination])
    return product


@pytest.fixture
def enquiry(customer, ready_product, destination, administrator) -> ExportEnquiry:
    return make_enquiry(
        customer, destination=destination, product=ready_product, actor=administrator
    )


@pytest.fixture
def order(enquiry, ready_product, administrator, customer) -> ExportOrder:
    """An accepted export order (created by the customer) with its checklist built."""
    return make_export_order(
        enquiry,
        actor=administrator,
        approver=administrator,
        customer=customer,
        product=ready_product,
    )


def _login(client, user: User) -> None:
    assert client.login(email=user.email, password="test-pass-12345")


def _file(name: str = "doc.txt"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, b"content", content_type="text/plain")


# ---------------------------------------------------------------------------
# Task 1 — destinations (approved, then activated)
# ---------------------------------------------------------------------------


def test_new_destination_is_pending_and_inactive(administrator):
    destination = services.upsert_destination(
        country=make_export_country("ZA", "South Africa"), actor=administrator
    )
    assert destination.approval_status == ApprovalStatus.PENDING
    assert destination.is_active is False


def test_activation_requires_prior_approval(administrator):
    destination = services.upsert_destination(
        country=make_export_country("ZM", "Zambia"), actor=administrator
    )
    with pytest.raises(ValidationError):
        services.set_destination_active(destination, actor=administrator, active=True)


def test_approval_requires_approve_capability(export_officer, administrator):
    destination = services.upsert_destination(
        country=make_export_country("CI", "Cote d'Ivoire"), actor=export_officer
    )
    with pytest.raises(PermissionDenied):
        services.approve_destination(destination, actor=export_officer)

    services.approve_destination(destination, actor=administrator)
    destination.refresh_from_db()
    assert destination.approval_status == ApprovalStatus.APPROVED


def test_active_and_approved_are_both_required(administrator):
    destination = services.upsert_destination(
        country=make_export_country("TG", "Togo"), actor=administrator
    )
    services.approve_destination(destination, actor=administrator)
    destination.refresh_from_db()
    assert destination.is_active is False
    assert selectors.approved_active_destinations().filter(pk=destination.pk).exists() is False


def test_destination_activation_is_audited(administrator, destination):
    assert destination.is_active is True
    assert destination.approved_by_id == administrator.pk
    assert destination.approved_at is not None


# ---------------------------------------------------------------------------
# Task 2 — product configuration, restrictions
# ---------------------------------------------------------------------------


def test_enquiry_requires_export_profile(customer, destination, product, administrator):
    with pytest.raises(ValidationError):
        make_enquiry(customer, destination=destination, product=product, actor=administrator)


def test_trade_restriction_blocks_destination(customer, ready_product, destination, administrator):
    services.add_trade_restriction(
        destination,
        actor=administrator,
        product=ready_product,
        restriction_type=RestrictionType.PROHIBITED,
        description="Import suspended (documents on file).",
    )
    assert ready_product.export_profile.allows_destination(destination) is False
    with pytest.raises(ValidationError):
        make_enquiry(customer, destination=destination, product=ready_product, actor=administrator)


def test_minimum_export_quantity_enforced(customer, product, destination, administrator):
    make_export_product(
        product,
        actor=administrator,
        destinations=[destination],
        min_export_quantity=Decimal("1000"),
        min_export_unit=product.unit,
    )
    with pytest.raises(ValidationError):
        make_enquiry(
            customer,
            destination=destination,
            product=product,
            actor=administrator,
            quantity=Decimal("500"),
        )


def test_allowed_destinations_are_positive(administrator, product):
    allowed = make_destination(actor=administrator, country=make_export_country("SN", "Senegal"))
    blocked = make_destination(actor=administrator, country=make_export_country("ML", "Mali"))
    make_export_product(product, actor=administrator, destinations=[allowed])
    assert product.export_profile.allows_destination(allowed) is True
    assert product.export_profile.allows_destination(blocked) is False


# ---------------------------------------------------------------------------
# Task 3 — enquiries
# ---------------------------------------------------------------------------


def test_enquiry_defaults_and_history(enquiry):
    assert enquiry.reference.startswith("AS-EXQ")
    assert enquiry.status == ExportEnquiryStatus.SUBMITTED
    assert enquiry.status_history.count() == 1
    assert enquiry.item_count == 1


def test_customer_cannot_create_for_another_party(
    customer, other_customer, ready_product, destination
):
    with pytest.raises(PermissionDenied):
        make_enquiry(customer, destination=destination, product=ready_product, actor=other_customer)


def test_illegal_enquiry_transition(enquiry, administrator):
    with pytest.raises(ValidationError):
        services.transition_enquiry(enquiry, "not_a_status", actor=administrator)


def test_terminal_enquiry_cannot_reopen(enquiry, administrator):
    services.cancel_enquiry(enquiry, actor=administrator)
    enquiry.refresh_from_db()
    assert enquiry.status == ExportEnquiryStatus.CANCELLED
    with pytest.raises(ValidationError):
        services.transition_enquiry(enquiry, ExportEnquiryStatus.UNDER_REVIEW, actor=administrator)


def test_review_enquiry_records_transition(enquiry, administrator):
    services.review_enquiry(enquiry, actor=administrator)
    enquiry.refresh_from_db()
    assert enquiry.status == ExportEnquiryStatus.UNDER_REVIEW


# ---------------------------------------------------------------------------
# Task 4 — quotations
# ---------------------------------------------------------------------------


def test_quotation_approval_requires_approve_capability(enquiry, ready_product, export_officer):
    quotation = make_quotation(enquiry, actor=export_officer, product=ready_product)
    with pytest.raises(PermissionDenied):
        services.approve_quotation(quotation, actor=export_officer)


def test_issue_requires_incoterm_version_and_named_place(enquiry, ready_product, administrator):
    quotation = make_quotation(
        enquiry,
        actor=administrator,
        product=ready_product,
        incoterm="",
        named_place="",
        incoterm_version="",
    )
    with pytest.raises(ValidationError):
        services.approve_quotation(quotation, actor=administrator)


def test_approve_issues_quotation_and_marks_enquiry_quoted(enquiry, ready_product, administrator):
    quotation = make_quotation(enquiry, actor=administrator, product=ready_product)
    services.approve_quotation(quotation, actor=administrator)
    quotation.refresh_from_db()
    quotation.enquiry.refresh_from_db()
    assert quotation.status == ExportQuotationStatus.ISSUED
    assert quotation.approved_by_id == administrator.pk
    assert quotation.enquiry.status == ExportEnquiryStatus.QUOTED


def test_accept_creates_order_and_converts_enquiry(enquiry, ready_product, administrator, customer):
    quotation = make_quotation(enquiry, actor=administrator, product=ready_product)
    services.approve_quotation(quotation, actor=administrator)
    order = services.accept_quotation(quotation, actor=customer)
    quotation.refresh_from_db()
    order.refresh_from_db()
    assert quotation.status == ExportQuotationStatus.ACCEPTED
    assert order.status == ExportOrderStatus.PENDING_PAYMENT
    assert order.total == quotation.total
    assert order.deposit_amount == quotation.required_deposit()
    assert order.balance_amount == quotation.total - order.deposit_amount
    assert order.items.count() == 1
    assert quotation.enquiry.status == ExportEnquiryStatus.CONVERTED


def test_cannot_accept_draft_quotation(enquiry, ready_product, administrator, customer):
    quotation = make_quotation(enquiry, actor=administrator, product=ready_product)
    with pytest.raises(ValidationError):
        services.accept_quotation(quotation, actor=customer)


def test_cannot_accept_expired_quotation(enquiry, ready_product, administrator, customer):
    quotation = make_quotation(
        enquiry,
        actor=administrator,
        product=ready_product,
        valid_until=timezone.localdate() - timedelta(days=1),
    )
    services.approve_quotation(quotation, actor=administrator)
    with pytest.raises(ValidationError):
        services.accept_quotation(quotation, actor=customer)


def test_revise_quotation_snapshots_and_resets(enquiry, ready_product, administrator):
    quotation = make_quotation(enquiry, actor=administrator, product=ready_product)
    services.revise_quotation(
        quotation,
        actor=administrator,
        changes={"named_place": "Tincan, Lagos"},
        summary="Named place corrected",
    )
    quotation.refresh_from_db()
    assert quotation.revision == 2
    assert quotation.status == ExportQuotationStatus.DRAFT
    assert quotation.revisions.count() == 1
    assert quotation.named_place == "Tincan, Lagos"


def test_accepted_quotation_is_frozen(enquiry, ready_product, administrator, customer):
    quotation = make_quotation(enquiry, actor=administrator, product=ready_product)
    services.approve_quotation(quotation, actor=administrator)
    services.accept_quotation(quotation, actor=customer)
    quotation.total = Decimal("1.23")
    with pytest.raises(ValidationError):
        quotation.save()


# ---------------------------------------------------------------------------
# Task 5/7 — orders & compliance
# ---------------------------------------------------------------------------


def test_order_starts_pending_payment(order):
    assert order.status == ExportOrderStatus.PENDING_PAYMENT
    assert order.balance_due == order.total
    assert order.compliance_checklist is not None


def test_order_can_enter_production(order, administrator):
    services.transition_export_order(order, ExportOrderStatus.IN_PRODUCTION, actor=administrator)
    order.refresh_from_db()
    assert order.status == ExportOrderStatus.IN_PRODUCTION


def test_illegal_order_transition(order, administrator):
    with pytest.raises(ValidationError):
        services.transition_export_order(order, "delivered", actor=administrator)


def test_checklist_includes_destination_document_requirement(
    customer, ready_product, destination, administrator
):
    doc_type = ExportDocumentType.objects.get(code="phytosanitary_certificate")
    services.add_document_requirement(destination, actor=administrator, document_type=doc_type)
    enquiry = make_enquiry(
        customer, destination=destination, product=ready_product, actor=administrator
    )
    order = make_export_order(
        enquiry,
        actor=administrator,
        approver=administrator,
        customer=customer,
        product=ready_product,
    )
    checklist = order.compliance_checklist
    assert checklist.items.filter(title=f"Provide {doc_type.name}").exists()


def test_approve_checklist_requires_approve(order, export_officer):
    checklist = order.compliance_checklist
    with pytest.raises(PermissionDenied):
        services.approve_compliance_checklist(checklist, actor=export_officer)


def test_approve_checklist_denied_for_customer(order, customer):
    with pytest.raises(PermissionDenied):
        services.approve_compliance_checklist(order.compliance_checklist, actor=customer)


def test_incomplete_checklist_cannot_be_approved(
    customer, ready_product, destination, administrator
):
    doc_type = ExportDocumentType.objects.get(code="phytosanitary_certificate")
    services.add_document_requirement(destination, actor=administrator, document_type=doc_type)
    enquiry = make_enquiry(
        customer, destination=destination, product=ready_product, actor=administrator
    )
    order = make_export_order(
        enquiry,
        actor=administrator,
        approver=administrator,
        customer=customer,
        product=ready_product,
    )
    checklist = order.compliance_checklist
    assert checklist.is_complete is False
    with pytest.raises(ValidationError):
        services.approve_compliance_checklist(checklist, actor=administrator)


def test_ready_for_shipment_blocked_until_compliance_cleared(order, administrator):
    with pytest.raises(ValidationError):
        services.transition_export_order(order, "ready_for_shipment", actor=administrator)


# ---------------------------------------------------------------------------
# Task 6 — documents
# ---------------------------------------------------------------------------


def test_official_document_type_requires_expiry(order, administrator):
    doc_type = ExportDocumentType.objects.get(code="phytosanitary_certificate")
    assert doc_type.requires_expiry is True
    with pytest.raises(ValidationError):
        services.add_document(order, actor=administrator, document_type=doc_type, file=_file())


def test_add_document_requires_file(order, administrator):
    doc_type = ExportDocumentType.objects.get(code="proforma_invoice")
    with pytest.raises(ValidationError):
        services.add_document(order, actor=administrator, document_type=doc_type, file=None)


def test_document_review_mapping(order, administrator):
    doc_type = ExportDocumentType.objects.get(code="proforma_invoice")
    document = services.add_document(
        order, actor=administrator, document_type=doc_type, file=_file()
    )
    assert document.verification_status == DocumentVerificationStatus.SUBMITTED
    services.review_document(document, actor=administrator, decision="approved")
    document.refresh_from_db()
    assert document.verification_status == DocumentVerificationStatus.VERIFIED
    assert document.reviews.count() == 1


def test_customer_supporting_document_recorded(order, customer):
    doc_type = ExportDocumentType.objects.get(code="commercial_invoice")
    document = services.upload_customer_document(
        order, customer=customer, document_type=doc_type, file=_file()
    )
    assert document.order_id == order.pk
    assert document.verification_status == DocumentVerificationStatus.SUBMITTED


def test_cannot_upload_document_for_someone_elses_order(order, other_customer):
    doc_type = ExportDocumentType.objects.get(code="commercial_invoice")
    with pytest.raises(PermissionDenied):
        services.upload_customer_document(
            order, customer=other_customer, document_type=doc_type, file=_file()
        )


def test_customer_visible_documents_hide_staff_only(order, administrator):
    doc_type = ExportDocumentType.objects.get(code="proforma_invoice")
    services.add_document(
        order,
        actor=administrator,
        document_type=doc_type,
        file=_file("hidden.txt"),
        is_customer_visible=False,
    )
    services.add_document(
        order,
        actor=administrator,
        document_type=doc_type,
        file=_file("shown.txt"),
        is_customer_visible=True,
    )
    assert selectors.visible_documents(order).count() == 1
    assert selectors.visible_documents(order, staff=True).count() == 2


# ---------------------------------------------------------------------------
# Task 8 — shipments & milestones
# ---------------------------------------------------------------------------


def _shipment(order, administrator):
    return services.create_shipment(
        order,
        actor=administrator,
        transport_mode=TransportMode.SEA,
        origin="Apapa, Lagos",
        destination="Tema, Ghana",
    )


def _shippable_order(enquiry, ready_product, administrator, customer):
    """An accepted order whose compliance is cleared and status is ready."""
    order = make_export_order(
        enquiry,
        actor=administrator,
        approver=administrator,
        customer=customer,
        product=ready_product,
    )
    services.approve_compliance_checklist(order.compliance_checklist, actor=administrator)
    order.refresh_from_db()
    services.transition_export_order(
        order, ExportOrderStatus.READY_FOR_SHIPMENT, actor=administrator
    )
    order.refresh_from_db()
    return order


def test_create_shipment_copies_order_items(order, administrator):
    shipment = _shipment(order, administrator)
    assert shipment.reference.startswith("AS-EXS")
    assert shipment.items.count() == order.items.count()
    assert shipment.status == ShipmentStatus.PREPARING


def test_dispatch_requires_compliance(order, administrator):
    shipment = _shipment(order, administrator)
    with pytest.raises(ValidationError):
        services.transition_shipment(shipment, ShipmentStatus.DISPATCHED, actor=administrator)


def test_delivered_shipment_advances_order(enquiry, ready_product, administrator, customer):
    order = _shippable_order(enquiry, ready_product, administrator, customer)
    shipment = _shipment(order, administrator)
    services.transition_shipment(shipment, ShipmentStatus.DELIVERED, actor=administrator)
    shipment.refresh_from_db()
    order.refresh_from_db()
    assert shipment.status == ShipmentStatus.DELIVERED
    assert shipment.actual_arrival is not None
    assert order.status == ExportOrderStatus.DELIVERED
    assert order.delivered_at is not None


def test_milestone_is_staff_entered(order, administrator):
    shipment = _shipment(order, administrator)
    milestone = services.add_shipment_milestone(
        shipment,
        actor=administrator,
        status=ShipmentStatus.DISPATCHED,
        location="Lagos Port",
    )
    assert milestone.is_staff_entered is True
    assert milestone.recorded_by_id == administrator.pk


def test_illegal_shipment_transition(order, administrator):
    shipment = _shipment(order, administrator)
    with pytest.raises(ValidationError):
        services.transition_shipment(shipment, ShipmentStatus.DELIVERED, actor=administrator)


# ---------------------------------------------------------------------------
# Task 9 — verified payments only
# ---------------------------------------------------------------------------


@pytest.fixture
def paystack_usd(settings):
    settings.PAYSTACK_ENABLED = True
    settings.PAYSTACK_SECRET_KEY = "sk_test_1234567890"
    settings.PAYSTACK_WEBHOOK_SECRET = ""
    settings.PAYSTACK_CURRENCY = "USD"
    return settings


@pytest.fixture
def fake_paystack(monkeypatch):
    state: dict = {}

    def fake_initialize(**kwargs):
        state["initialize"] = kwargs
        return {
            "authorization_url": "https://checkout.paystack.test/export",
            "access_code": "acc_export",
            "reference": kwargs["reference"],
        }

    def fake_verify(reference):
        payload = dict(state.get("verify_payload") or {})
        payload.setdefault("reference", reference)
        payload.setdefault("status", "success")
        payload.setdefault("currency", "USD")
        return payload

    monkeypatch.setattr(paystack, "initialize_transaction", fake_initialize)
    monkeypatch.setattr(paystack, "verify_transaction", fake_verify)
    return state


def _kobo(amount) -> int:
    return int((Decimal(str(amount)) * 100).to_integral_value())


def test_customer_cannot_pay_someone_elses_export_order(
    order, other_customer, paystack_usd, fake_paystack
):
    from apps.orders import payments as order_payments

    with pytest.raises(PermissionDenied):
        order_payments.initialize_export_payment(order, actor=other_customer, amount=order.total)


def test_verified_payment_settles_export_order(order, customer, paystack_usd, fake_paystack):
    from apps.orders import payments as order_payments

    payment = order_payments.initialize_export_payment(
        order, actor=customer, amount=order.total, purpose="full"
    )
    assert payment.export_order_id == order.pk
    assert payment.status == PaymentState.PROCESSING

    fake_paystack["verify_payload"] = {
        "status": "success",
        "amount": _kobo(order.total),
        "currency": "USD",
        "channel": "card",
    }
    order_payments.verify_payment(payment, source="test")

    order.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == PaymentState.PAID
    assert payment.verified_amount == order.total
    assert order.amount_paid == order.total
    assert order.status == ExportOrderStatus.PAYMENT_VERIFIED


def test_verified_revenue_excludes_other_payments(order, customer, paystack_usd, fake_paystack):
    from apps.orders import payments as order_payments
    from apps.orders.models import Order

    shop_order = Order.objects.create(number="AS-SHOP-TEST-1", user=customer)
    Payment.objects.create(
        order=shop_order,
        customer=customer,
        reference="AS-PAY-SHOP-1",
        provider="paystack",
        currency="NGN",
        expected_amount=Decimal("1000.00"),
        verified_amount=Decimal("1000.00"),
        status=PaymentState.PAID,
    )
    payment = order_payments.initialize_export_payment(order, actor=customer, amount=order.total)
    fake_paystack["verify_payload"] = {
        "status": "success",
        "amount": _kobo(order.total),
        "currency": "USD",
        "channel": "card",
    }
    order_payments.verify_payment(payment, source="test")

    # The NGN shop payment is `paid` too but must never count as export revenue.
    assert selectors.overview_metrics()["verified_revenue"] == order.total


# ---------------------------------------------------------------------------
# Task 12 — reporting
# ---------------------------------------------------------------------------


def test_overview_metrics_keys(order):
    metrics = selectors.overview_metrics()
    for key in (
        "enquiries",
        "open_enquiries",
        "quotations_issued",
        "orders",
        "open_orders",
        "dispatched_shipments",
        "delivered_shipments",
        "verified_revenue",
        "active_destinations",
    ):
        assert key in metrics
    assert metrics["orders"] == 1


def test_product_quantities_from_accepted_orders(order):
    quantities = selectors.product_quantities()
    assert quantities
    assert quantities[0]["quantity"] == order.items.first().quantity


# ---------------------------------------------------------------------------
# Customer portal — views & ownership
# ---------------------------------------------------------------------------


def test_customer_portal_requires_login(client):
    response = client.get(reverse("export:home"))
    assert response.status_code == 302


def test_customer_cannot_view_anothers_order(client, order, other_customer):
    _login(client, other_customer)
    response = client.get(reverse("export:order_detail", args=[order.reference]))
    assert response.status_code == 404


def test_customer_home_renders(client, order, customer):
    _login(client, customer)
    response = client.get(reverse("export:home"))
    assert response.status_code == 200


def test_customer_enquiry_create_view(client, customer, destination, ready_product):
    from apps.catalog.models import PublishStatus

    ready_product.status = PublishStatus.PUBLISHED
    ready_product.save(update_fields=["status"])
    _login(client, customer)
    response = client.post(
        reverse("export:enquiry_create"),
        {
            "destination": str(destination.pk),
            "delivery_destination": "Tema, Ghana",
            "preferred_shipping_mode": "sea",
            "priority": "normal",
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "1",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-product": str(ready_product.pk),
            "form-0-quantity": "500",
        },
    )
    assert response.status_code in {200, 302}
    assert ExportEnquiry.objects.filter(customer=customer).exists()


def test_customer_can_download_visible_document(client, order, customer, administrator):
    doc_type = ExportDocumentType.objects.get(code="proforma_invoice")
    document = services.add_document(
        order,
        actor=administrator,
        document_type=doc_type,
        file=_file("visible.txt"),
        is_customer_visible=True,
    )
    _login(client, customer)
    response = client.get(reverse("export:document_download", args=[document.pk]))
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Staff dashboard — capability gating
# ---------------------------------------------------------------------------


def test_staff_dashboard_requires_export_capability(client, customer):
    _login(client, customer)
    response = client.get(reverse("export_dashboard:home"))
    assert response.status_code == 403


def test_anonymous_staff_dashboard_redirects(client):
    response = client.get(reverse("export_dashboard:home"))
    assert response.status_code == 302


def test_export_officer_can_access_dashboard(client, export_officer):
    _login(client, export_officer)
    response = client.get(reverse("export_dashboard:home"))
    assert response.status_code == 200


def test_staff_dashboard_home_renders(client, administrator, order):
    _login(client, administrator)
    response = client.get(reverse("export_dashboard:home"))
    assert response.status_code == 200
    assert b"Export" in response.content


def test_staff_reports_render(client, administrator, order):
    _login(client, administrator)
    response = client.get(reverse("export_dashboard:reports"))
    assert response.status_code == 200


def test_staff_order_detail_renders(client, administrator, order):
    _login(client, administrator)
    response = client.get(reverse("export_dashboard:order_detail", args=[order.reference]))
    assert response.status_code == 200


def test_customer_cannot_reach_staff_dashboard(client, customer):
    _login(client, customer)
    for name in ("enquiry_list", "order_list", "destination_list"):
        response = client.get(reverse(f"export_dashboard:{name}"))
        assert response.status_code == 403

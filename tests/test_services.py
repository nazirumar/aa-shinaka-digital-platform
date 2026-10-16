"""Phase 7 tests: shared service requests, the four service divisions,
quotations, verified-payment settlement, the customer portal and the staff
service dashboard.

Behaviour that is under test always goes through ``apps.services.services`` /
``apps.services.payments`` so the real validation, transitions, capacity
accounting and permission checks are exercised.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from services_helpers import (
    future_window,
    issue_quotation,
    make_consultancy_service,
    make_consultant,
    make_facility,
    make_produce_type,
    make_quotation,
    make_request,
    make_storage_request,
    make_storage_unit,
)

from apps.accounts.models import UserRole
from apps.accounts.roles import sync_user_groups
from apps.orders.payment_models import Payment, PaymentState
from apps.services import notifications, payments, selectors, services
from apps.services.models import (
    AppointmentStatus,
    ConsultationMode,
    FarmProjectStatus,
    MarketingCampaignStatus,
    MarketingProposalStatus,
    QuotationPaymentStatus,
    QuotationStatus,
    ServicePriority,
    ServiceRequestStatus,
    ServiceType,
    StorageBookingStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def consultant_user(db):
    user = get_user_model().objects.create_user(
        email="consultant@example.com",
        password="test-pass-12345",
        first_name="Ngozi",
        last_name="Ade",
        role=UserRole.CONSULTANT,
        is_staff=True,
    )
    sync_user_groups(user)
    return user


# ---------------------------------------------------------------------------
# Shared foundation (Task 1)
# ---------------------------------------------------------------------------


def test_service_request_reference_history_and_activity(customer):
    request_obj = make_request(customer, description="Need help")
    assert request_obj.reference.startswith("AS-SR")
    assert request_obj.status == ServiceRequestStatus.SUBMITTED
    assert request_obj.status_history.count() == 1
    assert request_obj.activity_log.filter(action="request.created").exists()
    assert request_obj.is_open is True


def test_request_transition_guards_and_closing(customer, administrator):
    request_obj = make_request(customer)
    assert request_obj.can_transition_to(ServiceRequestStatus.UNDER_REVIEW)
    assert not request_obj.can_transition_to(ServiceRequestStatus.COMPLETED)

    services.review_service_request(
        request_obj, actor=administrator, note="Looking into it", priority=ServicePriority.HIGH
    )
    request_obj.refresh_from_db()
    assert request_obj.status == ServiceRequestStatus.UNDER_REVIEW
    assert request_obj.priority == ServicePriority.HIGH
    assert request_obj.status_history.count() == 2


def test_assign_staff_sets_primary_owner(customer, administrator, staff_user):
    request_obj = make_request(customer, service_type=ServiceType.MARKETING)
    assignment = services.assign_staff(
        request_obj, staff=staff_user, actor=administrator, role="officer", note="Please handle"
    )
    request_obj.refresh_from_db()
    assert request_obj.assigned_to == staff_user
    assert assignment.is_active is True

    # Assigning again with the same role reactivates the existing row.
    services.assign_staff(request_obj, staff=staff_user, actor=administrator, role="officer")
    assert request_obj.assignments.count() == 1


def test_comments_and_attachment_validation(customer, administrator):
    request_obj = make_request(customer)
    services.add_comment(request_obj, author=customer, body="Hello", visibility="customer")
    with pytest.raises(ValidationError):
        services.add_comment(request_obj, author=customer, body="   ")

    with pytest.raises(ValidationError):
        services.add_attachment(
            request_obj,
            uploaded_by=administrator,
            file=SimpleUploadedFile("malware.exe", b"x"),
        )

    attachment = services.add_attachment(
        request_obj,
        uploaded_by=customer,
        file=SimpleUploadedFile("invoice.pdf", b"%PDF-1.4 test"),
    )
    assert request_obj.attachments.count() == 1
    assert attachment.label == "invoice.pdf"


def test_notification_dedupe_only_sends_once(customer):
    request_obj = make_request(customer, notify=False)
    first = notifications.notify_once(
        event="demo",
        dedupe_key=f"demo:{request_obj.pk}",
        to="customer@example.com",
        subject="Hello",
        heading="Hello",
        intro="Hello",
    )
    second = notifications.notify_once(
        event="demo",
        dedupe_key=f"demo:{request_obj.pk}",
        to="customer@example.com",
        subject="Hello",
        heading="Hello",
        intro="Hello",
    )
    assert first is True
    assert second is False


def test_staff_can_only_act_within_their_division(customer, administrator, consultant_user):
    marketing = make_request(customer, service_type=ServiceType.MARKETING)
    # The consultant lacks the marketing capability.
    with pytest.raises(PermissionDenied):
        services.review_service_request(marketing, actor=consultant_user)
    # The administrator holds every capability.
    services.review_service_request(marketing, actor=administrator)


# ---------------------------------------------------------------------------
# Consultancy (Task 2)
# ---------------------------------------------------------------------------


def test_book_consultation_creates_requested_appointment(customer):
    service = make_consultancy_service()
    start, _ = future_window()
    appointment = services.book_consultation(
        customer=customer,
        service=service,
        mode=ConsultationMode.ONLINE,
        preferred_start=start,
        description="pH levels",
    )
    assert appointment.status == AppointmentStatus.REQUESTED
    assert appointment.request.service_type == ServiceType.CONSULTANCY
    assert appointment.scheduled_start == start


def test_consultation_mode_must_be_supported(customer):
    service = make_consultancy_service(supports_online=False)
    start, _ = future_window()
    with pytest.raises(ValidationError):
        services.book_consultation(
            customer=customer, service=service, mode=ConsultationMode.ONLINE, preferred_start=start
        )


def test_confirm_requires_availability_then_confirms(customer, administrator, consultant_user):
    start, end = future_window()
    service = make_consultancy_service()
    appointment = services.book_consultation(
        customer=customer, service=service, mode=ConsultationMode.ONLINE, preferred_start=start
    )
    consultant = make_consultant(consultant_user, start=start, end=end)

    with pytest.raises(ValidationError):
        services.confirm_appointment(appointment, actor=administrator)  # no consultant yet

    services.confirm_appointment(
        appointment, actor=administrator, consultant=consultant, start=start, end=end
    )
    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.request.status == ServiceRequestStatus.CONFIRMED


def test_appointment_overlap_is_rejected(customer, administrator, consultant_user):
    start, end = future_window()
    service = make_consultancy_service()
    consultant = make_consultant(consultant_user, start=start, end=end)

    first = services.book_consultation(
        customer=customer, service=service, mode=ConsultationMode.ONLINE, preferred_start=start
    )
    services.confirm_appointment(
        first, actor=administrator, consultant=consultant, start=start, end=end
    )

    second = services.book_consultation(
        customer=customer,
        service=service,
        mode=ConsultationMode.ONLINE,
        preferred_start=start + timedelta(minutes=30),
    )
    with pytest.raises(ValidationError):
        services.confirm_appointment(
            second,
            actor=administrator,
            consultant=consultant,
            start=start + timedelta(minutes=30),
            end=start + timedelta(minutes=90),
        )


def test_complete_appointment_records_report(customer, administrator, consultant_user):
    start, end = future_window()
    service = make_consultancy_service()
    consultant = make_consultant(consultant_user, start=start, end=end)
    appointment = services.book_consultation(
        customer=customer, service=service, mode=ConsultationMode.ONLINE, preferred_start=start
    )
    appointment = services.confirm_appointment(
        appointment, actor=administrator, consultant=consultant, start=start, end=end
    )
    services.record_consultation_report(
        appointment, actor=administrator, summary="Soil is acidic", recommendations="Add lime"
    )
    services.complete_appointment(appointment, actor=administrator, summary="Delivered")
    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.COMPLETED
    assert appointment.request.status == ServiceRequestStatus.COMPLETED


# ---------------------------------------------------------------------------
# Farming (Task 3)
# ---------------------------------------------------------------------------


def test_submit_farm_request_validates_budget(customer):
    farm_request = services.submit_farm_service_request(
        customer=customer, farm_location="Kaduna", crop_type="Maize"
    )
    assert farm_request.request.service_type == ServiceType.FARMING

    with pytest.raises(ValidationError):
        services.submit_farm_service_request(
            customer=customer,
            farm_location="Kaduna",
            budget_min=Decimal("200"),
            budget_max=Decimal("100"),
        )


def test_farm_project_requires_agreement_before_activation(customer, administrator):
    farm_request = services.submit_farm_service_request(
        customer=customer, farm_location="Zaria", crop_type="Rice"
    )
    project = services.create_farm_project(farm_request, actor=administrator, name="Rice project")
    assert project.status == FarmProjectStatus.DRAFT

    with pytest.raises(ValidationError):
        services.activate_farm_project(project, actor=administrator)  # not approved

    services.approve_farm_project(project, actor=administrator)  # approved, no agreement yet
    with pytest.raises(ValidationError):
        services.activate_farm_project(project, actor=administrator)  # missing agreement

    project.agreement_reference = "AGR-1"
    project.save(update_fields=["agreement_reference", "updated_at"])

    services.activate_farm_project(project, actor=administrator)
    project.refresh_from_db()
    assert project.status == FarmProjectStatus.ACTIVE
    assert project.request.request.status == ServiceRequestStatus.IN_PROGRESS


def test_farm_milestone_and_progress_report(customer, administrator):
    farm_request = services.submit_farm_service_request(
        customer=customer, farm_location="Zaria", crop_type="Soy"
    )
    project = services.create_farm_project(farm_request, actor=administrator, name="Soy project")
    services.approve_farm_project(project, actor=administrator, agreement_reference="AGR-1")

    services.add_farm_milestone(project, actor=administrator, title="Plough field")
    assert project.milestones.count() == 1

    with pytest.raises(ValidationError):
        services.add_farm_progress_report(
            farm_request.project,
            actor=administrator,
            title="Wk 1",
            summary="",
            progress_percent=140,
        )

    report = services.add_farm_progress_report(
        farm_request.project,
        actor=administrator,
        title="Week 1",
        summary="Planted",
        progress_percent=25,
    )
    assert report.progress_percent == 25
    assert services.add_farm_progress_report.__name__


# ---------------------------------------------------------------------------
# Marketing (Task 4)
# ---------------------------------------------------------------------------


def test_marketing_enquiry_and_proposal_lifecycle(customer, administrator):
    enquiry = services.submit_marketing_enquiry(
        customer=customer, product_type="Soybean", available_quantity="5"
    )
    proposal = services.create_marketing_proposal(
        enquiry, actor=administrator, title="Sell to processors"
    )
    assert proposal.status == MarketingProposalStatus.DRAFT

    # A campaign cannot exist before the proposal is accepted.
    with pytest.raises(ValidationError):
        services.create_marketing_campaign(enquiry, actor=administrator, name="Launch")

    services.issue_marketing_proposal(proposal, actor=administrator)
    services.decide_marketing_proposal(proposal, actor=customer, accepted=True)
    proposal.refresh_from_db()
    assert proposal.status == MarketingProposalStatus.ACCEPTED

    campaign = services.create_marketing_campaign(enquiry, actor=administrator, name="Launch")
    assert campaign.status == MarketingCampaignStatus.PLANNED
    assert enquiry.request.status == ServiceRequestStatus.IN_PROGRESS

    services.record_marketing_activity(
        campaign,
        actor=administrator,
        occurred_on=timezone.localdate(),
        title="First buyer meeting",
        outcome="Interested",
    )
    campaign.refresh_from_db()
    assert campaign.status == MarketingCampaignStatus.ACTIVE

    services.complete_marketing_campaign(campaign, actor=administrator)
    campaign.refresh_from_db()
    assert campaign.status == MarketingCampaignStatus.COMPLETED


# ---------------------------------------------------------------------------
# Storage & warehousing (Task 5)
# ---------------------------------------------------------------------------


def test_storage_booking_reserves_capacity_and_overbooking_is_rejected(customer, administrator):
    produce = make_produce_type("Maize")
    facility = make_facility(capacity="50.00", accepted=[produce])

    first_request = make_storage_request(customer, produce_type=produce, quantity="30.00")
    start = timezone.localdate() + timedelta(days=1)
    end = start + timedelta(days=10)
    booking = services.create_storage_booking(
        first_request, actor=administrator, facility=facility, start_date=start, end_date=end
    )
    assert booking.status == StorageBookingStatus.REQUESTED
    assert booking.allocations.filter(released_at__isnull=True).count() == 1

    # A second, overlapping booking beyond the remaining 20 is refused.
    second_request = make_storage_request(customer, produce_type=produce, quantity="30.00")
    with pytest.raises(ValidationError):
        services.create_storage_booking(
            second_request, actor=administrator, facility=facility, start_date=start, end_date=end
        )

    # A non-overlapping window is still available.
    later_start = end + timedelta(days=1)
    later_booking = services.create_storage_booking(
        second_request,
        actor=administrator,
        facility=facility,
        start_date=later_start,
        end_date=later_start + timedelta(days=5),
    )
    assert later_booking.pk is not None


def test_unit_capacity_is_enforced(customer, administrator):
    produce = make_produce_type("Rice")
    facility = make_facility(capacity="100.00", accepted=[produce])
    unit = make_storage_unit(facility, capacity="10.00")

    storage_request = make_storage_request(customer, produce_type=produce, quantity="20.00")
    start = timezone.localdate() + timedelta(days=2)
    with pytest.raises(ValidationError):
        services.create_storage_booking(
            storage_request,
            actor=administrator,
            facility=facility,
            unit=unit,
            start_date=start,
            end_date=start + timedelta(days=5),
        )


def test_storage_check_in_and_out(customer, administrator):
    produce = make_produce_type("Sorghum")
    facility = make_facility(capacity="100.00", accepted=[produce])
    storage_request = make_storage_request(customer, produce_type=produce, quantity="40.00")
    start = timezone.localdate() + timedelta(days=1)
    booking = services.create_storage_booking(
        storage_request,
        actor=administrator,
        facility=facility,
        start_date=start,
        end_date=start + timedelta(days=30),
    )
    services.confirm_storage_booking(booking, actor=administrator)

    services.storage_check_in(booking, actor=administrator, quantity="40.00")
    booking.refresh_from_db()
    assert booking.status == StorageBookingStatus.CHECKED_IN

    with pytest.raises(ValidationError):
        services.storage_check_out(booking, actor=administrator, quantity="50.00")

    services.storage_check_out(booking, actor=administrator, quantity="40.00")
    booking.refresh_from_db()
    assert booking.status == StorageBookingStatus.CHECKED_OUT


def test_facility_rejects_unaccepted_produce(customer, administrator):
    accepted = make_produce_type("Maize")
    other = make_produce_type("Cocoa")
    facility = make_facility(capacity="50.00", accepted=[accepted])
    storage_request = make_storage_request(customer, produce_type=other, quantity="10.00")
    start = timezone.localdate() + timedelta(days=1)
    with pytest.raises(ValidationError):
        services.create_storage_booking(
            storage_request,
            actor=administrator,
            facility=facility,
            start_date=start,
            end_date=start + timedelta(days=3),
        )


# ---------------------------------------------------------------------------
# Quotations (Task 6)
# ---------------------------------------------------------------------------


def test_quotation_totals_are_recomputed_server_side(customer, administrator):
    request_obj = make_request(customer)
    quotation = make_quotation(
        customer,
        actor=administrator,
        service_request=request_obj,
        items=[
            {"description": "Survey", "quantity": "2", "unit_price": "10000"},
            {"description": "Report", "quantity": "1", "unit_price": "5000"},
        ],
    )
    assert quotation.subtotal == Decimal("25000.00")
    assert quotation.total == quotation.subtotal + quotation.tax_amount
    assert quotation.status == QuotationStatus.DRAFT
    assert quotation.items.count() == 2

    with pytest.raises(ValidationError):
        services.create_quotation(actor=administrator, customer=customer, items=[])


def test_quotation_workflow_moves_request_and_freezes_on_accept(customer, administrator):
    request_obj = make_request(customer)
    services.review_service_request(request_obj, actor=administrator)
    quotation = make_quotation(customer, actor=administrator, service_request=request_obj)

    services.submit_quotation_for_approval(quotation, actor=administrator)
    quotation.refresh_from_db()
    assert quotation.status == QuotationStatus.PENDING_APPROVAL

    # Cannot issue before approval.
    with pytest.raises(ValidationError):
        services.issue_quotation(quotation, actor=administrator)

    services.approve_quotation(quotation, actor=administrator)
    quotation.refresh_from_db()
    assert quotation.approved_at is not None

    services.issue_quotation(quotation, actor=administrator)
    quotation.refresh_from_db()
    request_obj.refresh_from_db()
    assert quotation.status == QuotationStatus.ISSUED
    assert request_obj.status == ServiceRequestStatus.QUOTED

    services.accept_quotation(quotation, actor=customer)
    quotation.refresh_from_db()
    request_obj.refresh_from_db()
    assert quotation.status == QuotationStatus.ACCEPTED
    assert request_obj.status == ServiceRequestStatus.CONFIRMED

    # Accepted quotations are immutable.
    quotation.total = Decimal("1.00")
    with pytest.raises(ValidationError):
        quotation.save()


def test_only_quotation_capability_can_approve(customer, administrator, consultant_user):
    quotation = make_quotation(customer, actor=administrator)
    services.submit_quotation_for_approval(quotation, actor=administrator)
    with pytest.raises(PermissionDenied):
        services.approve_quotation(quotation, actor=consultant_user)


def test_revise_quotation_supersedes_and_increments(customer, administrator):
    request_obj = make_request(customer)
    quotation = make_quotation(customer, actor=administrator, service_request=request_obj)
    issue_quotation(quotation, actor=administrator)

    services.reject_quotation(quotation, actor=customer, note="Too expensive")
    revision = services.revise_quotation(quotation, actor=administrator)
    assert revision.revision == quotation.revision + 1
    assert revision.supersedes_id == quotation.pk
    assert revision.status == QuotationStatus.DRAFT
    assert revision.items.count() == quotation.items.count()


def test_expire_due_quotations(customer, administrator):
    quotation = make_quotation(
        customer,
        actor=administrator,
        valid_until=timezone.localdate() - timedelta(days=1),
    )
    issue_quotation(quotation, actor=administrator)
    assert services.expire_due_quotations() >= 1
    quotation.refresh_from_db()
    assert quotation.status == QuotationStatus.EXPIRED


# ---------------------------------------------------------------------------
# Verified-payment settlement (Phase 6 integration)
# ---------------------------------------------------------------------------


def test_settle_quotation_payment_activates_paid_storage(customer, administrator):
    produce = make_produce_type("Ginger")
    facility = make_facility(capacity="100.00", accepted=[produce])
    storage_request = make_storage_request(customer, produce_type=produce, quantity="20.00")

    quotation = make_quotation(
        customer,
        actor=administrator,
        service_request=storage_request.request,
        items=[{"description": "Storage", "quantity": "20", "unit_price": "1000"}],
    )
    issue_quotation(quotation, actor=administrator)

    start = timezone.localdate() + timedelta(days=1)
    booking = services.create_storage_booking(
        storage_request,
        actor=administrator,
        facility=facility,
        start_date=start,
        end_date=start + timedelta(days=20),
        quotation=quotation,
    )

    # Unpaid quoted booking cannot be confirmed.
    with pytest.raises(ValidationError):
        services.confirm_storage_booking(booking, actor=administrator)

    payment = Payment.objects.create(
        customer=customer,
        service_quotation=quotation,
        reference=f"PAY-{uuid.uuid4().hex[:12]}",
        expected_amount=quotation.total,
        status=PaymentState.PAID,
    )
    settled = payments.settle_quotation_payment(payment, source="test")
    quotation.refresh_from_db()
    booking.refresh_from_db()

    assert settled.pk == quotation.pk
    assert quotation.payment_status == QuotationPaymentStatus.PAID
    assert quotation.paid_at is not None
    assert quotation.status == QuotationStatus.ACCEPTED  # paying an issued quote accepts it
    assert booking.status == StorageBookingStatus.CONFIRMED

    # Idempotent — a second settlement is a no-op.
    again = payments.settle_quotation_payment(payment, source="retry")
    assert again.pk == quotation.pk
    assert quotation.payments.count() == 1


def test_settle_quotation_payment_ignores_non_quotation_payment():
    class _Stub:
        service_quotation_id = None

    assert payments.settle_quotation_payment(_Stub()) is None


# ---------------------------------------------------------------------------
# Selectors / portal reads
# ---------------------------------------------------------------------------


def test_customer_selectors_are_scoped_to_owner(customer, administrator):
    mine = make_request(customer, title="Mine")
    other = get_user_model().objects.create_user(
        email="other@example.com", password="test-pass-12345", role=UserRole.CUSTOMER
    )
    theirs = make_request(other, title="Theirs")

    assert selectors.customer_service_request(customer, mine.reference).pk == mine.pk
    assert selectors.customer_service_request(customer, theirs.reference) is None
    assert list(selectors.customer_service_requests(customer).values_list("pk", flat=True)) == [
        mine.pk
    ]
    assert mine.pk != theirs.pk


def test_service_overview_metrics_returns_real_counts(customer, administrator):
    make_request(customer, service_type=ServiceType.CONSULTANCY)
    make_request(customer, service_type=ServiceType.STORAGE)
    metrics = selectors.service_overview_metrics()
    assert metrics["total_requests"] >= 2
    division_keys = {row["service_type"] for row in metrics["by_division"]}
    assert ServiceType.CONSULTANCY in division_keys
    assert ServiceType.STORAGE in division_keys


# ---------------------------------------------------------------------------
# Customer portal (Task 8) + staff dashboard (Task 9) views
# ---------------------------------------------------------------------------


def test_customer_portal_requires_login(client):
    response = client.get(reverse("services:service_home"))
    assert response.status_code == 302
    assert "login" in response["Location"]


def test_customer_portal_pages_render(client, customer, administrator):
    request_obj = make_request(customer, title="Render me")
    quotation = make_quotation(customer, actor=administrator, service_request=request_obj)
    issue_quotation(quotation, actor=administrator)

    client.force_login(customer)
    for name, kwargs in [
        ("services:service_home", {}),
        ("services:request_list", {}),
        ("services:quotation_list", {}),
        ("services:request_detail", {"reference": request_obj.reference}),
        ("services:quotation_detail", {"pk": quotation.pk}),
    ]:
        response = client.get(reverse(name, kwargs=kwargs))
        assert response.status_code == 200, name


def test_customer_cannot_view_another_customers_request(client, customer):
    other = get_user_model().objects.create_user(
        email="stranger@example.com", password="test-pass-12345", role=UserRole.CUSTOMER
    )
    request_obj = make_request(other, title="Private")
    client.force_login(customer)
    response = client.get(
        reverse("services:request_detail", kwargs={"reference": request_obj.reference})
    )
    assert response.status_code == 404


def test_dashboard_requires_service_capability(client, customer, administrator):
    client.force_login(customer)
    assert client.get(reverse("services_dashboard:home")).status_code == 403

    client.force_login(administrator)
    assert client.get(reverse("services_dashboard:home")).status_code == 200


def test_dashboard_pages_render_with_data(client, customer, administrator, consultant_user):
    request_obj = make_request(customer, title="Dash request")
    quotation = make_quotation(customer, actor=administrator, service_request=request_obj)
    issue_quotation(quotation, actor=administrator)
    farm_request = services.submit_farm_service_request(
        customer=customer, farm_location="Kaduna", crop_type="Maize"
    )
    project = services.create_farm_project(farm_request, actor=administrator, name="Maize project")
    enquiry = services.submit_marketing_enquiry(
        customer=customer, product_type="Soya", available_quantity="5"
    )
    produce = make_produce_type("Storage maize")
    facility = make_facility(name="Render warehouse", capacity="60.00", accepted=[produce])
    storage_request = make_storage_request(customer, produce_type=produce, quantity="10.00")
    start = timezone.localdate() + timedelta(days=1)
    booking = services.create_storage_booking(
        storage_request,
        actor=administrator,
        facility=facility,
        start_date=start,
        end_date=start + timedelta(days=7),
    )

    client.force_login(administrator)
    pages = [
        ("services_dashboard:home", {}),
        ("services_dashboard:request_list", {}),
        ("services_dashboard:request_detail", {"reference": request_obj.reference}),
        ("services_dashboard:farm_project_list", {}),
        ("services_dashboard:farm_project_detail", {"pk": project.pk}),
        ("services_dashboard:marketing_list", {}),
        ("services_dashboard:marketing_enquiry_detail", {"pk": enquiry.pk}),
        ("services_dashboard:facility_list", {}),
        ("services_dashboard:facility_detail", {"pk": facility.pk}),
        ("services_dashboard:booking_list", {}),
        ("services_dashboard:booking_detail", {"pk": booking.pk}),
        ("services_dashboard:quotation_list", {}),
        ("services_dashboard:quotation_detail", {"pk": quotation.pk}),
        ("services_dashboard:quotation_create", {"reference": request_obj.reference}),
    ]
    for name, kwargs in pages:
        response = client.get(reverse(name, kwargs=kwargs))
        assert response.status_code == 200, name


def test_all_service_url_names_reverse():
    routes = [
        ("services:service_home", {}),
        ("services:request_list", {}),
        ("services:request_detail", {"reference": "AS-SR-TEST"}),
        ("services:quotation_list", {}),
        ("services:quotation_detail", {"pk": uuid.uuid4()}),
        ("services:quotation_pay", {"pk": uuid.uuid4()}),
        ("services:service_payment_callback", {"reference": "AS-QT-1"}),
        ("services:proposal_decide", {"pk": uuid.uuid4()}),
        ("services_dashboard:home", {}),
        ("services_dashboard:request_list", {}),
        ("services_dashboard:request_detail", {"reference": "AS-SR-TEST"}),
        ("services_dashboard:appointment_confirm", {"pk": uuid.uuid4()}),
        ("services_dashboard:appointment_complete", {"pk": uuid.uuid4()}),
        ("services_dashboard:farm_project_list", {}),
        ("services_dashboard:farm_project_create", {"pk": uuid.uuid4()}),
        ("services_dashboard:farm_project_detail", {"pk": uuid.uuid4()}),
        ("services_dashboard:marketing_list", {}),
        ("services_dashboard:marketing_enquiry_detail", {"pk": uuid.uuid4()}),
        ("services_dashboard:facility_list", {}),
        ("services_dashboard:facility_create", {}),
        ("services_dashboard:facility_detail", {"pk": uuid.uuid4()}),
        ("services_dashboard:booking_list", {}),
        ("services_dashboard:booking_create", {"pk": uuid.uuid4()}),
        ("services_dashboard:booking_detail", {"pk": uuid.uuid4()}),
        ("services_dashboard:quotation_list", {}),
        ("services_dashboard:quotation_create", {"reference": "AS-SR-TEST"}),
        ("services_dashboard:quotation_detail", {"pk": uuid.uuid4()}),
    ]
    for name, kwargs in routes:
        assert reverse(name, kwargs=kwargs)

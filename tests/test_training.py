"""Phase 9 — training academy (learning management).

Behaviour under test flows through ``apps.training.services`` (writes,
transitions, capacity enforcement, payment settlement), ``apps.orders.payments``
(the verified-only provider path) and the real URL/view layer for the public
site, the student portal and the staff dashboard. Reads are checked against
``apps.training.selectors``.

Money is ``Decimal``. Every course, session, instructor, qualification and
review in these fixtures is explicitly arranged — nothing is fabricated.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone
from training_helpers import (
    add_mc_question,
    add_short_answer,
    answer_map,
    enroll,
    make_assessment,
    make_category,
    make_course,
    make_instructor,
    make_lesson,
    make_module,
    make_session,
    make_venue,
)

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.orders import payments as order_payments
from apps.orders import paystack
from apps.orders.payment_models import Payment, PaymentState
from apps.training import documents, selectors, services
from apps.training.models import (
    AttendanceStatus,
    CertificateStatus,
    CourseStatus,
    EnrollmentPaymentStatus,
    EnrollmentStatus,
    SessionStatus,
    SubmissionStatus,
    TrainingNotificationLog,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_user(*, email, password="test-pass-12345", role=UserRole.CUSTOMER, **fields):
    is_staff = role != UserRole.CUSTOMER
    user = User.objects.create_user(
        email=email, password=password, role=role, is_staff=is_staff, **fields
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def training_manager(db) -> User:
    return _make_user(
        email="trainer@example.com",
        role=UserRole.TRAINING_MANAGER,
        first_name="Tobi",
        last_name="Adeyemi",
    )


@pytest.fixture
def another_customer(db) -> User:
    return _make_user(email="other@example.com", first_name="Ngozi", last_name="Eze")


@pytest.fixture
def paystack_ngn(settings):
    settings.PAYSTACK_ENABLED = True
    settings.PAYSTACK_SECRET_KEY = "sk_test_1234567890"
    settings.PAYSTACK_WEBHOOK_SECRET = ""
    settings.PAYSTACK_CURRENCY = "NGN"
    return settings


@pytest.fixture
def fake_paystack(monkeypatch):
    state: dict = {}

    def fake_initialize(**kwargs):
        state["initialize"] = kwargs
        return {
            "authorization_url": "https://checkout.paystack.test/training",
            "access_code": "acc_training",
            "reference": kwargs["reference"],
        }

    def fake_verify(reference):
        payload = dict(state.get("verify_payload") or {})
        payload.setdefault("reference", reference)
        payload.setdefault("status", "success")
        payload.setdefault("currency", "NGN")
        return payload

    monkeypatch.setattr(paystack, "initialize_transaction", fake_initialize)
    monkeypatch.setattr(paystack, "verify_transaction", fake_verify)
    return state


def _kobo(amount) -> int:
    return int((Decimal(str(amount)) * 100).to_integral_value())


# ---------------------------------------------------------------------------
# Task 1 — categories
# ---------------------------------------------------------------------------


def test_category_requires_manage_capability(customer, training_manager):
    with pytest.raises(PermissionDenied):
        services.upsert_category(actor=customer, name="Blocked")
    category = services.upsert_category(actor=training_manager, name="Crop Production")
    assert category.pk is not None
    assert category.slug == "crop-production"


def test_category_toggle_and_active_listing(training_manager):
    category = make_category(actor=training_manager)
    services.set_category_active(category, actor=training_manager, active=False)
    category.refresh_from_db()
    assert category.is_active is False
    assert category not in selectors.active_categories()


# ---------------------------------------------------------------------------
# Task 2 — courses, modules, lessons, resources
# ---------------------------------------------------------------------------


def test_course_publication_gate(training_manager, administrator):
    course = make_course(actor=training_manager, publish=False)
    assert course.status == CourseStatus.DRAFT
    assert selectors.published_courses().count() == 0

    # Publishing requires TRAINING_APPROVE, not just manage.
    with pytest.raises(PermissionDenied):
        services.transition_course(course, CourseStatus.PUBLISHED, actor=training_manager)
    services.transition_course(course, CourseStatus.PUBLISHED, actor=administrator)
    course.refresh_from_db()
    assert course.status == CourseStatus.PUBLISHED
    assert course.published_at is not None
    assert course in selectors.published_courses()


def test_illegal_course_transition_rejected(training_manager):
    course = make_course(actor=training_manager)
    with pytest.raises(ValidationError):
        services.transition_course(course, "bogus", actor=training_manager)


def test_lesson_preview_visibility_and_private_access(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    module = make_module(actor=training_manager, course=course)
    public = make_lesson(
        actor=training_manager, module=module, title="Preview", sort_order=1, is_preview=True
    )
    private = make_lesson(actor=training_manager, module=module, title="Members only", sort_order=2)

    assert services.can_access_lesson(None, public) is True
    assert services.can_access_lesson(None, private) is False
    # A non-enrolled authenticated user cannot reach the private lesson.
    assert services.can_access_lesson(customer, private) is False


def test_resource_access_control(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    module = make_module(actor=training_manager, course=course)
    make_lesson(actor=training_manager, module=module)
    resource = services.add_resource(
        actor=training_manager,
        course=course,
        title="Handbook",
        resource_type="document",
        external_url="https://example.test/handbook.pdf",
    )
    assert services.can_access_resource(customer, resource) is False
    assert services.can_access_resource(training_manager, resource) is True

    # A confirmed student on the course may access it.
    session = make_session(actor=training_manager, course=course)
    services.submit_enrollment(student=customer, session=session, actor=customer)
    assert services.can_access_resource(customer, resource) is True


# ---------------------------------------------------------------------------
# Task 3 — instructors & assignments
# ---------------------------------------------------------------------------


def test_instructor_profile_and_assignment(training_manager, staff_user):
    profile = make_instructor(actor=training_manager, user=staff_user)
    assert profile.pk is not None

    # A second profile for the same user is rejected.
    with pytest.raises(ValidationError):
        make_instructor(actor=training_manager, user=staff_user)

    course = make_course(actor=training_manager)
    with pytest.raises(ValidationError):
        services.assign_instructor(instructor=profile, actor=training_manager)

    assignment = services.assign_instructor(
        instructor=profile, actor=training_manager, course=course, role="Lead instructor"
    )
    assert assignment.is_active is True
    assert services.instructor_teaches(staff_user, course=course) is True
    assert services.instructor_teaches(training_manager, course=course) is False


def test_instructor_not_teaching_unrelated_course(training_manager, staff_user):
    profile = make_instructor(actor=training_manager, user=staff_user)
    other = make_course(actor=training_manager)
    assert services.instructor_teaches(staff_user, course=other) is False
    assert profile.assignments.exists() is False


# ---------------------------------------------------------------------------
# Task 4 — venues, sessions, schedules
# ---------------------------------------------------------------------------


def test_session_date_validation(training_manager):
    course = make_course(actor=training_manager)
    today = timezone.localdate()
    with pytest.raises(ValidationError):
        make_session(actor=training_manager, course=course, start_in_days=5, duration_days=-10)
    with pytest.raises(ValidationError):
        services.create_session(
            actor=training_manager,
            course=course,
            start_date=today + timedelta(days=5),
            end_date=today + timedelta(days=6),
            enrollment_deadline=today + timedelta(days=10),
        )


def test_session_status_transitions(training_manager):
    course = make_course(actor=training_manager)
    session = make_session(actor=training_manager, course=course, status=SessionStatus.DRAFT)
    session = services.transition_session(session, SessionStatus.SCHEDULED, actor=training_manager)
    assert session.status == SessionStatus.SCHEDULED
    session = services.transition_session(
        session, SessionStatus.ENROLLMENT_OPEN, actor=training_manager
    )
    assert session.status == SessionStatus.ENROLLMENT_OPEN

    with pytest.raises(ValidationError):
        services.transition_session(session, SessionStatus.DRAFT, actor=training_manager)


def test_session_schedule_entries_and_venue(training_manager):
    course = make_course(actor=training_manager)
    venue = make_venue(actor=training_manager)
    session = make_session(actor=training_manager, course=course, venue=venue)
    entry = services.add_schedule_entry(
        actor=training_manager, session=session, topic="Soil sampling", date=session.start_date
    )
    assert entry.session_id == session.pk


# ---------------------------------------------------------------------------
# Task 5 — enrolment (capacity, waitlist, free/paid)
# ---------------------------------------------------------------------------


def test_free_session_confirms_immediately(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="0")
    enrollment = enroll(student=customer, session=session)
    assert enrollment.status == EnrollmentStatus.CONFIRMED
    assert enrollment.payment_status == EnrollmentPaymentStatus.NOT_REQUIRED
    assert enrollment.balance_due == Decimal("0")
    assert enrollment.confirmed_at is not None


def test_paid_session_awaits_payment(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="15000")
    enrollment = enroll(student=customer, session=session)
    assert enrollment.status == EnrollmentStatus.PAYMENT_PENDING
    assert enrollment.payment_status == EnrollmentPaymentStatus.PENDING
    assert enrollment.balance_due == Decimal("15000")


def test_capacity_enforced_and_waitlist(customer, another_customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, capacity=1, fee="0")
    first = enroll(student=customer, session=session)
    assert first.status == EnrollmentStatus.CONFIRMED

    second = enroll(student=another_customer, session=session)
    assert second.status == EnrollmentStatus.WAITLISTED
    assert session.is_full is True
    assert session.confirmed_seats == 1


def test_paid_capacity_counts_pending_seats(customer, another_customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, capacity=1, fee="1000")
    enroll(student=customer, session=session)
    second = enroll(student=another_customer, session=session)
    assert second.status == EnrollmentStatus.WAITLISTED


def test_duplicate_active_enrollment_blocked(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course)
    enroll(student=customer, session=session)
    with pytest.raises(ValidationError):
        enroll(student=customer, session=session)


def test_enrollment_requires_open_session(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    draft = make_session(actor=training_manager, course=course, status=SessionStatus.DRAFT)
    with pytest.raises(ValidationError):
        enroll(student=customer, session=draft)


def test_enrollment_deadline_enforced(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course)
    session.enrollment_deadline = timezone.localdate() - timedelta(days=1)
    session.save(update_fields=["enrollment_deadline"])
    with pytest.raises(ValidationError):
        enroll(student=customer, session=session)


def test_student_cannot_enrol_for_someone_else(customer, another_customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course)
    with pytest.raises(PermissionDenied):
        services.submit_enrollment(student=customer, session=session, actor=another_customer)


def test_cancel_own_enrollment_frees_seat(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    services.cancel_own_enrollment(enrollment, actor=customer)
    enrollment.refresh_from_db()
    assert enrollment.status == EnrollmentStatus.CANCELLED

    # Cancelling frees the seat, so a new student may confirm.
    replacement = enroll(student=_make_user(email="replacement@example.com"), session=session)
    assert replacement.status == EnrollmentStatus.CONFIRMED


def test_cannot_cancel_another_students_enrollment(customer, another_customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    with pytest.raises(PermissionDenied):
        services.cancel_own_enrollment(enrollment, actor=another_customer)


# ---------------------------------------------------------------------------
# Task 6 — verified-only payment settlement
# ---------------------------------------------------------------------------


def test_initialize_payment_requires_paystack_enabled(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="15000")
    enrollment = enroll(student=customer, session=session)
    with pytest.raises(ValidationError):
        order_payments.initialize_training_payment(
            enrollment, actor=customer, amount=Decimal("15000")
        )


def test_initialize_payment_ownership_and_target(
    customer, another_customer, training_manager, paystack_ngn, fake_paystack
):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="15000")
    enrollment = enroll(student=customer, session=session)

    with pytest.raises(PermissionDenied):
        order_payments.initialize_training_payment(
            enrollment, actor=another_customer, amount=Decimal("15000")
        )

    payment = order_payments.initialize_training_payment(
        enrollment, actor=customer, amount=Decimal("15000")
    )
    assert payment.training_enrollment_id == enrollment.pk
    assert payment.expected_amount == Decimal("15000")
    assert payment.status == PaymentState.PROCESSING
    assert order_payments.latest_authorization_url(payment).startswith(
        "https://checkout.paystack.test"
    )


def test_verified_payment_confirms_enrolment_and_is_idempotent(
    customer, training_manager, paystack_ngn, fake_paystack
):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="15000")
    enrollment = enroll(student=customer, session=session)

    payment = order_payments.initialize_training_payment(
        enrollment, actor=customer, amount=Decimal("15000")
    )
    fake_paystack["verify_payload"] = {"status": "success", "amount": _kobo(15000)}
    verified = order_payments.verify_payment(payment, source="test")
    assert verified.status == PaymentState.PAID
    assert verified.verified_amount == Decimal("15000")

    enrollment.refresh_from_db()
    assert enrollment.status == EnrollmentStatus.CONFIRMED
    assert enrollment.payment_status == EnrollmentPaymentStatus.PAID
    assert enrollment.amount_paid == Decimal("15000")
    assert payment.reference in enrollment.settled_payment_references

    # Re-verifying the same payment never double-counts.
    again = order_payments.verify_payment(payment, source="test")
    assert again.verified_amount == Decimal("15000")
    enrollment.refresh_from_db()
    assert enrollment.amount_paid == Decimal("15000")


def test_partial_payment_keeps_enrolment_pending(customer, training_manager):
    """A partial settlement is applied server-side; enrolment stays pending."""
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="15000")
    enrollment = enroll(student=customer, session=session)
    assert enrollment.balance_due == Decimal("15000")

    payment = Payment.objects.create(
        training_enrollment=enrollment,
        customer=customer,
        reference="AS-PAY-PARTIAL-TEST",
        provider="paystack",
        currency=session.currency,
        expected_amount=Decimal("15000"),
        status=PaymentState.PAID,
        verified_amount=Decimal("5000"),
        purpose="full",
    )
    services.settle_enrollment_payment(enrollment, payment=payment, source="test")

    enrollment.refresh_from_db()
    assert enrollment.status == EnrollmentStatus.PAYMENT_PENDING
    assert enrollment.payment_status == EnrollmentPaymentStatus.PARTIALLY_PAID
    assert enrollment.amount_paid == Decimal("5000")
    assert enrollment.balance_due == Decimal("10000")


def test_settlement_ignores_non_training_payments(
    customer, training_manager, paystack_ngn, fake_paystack
):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="10000")
    enrollment = enroll(student=customer, session=session)
    payment = order_payments.initialize_training_payment(
        enrollment, actor=customer, amount=Decimal("10000")
    )
    # Detach the training target in memory (the DB check keeps exactly one
    # target): settle_training_payment must then be a no-op.
    payment.training_enrollment = None
    from apps.training import payments as training_payments

    assert training_payments.settle_training_payment(payment, source="test") is None


def test_browser_callback_cannot_confirm_payment(
    customer, training_manager, paystack_ngn, fake_paystack, client
):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="15000")
    enrollment = enroll(student=customer, session=session)
    payment = order_payments.initialize_training_payment(
        enrollment, actor=customer, amount=Decimal("15000")
    )

    client.force_login(customer)
    fake_paystack["verify_payload"] = {"status": "failed", "amount": _kobo(0)}
    url = reverse("training:payment_callback", kwargs={"reference": enrollment.reference})
    client.get(url, {"reference": payment.reference})

    enrollment.refresh_from_db()
    assert enrollment.status == EnrollmentStatus.PAYMENT_PENDING
    assert enrollment.payment_status != EnrollmentPaymentStatus.PAID


# ---------------------------------------------------------------------------
# Task 8 — attendance
# ---------------------------------------------------------------------------


def test_attendance_register_requires_trainer(customer, training_manager):
    course = make_course(actor=training_manager)
    session = make_session(actor=training_manager, course=course, status=SessionStatus.IN_PROGRESS)
    with pytest.raises(PermissionDenied):
        services.create_attendance_session(
            actor=customer, session=session, date=timezone.localdate()
        )


def test_attendance_register_and_record(customer, training_manager):
    course = make_course(actor=training_manager)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    assert enrollment.status == EnrollmentStatus.CONFIRMED
    # Move the cohort to delivery now that it has a confirmed student.
    services.transition_session(session, SessionStatus.IN_PROGRESS, actor=training_manager)

    register = services.create_attendance_session(
        actor=training_manager, session=session, date=timezone.localdate(), topic="Field visit"
    )
    with pytest.raises(ValidationError):
        services.create_attendance_session(
            actor=training_manager, session=session, date=timezone.localdate()
        )

    record = services.record_attendance(
        actor=training_manager,
        attendance_session=register,
        enrollment=enrollment,
        status=AttendanceStatus.PRESENT,
    )
    assert record.status == AttendanceStatus.PRESENT

    # A second record for the same student updates rather than duplicates.
    services.record_attendance(
        actor=training_manager,
        attendance_session=register,
        enrollment=enrollment,
        status=AttendanceStatus.LATE,
    )
    enrollment.refresh_from_db()
    summary = selectors.attendance_summary(enrollment)
    assert summary["total"] == 1
    assert summary["attended"] == 1
    assert summary["percentage"] == Decimal("100")


def test_attendance_rejects_unknown_status(customer, training_manager):
    course = make_course(actor=training_manager)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    register = services.create_attendance_session(
        actor=training_manager, session=session, date=timezone.localdate()
    )
    with pytest.raises(ValidationError):
        services.record_attendance(
            actor=training_manager,
            attendance_session=register,
            enrollment=enrollment,
            status="teleported",
        )


# ---------------------------------------------------------------------------
# Task 9 — assessments
# ---------------------------------------------------------------------------


def test_assessment_requires_question_before_publish(training_manager):
    course = make_course(actor=training_manager)
    assessment = make_assessment(actor=training_manager, course=course)
    with pytest.raises(ValidationError):
        services.publish_assessment(assessment, actor=training_manager)


def test_objective_submission_auto_grades_and_passes(customer, training_manager):
    course = make_course(actor=training_manager)
    assessment = make_assessment(actor=training_manager, course=course, max_attempts=2)
    add_mc_question(actor=training_manager, assessment=assessment, prompt="Capital of Nigeria?")
    services.publish_assessment(assessment, actor=training_manager)

    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    questions = list(assessment.questions.all())
    submission = services.submit_assessment(
        enrollment=enrollment,
        assessment=assessment,
        answers=answer_map(questions=questions),
        actor=customer,
    )
    assert submission.status == SubmissionStatus.GRADED
    assert submission.result.passed is True
    assert submission.result.percentage == Decimal("100")


def test_wrong_answer_fails(customer, training_manager):
    course = make_course(actor=training_manager)
    assessment = make_assessment(actor=training_manager, course=course)
    add_mc_question(
        actor=training_manager, assessment=assessment, prompt="Pick", correct_first=True
    )
    services.publish_assessment(assessment, actor=training_manager)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    questions = list(assessment.questions.all())
    submission = services.submit_assessment(
        enrollment=enrollment,
        assessment=assessment,
        answers=answer_map(questions=questions, correct=False),
        actor=customer,
    )
    assert submission.status == SubmissionStatus.GRADED
    assert submission.result.passed is False


def test_submission_limits_and_gates(customer, training_manager):
    course = make_course(actor=training_manager)
    assessment = make_assessment(actor=training_manager, course=course, max_attempts=1)
    add_mc_question(actor=training_manager, assessment=assessment)
    services.publish_assessment(assessment, actor=training_manager)

    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    questions = list(assessment.questions.all())
    services.submit_assessment(
        enrollment=enrollment,
        assessment=assessment,
        answers=answer_map(questions=questions),
        actor=customer,
    )
    with pytest.raises(ValidationError):
        services.submit_assessment(
            enrollment=enrollment,
            assessment=assessment,
            answers=answer_map(questions=questions),
            actor=customer,
        )

    # Only confirmed students may submit.
    paid = make_session(
        actor=training_manager, course=make_course(actor=training_manager, publish=True), fee="5000"
    )
    pending_enrollment = enroll(student=customer, session=paid)
    blocked = make_assessment(actor=training_manager, course=paid.course)
    add_mc_question(actor=training_manager, assessment=blocked)
    services.publish_assessment(blocked, actor=training_manager)
    with pytest.raises(ValidationError):
        services.submit_assessment(
            enrollment=pending_enrollment, assessment=blocked, answers={}, actor=customer
        )


def test_short_answer_requires_manual_grading(customer, training_manager):
    course = make_course(actor=training_manager)
    assessment = make_assessment(actor=training_manager, course=course)
    add_short_answer(actor=training_manager, assessment=assessment, prompt="Explain irrigation")
    services.publish_assessment(assessment, actor=training_manager)

    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    submission = services.submit_assessment(
        enrollment=enrollment, assessment=assessment, answers={}, actor=customer
    )
    assert submission.status == SubmissionStatus.SUBMITTED
    # No score row exists until a member of staff grades the written answer.
    assert not hasattr(submission, "result")

    result = services.grade_submission(
        submission, actor=training_manager, score=Decimal("8"), feedback="Good"
    )
    assert result.score == Decimal("8")
    assert result.passed is True
    submission.refresh_from_db()
    assert submission.status == SubmissionStatus.GRADED


def test_published_assessments_excludes_unpublished(training_manager):
    course = make_course(actor=training_manager)
    draft = make_assessment(actor=training_manager, course=course, title="Draft")
    assert draft not in selectors.published_assessments(course)
    add_mc_question(actor=training_manager, assessment=draft)
    services.publish_assessment(draft, actor=training_manager)
    draft.refresh_from_db()
    assert draft in selectors.published_assessments(course)


# ---------------------------------------------------------------------------
# Task 10 — progress & completion
# ---------------------------------------------------------------------------


def test_lesson_progress_requires_confirmed_student(customer, training_manager):
    course = make_course(actor=training_manager)
    module = make_module(actor=training_manager, course=course)
    lesson = make_lesson(actor=training_manager, module=module)
    session = make_session(actor=training_manager, course=course, fee="5000")
    enrollment = enroll(student=customer, session=session)  # payment pending
    with pytest.raises(ValidationError):
        services.mark_lesson_complete(
            actor=customer, enrollment=enrollment, lesson=lesson, completed=True
        )


def test_progress_recompute_and_completion(customer, training_manager):
    course = make_course(actor=training_manager)
    module = make_module(actor=training_manager, course=course)
    make_lesson(actor=training_manager, module=module, title="L1", sort_order=1)
    make_lesson(actor=training_manager, module=module, title="L2", sort_order=2)
    assessment = make_assessment(actor=training_manager, course=course, completion_required=True)
    add_mc_question(actor=training_manager, assessment=assessment)
    services.publish_assessment(assessment, actor=training_manager)

    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    assert enrollment.status == EnrollmentStatus.CONFIRMED

    lessons = list(selectors.course_lessons(course))
    for lesson in lessons:
        services.mark_lesson_complete(actor=customer, enrollment=enrollment, lesson=lesson)
    questions = list(assessment.questions.all())
    services.submit_assessment(
        enrollment=enrollment,
        assessment=assessment,
        answers=answer_map(questions=questions),
        actor=customer,
    )

    enrollment.refresh_from_db()
    assert enrollment.status == EnrollmentStatus.COMPLETED
    progress = enrollment.progress
    assert progress.total_lessons == 2
    assert progress.completed_lessons == 2
    assert progress.required_assessments == 1
    assert progress.assessments_passed == 1
    assert progress.is_completed is True
    assert services.is_course_complete(enrollment) is True


def test_no_content_never_completes(customer, training_manager):
    course = make_course(actor=training_manager)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    services.recompute_progress(enrollment)
    assert enrollment.progress.is_completed is False


def test_uncompleting_lesson_reverts_progress(customer, training_manager):
    course = make_course(actor=training_manager)
    module = make_module(actor=training_manager, course=course)
    lesson = make_lesson(actor=training_manager, module=module)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    services.mark_lesson_complete(actor=customer, enrollment=enrollment, lesson=lesson)
    enrollment.refresh_from_db()
    assert enrollment.progress.is_completed is True

    services.mark_lesson_complete(
        actor=training_manager, enrollment=enrollment, lesson=lesson, completed=False
    )
    enrollment.refresh_from_db()
    # Progress is recomputed from real records; COMPLETED enrolments are terminal.
    assert enrollment.progress.completed_lessons == 0
    assert enrollment.progress.is_completed is False


# ---------------------------------------------------------------------------
# Task 11 — certificates
# ---------------------------------------------------------------------------


def test_certificate_requires_approve_and_completion(customer, training_manager, administrator):
    course = make_course(actor=training_manager, certificate_eligible=True)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)

    # Not complete -> cannot issue, even for an approver.
    with pytest.raises(ValidationError):
        services.issue_certificate(actor=administrator, enrollment=enrollment)

    # Complete the (empty-content) course by marking completion directly.
    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.completed_at = timezone.now()
    enrollment.save(update_fields=["status", "completed_at"])

    # Approve capability is required.
    with pytest.raises(PermissionDenied):
        services.issue_certificate(actor=training_manager, enrollment=enrollment)

    certificate = services.issue_certificate(actor=administrator, enrollment=enrollment)
    assert certificate.certificate_number.startswith("CERT-")
    assert certificate.status == CertificateStatus.ISSUED
    assert certificate.is_valid is True


def test_certificate_not_eligible_course_blocked(customer, training_manager, administrator):
    course = make_course(actor=training_manager, certificate_eligible=False)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        services.issue_certificate(actor=administrator, enrollment=enrollment)


def test_duplicate_certificate_blocked(customer, training_manager, administrator):
    course = make_course(actor=training_manager, certificate_eligible=True)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.save(update_fields=["status"])
    services.issue_certificate(actor=administrator, enrollment=enrollment)
    with pytest.raises(ValidationError):
        services.issue_certificate(actor=administrator, enrollment=enrollment)


def test_revoke_certificate_and_public_verify(customer, training_manager, administrator):
    course = make_course(actor=training_manager, certificate_eligible=True)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.save(update_fields=["status"])
    certificate = services.issue_certificate(actor=administrator, enrollment=enrollment)

    found = services.verify_certificate(certificate.verification_code)
    assert found is not None and found.is_valid is True

    services.revoke_certificate(certificate, actor=administrator, reason="Data error")
    certificate.refresh_from_db()
    assert certificate.status == CertificateStatus.REVOKED
    assert certificate.is_valid is False
    # Still found by code, but flagged invalid.
    assert services.verify_certificate(certificate.verification_code) is not None


def test_verify_certificate_records_attempt(customer, training_manager, administrator):
    course = make_course(actor=training_manager, certificate_eligible=True)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.save(update_fields=["status"])
    certificate = services.issue_certificate(actor=administrator, enrollment=enrollment)

    assert services.verify_certificate("does-not-exist") is None
    assert selectors.certificate_by_code("does-not-exist") is None
    assert selectors.certificate_by_code(certificate.verification_code) is not None


def test_certificate_pdf_renders(customer, training_manager, administrator):
    course = make_course(actor=training_manager, certificate_eligible=True)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.save(update_fields=["status"])
    certificate = services.issue_certificate(actor=administrator, enrollment=enrollment)
    payload = documents.certificate_pdf(certificate)
    assert payload.startswith(b"%PDF")
    assert certificate.verification_code.encode() in payload


# ---------------------------------------------------------------------------
# Task 12 — public site
# ---------------------------------------------------------------------------


def test_public_course_list_filters_drafts(client, training_manager):
    make_course(actor=training_manager, publish=False)
    published = make_course(actor=training_manager, publish=True, title="Published Course")

    response = client.get(reverse("training:course_list"))
    assert response.status_code == 200
    assert b"Published Course" in response.content
    assert b"Foundation Course" not in response.content  # the draft default title

    detail = client.get(reverse("training:course_detail", kwargs={"slug": published.slug}))
    assert detail.status_code == 200
    assert b"Published Course" in detail.content


def test_public_course_detail_404_for_draft(client, training_manager):
    draft = make_course(actor=training_manager, publish=False)
    response = client.get(reverse("training:course_detail", kwargs={"slug": draft.slug}))
    assert response.status_code == 404


def test_public_category_and_session_pages(client, training_manager):
    category = make_category(actor=training_manager)
    course = make_course(actor=training_manager, category=category, publish=True)
    session = make_session(actor=training_manager, course=course)

    assert client.get(reverse("training:training_home")).status_code == 200
    assert (
        client.get(reverse("training:category_detail", kwargs={"slug": category.slug})).status_code
        == 200
    )
    assert client.get(reverse("training:session_list")).status_code == 200

    detail = client.get(reverse("training:session_detail", kwargs={"pk": session.pk}))
    assert detail.status_code == 200
    assert b"Cohort 1" in detail.content


def test_public_session_detail_hides_unpublished_course(client, training_manager):
    course = make_course(actor=training_manager, publish=False)  # draft
    session = make_session(actor=training_manager, course=course)
    response = client.get(reverse("training:session_detail", kwargs={"pk": session.pk}))
    assert response.status_code == 404


def test_public_certificate_verification(client, customer, training_manager, administrator):
    course = make_course(actor=training_manager, certificate_eligible=True)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.save(update_fields=["status"])
    certificate = services.issue_certificate(actor=administrator, enrollment=enrollment)

    ok = client.get(
        reverse("training:certificate_verify_code", kwargs={"code": certificate.verification_code})
    )
    assert ok.status_code == 200
    assert b"verified" in ok.content.lower()

    missing = client.get(reverse("training:certificate_verify"), {"code": "NO-SUCH-CODE"})
    assert missing.status_code == 200
    assert b"No matching certificate" in missing.content


def test_enroll_view_creates_enrolment(customer, training_manager, client):
    client.force_login(customer)
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, capacity=2)
    response = client.post(reverse("training:enroll", kwargs={"pk": session.pk}))
    assert response.status_code == 302
    enrollment = session.enrollments.get(student=customer)
    assert enrollment is not None
    assert selectors.enrollment_for(customer, enrollment.reference) is not None


def test_enroll_view_requires_login(training_manager, client):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course)
    response = client.post(reverse("training:enroll", kwargs={"pk": session.pk}))
    assert response.status_code == 302
    assert session.enrollments.count() == 0


# ---------------------------------------------------------------------------
# Task 13 — student portal
# ---------------------------------------------------------------------------


def test_student_portal_is_scoped_to_own_records(
    customer, another_customer, training_manager, client
):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course)
    own = enroll(student=customer, session=session)
    other = enroll(student=another_customer, session=session)

    client.force_login(customer)
    assert client.get(reverse("training_account:home")).status_code == 200
    assert (
        client.get(
            reverse("training_account:enrollment_detail", kwargs={"reference": own.reference})
        ).status_code
        == 200
    )

    # Another student's enrolment is invisible (404, never a leak).
    assert (
        client.get(
            reverse("training_account:enrollment_detail", kwargs={"reference": other.reference})
        ).status_code
        == 404
    )
    assert client.get(reverse("training_account:certificate_list")).status_code == 200
    assert client.get(reverse("training_account:payment_history")).status_code == 200


def test_assessment_take_requires_own_confirmed_enrolment(customer, training_manager, client):
    course = make_course(actor=training_manager, publish=True)
    assessment = make_assessment(actor=training_manager, course=course, publish=True)
    add_mc_question(actor=training_manager, assessment=assessment)

    paid = make_session(actor=training_manager, course=course, fee="5000")
    free = make_session(actor=training_manager, course=course, fee="0", start_in_days=14)
    pending = enroll(student=customer, session=paid)
    confirmed = enroll(student=customer, session=free)

    client.force_login(customer)
    # Unconfirmed enrolment cannot take assessments.
    assert (
        client.get(
            reverse(
                "training_account:assessment_take",
                kwargs={"reference": pending.reference, "assessment_id": assessment.pk},
            )
        ).status_code
        == 403
    )
    # Confirmed enrolment can.
    assert (
        client.get(
            reverse(
                "training_account:assessment_take",
                kwargs={"reference": confirmed.reference, "assessment_id": assessment.pk},
            )
        ).status_code
        == 200
    )


def test_resource_download_gate(customer, another_customer, training_manager, client):
    course = make_course(actor=training_manager, publish=True)
    resource = services.add_resource(
        actor=training_manager,
        course=course,
        title="Handbook",
        resource_type="document",
        external_url="https://example.test/h.pdf",
    )
    client.force_login(another_customer)
    response = client.get(reverse("training_account:resource_download", kwargs={"pk": resource.pk}))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Task 14 — notifications
# ---------------------------------------------------------------------------


def test_notifications_are_deduplicated():
    from apps.training import notifications

    assert (
        notifications.notify_once(
            event="training_test",
            dedupe_key="training-test:1",
            to="a@example.com",
            subject="S",
            heading="H",
            intro="I",
        )
        is True
    )
    assert (
        notifications.notify_once(
            event="training_test",
            dedupe_key="training-test:1",
            to="a@example.com",
            subject="S",
            heading="H",
            intro="I",
        )
        is False
    )
    assert TrainingNotificationLog.objects.filter(dedupe_key="training-test:1").count() == 1


def test_enrollment_notification_written(customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course)
    enroll(student=customer, session=session)
    assert TrainingNotificationLog.objects.filter(event="training_enrollment_submitted").exists()


def test_notify_once_without_recipient_is_noop():
    from apps.training import notifications

    assert (
        notifications.notify_once(
            event="training_test",
            dedupe_key="training-test:none",
            to="",
            subject="S",
            heading="H",
            intro="I",
        )
        is False
    )
    assert TrainingNotificationLog.objects.filter(dedupe_key="training-test:none").count() == 0


# ---------------------------------------------------------------------------
# Task 15 — reporting
# ---------------------------------------------------------------------------


def test_report_metrics_separate_requests_from_confirmed(
    customer, another_customer, training_manager
):
    course = make_course(actor=training_manager, publish=True)
    free = make_session(actor=training_manager, course=course, fee="0")
    paid = make_session(actor=training_manager, course=course, fee="10000")
    enroll(student=customer, session=free)
    enroll(student=another_customer, session=paid)

    metrics = selectors.report_metrics()
    assert metrics["total_enrollments"] == 2
    assert metrics["confirmed_students"] == 1  # only the free enrolment confirmed
    assert metrics["pending_enrollments"] == 1


def test_verified_revenue_only_counts_training_payments(
    customer, training_manager, paystack_ngn, fake_paystack
):
    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, fee="12000")
    enrollment = enroll(student=customer, session=session)
    payment = order_payments.initialize_training_payment(
        enrollment, actor=customer, amount=Decimal("12000")
    )
    assert selectors.verified_revenue() == Decimal("0")  # unverified

    fake_paystack["verify_payload"] = {"status": "success", "amount": _kobo(12000)}
    order_payments.verify_payment(payment, source="test")
    assert selectors.verified_revenue() == Decimal("12000")


def test_completion_rate(customer, training_manager):
    course = make_course(actor=training_manager)
    session = make_session(actor=training_manager, course=course)
    enrollment = enroll(student=customer, session=session)
    assert selectors.completion_rate() == Decimal("0")
    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.save(update_fields=["status"])
    assert selectors.completion_rate() == Decimal("100")


def test_course_popularity_counts_confirmed_only(customer, another_customer, training_manager):
    course = make_course(actor=training_manager, publish=True)
    free = make_session(actor=training_manager, course=course, fee="0")
    paid = make_session(actor=training_manager, course=course, fee="10000")
    enroll(student=customer, session=free)
    enroll(student=another_customer, session=paid)

    popular = selectors.course_popularity()
    match = [course_row for course_row in popular if course_row.pk == course.pk]
    assert match
    assert match[0].confirmed == 1


# ---------------------------------------------------------------------------
# Task 16 — staff dashboard permissions
# ---------------------------------------------------------------------------


def test_dashboard_home_capability_gate(client, customer, training_manager):
    assert client.get(reverse("training_dashboard:home")).status_code == 302  # anon -> login
    client.force_login(customer)
    assert client.get(reverse("training_dashboard:home")).status_code == 403
    client.force_login(training_manager)
    assert client.get(reverse("training_dashboard:home")).status_code == 200


def test_course_publish_requires_approve(client, training_manager, administrator):
    course = make_course(actor=training_manager)

    client.force_login(training_manager)
    assert (
        client.post(
            reverse("training_dashboard:course_publish", kwargs={"pk": course.pk})
        ).status_code
        == 403
    )

    client.force_login(administrator)
    response = client.post(reverse("training_dashboard:course_publish", kwargs={"pk": course.pk}))
    assert response.status_code == 302
    course.refresh_from_db()
    assert course.status == CourseStatus.PUBLISHED


def test_certificate_pages_require_approve(client, training_manager, administrator):
    # certificate_list is staff-gated (MANAGE or APPROVE), so managers can see it.
    client.force_login(training_manager)
    assert client.get(reverse("training_dashboard:certificate_list")).status_code == 200
    # certificate_template_list is approve-gated.
    assert client.get(reverse("training_dashboard:certificate_template_list")).status_code == 403

    client.force_login(administrator)
    assert client.get(reverse("training_dashboard:certificate_template_list")).status_code == 200


def test_staff_dashboard_smoke_pages(client, administrator):
    client.force_login(administrator)
    urls = [
        "training_dashboard:home",
        "training_dashboard:category_list",
        "training_dashboard:course_list",
        "training_dashboard:instructor_list",
        "training_dashboard:venue_list",
        "training_dashboard:session_list",
        "training_dashboard:enrollment_list",
        "training_dashboard:attendance_session_list",
        "training_dashboard:assessment_list",
        "training_dashboard:certificate_list",
        "training_dashboard:certificate_template_list",
        "training_dashboard:reports",
    ]
    for name in urls:
        response = client.get(reverse(name))
        assert response.status_code == 200, name


# ---------------------------------------------------------------------------
# Task 17 — Celery reminder
# ---------------------------------------------------------------------------


def test_session_reminder_task_is_idempotent(customer, training_manager):
    from apps.training.tasks import send_session_reminders

    course = make_course(actor=training_manager, publish=True)
    session = make_session(actor=training_manager, course=course, start_in_days=2)
    enroll(student=customer, session=session)

    first = send_session_reminders(within_days=3)
    second = send_session_reminders(within_days=3)
    assert first == 1
    assert second == 0  # date-keyed dedupe prevents repeats


# ---------------------------------------------------------------------------
# Task 18 — URL reversal
# ---------------------------------------------------------------------------


def test_all_training_urls_reverse():
    # URLs that need kwargs
    assert reverse("training:course_detail", kwargs={"slug": "test-course"})
    assert reverse("training:category_detail", kwargs={"slug": "test-category"})
    assert reverse("training:session_detail", kwargs={"pk": "12345678-1234-1234-1234-123456789012"})
    assert reverse("training:enroll", kwargs={"pk": "12345678-1234-1234-1234-123456789012"})
    assert reverse("training:certificate_verify_code", kwargs={"code": "ABC123"})
    assert reverse("training:payment_callback", kwargs={"reference": "ENR-20240101-ABCDEF"})
    assert reverse(
        "training_account:enrollment_detail", kwargs={"reference": "ENR-20240101-ABCDEF"}
    )
    assert reverse(
        "training_account:lesson_complete",
        kwargs={
            "reference": "ENR-20240101-ABCDEF",
            "lesson_id": "12345678-1234-1234-1234-123456789012",
        },
    )
    assert reverse(
        "training_account:assessment_take",
        kwargs={
            "reference": "ENR-20240101-ABCDEF",
            "assessment_id": "12345678-1234-1234-1234-123456789012",
        },
    )
    assert reverse(
        "training_account:resource_download",
        kwargs={"pk": "12345678-1234-1234-1234-123456789012"},
    )
    assert reverse(
        "training_account:certificate_view",
        kwargs={"pk": "12345678-1234-1234-1234-123456789012"},
    )
    assert reverse(
        "training_account:certificate_download",
        kwargs={"pk": "12345678-1234-1234-1234-123456789012"},
    )
    assert reverse("training_account:enrollment_pay", kwargs={"reference": "ENR-20240101-ABCDEF"})
    assert reverse(
        "training_account:enrollment_cancel", kwargs={"reference": "ENR-20240101-ABCDEF"}
    )
    assert reverse(
        "training_dashboard:course_publish",
        kwargs={"pk": "12345678-1234-1234-1234-123456789012"},
    )
    assert reverse(
        "training_dashboard:certificate_issue", kwargs={"reference": "ENR-20240101-ABCDEF"}
    )

    # URLs without kwargs
    names = [
        "training:training_home",
        "training:course_list",
        "training:session_list",
        "training:certificate_verify",
        "training_account:home",
        "training_account:my_courses",
        "training_account:upcoming_sessions",
        "training_account:enrollment_list",
        "training_account:certificate_list",
        "training_account:payment_history",
        "training_dashboard:home",
    ]
    for name in names:
        assert reverse(name), name

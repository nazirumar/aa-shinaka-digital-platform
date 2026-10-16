"""Write layer for the training academy (Tasks 1–13).

Every state change is transaction-safe, validates its own preconditions and is
authorised server-side via capabilities (or an active instructor assignment).
Views and the portal call these functions; they never mutate training models
directly.

Key invariants
-------------
* A course is only publicly visible once **published** by an approver.
* Enrolment capacity is enforced transactionally against confirmed/held seats;
  a pending request is never counted as a confirmed participant.
* A paid enrolment only becomes *confirmed* after a **verified** payment, never
  from a browser callback.
* Attendance records are unique per register and record who marked them.
* A lesson is only complete when the student (or staff) explicitly marks it so.
* A certificate is only issued once the configured completion requirements are
  met, and requires the ``TRAINING_APPROVE`` capability.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability
from apps.core.audit import record_audit
from apps.notifications import events as notification_events

from . import notifications, selectors
from .models import (
    ACTIVE_ENROLLMENT_STATUSES,
    CONFIRMED_ENROLLMENT_STATUSES,
    COURSE_TRANSITIONS,
    ENROLLMENT_TRANSITIONS,
    SESSION_TRANSITIONS,
    Assessment,
    AssessmentOption,
    AssessmentQuestion,
    AssessmentResult,
    AssessmentSubmission,
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
    Certificate,
    CertificateStatus,
    CertificateTemplate,
    Course,
    CourseLesson,
    CourseModule,
    CourseProgress,
    CourseResource,
    CourseStatus,
    Enrollment,
    EnrollmentPaymentStatus,
    EnrollmentStatus,
    InstructorAssignment,
    InstructorProfile,
    LessonProgress,
    SessionStatus,
    SubmissionStatus,
    TrainingCategory,
    TrainingSession,
    TrainingSessionSchedule,
    TrainingVenue,
    generate_reference,
)

logger = logging.getLogger(__name__)

# Attendance percentage required for completion (0 = attendance not required).
COMPLETION_ATTENDANCE_THRESHOLD = Decimal("0")


# ---------------------------------------------------------------------------
# Authorisation helpers
# ---------------------------------------------------------------------------


def _require(actor, *capabilities: str, any_of: bool = False) -> None:
    if not has_capability(actor, *capabilities, any_of=any_of):
        raise PermissionDenied("You do not have permission to perform this action.")


def is_active_instructor(actor) -> bool:
    profile = getattr(actor, "instructor_profile", None)
    return bool(profile and profile.is_active and getattr(actor, "is_active", False))


def instructor_teaches(actor, *, course=None, session=None) -> bool:
    """Whether ``actor`` has an active instructor assignment for a course/session."""
    profile = getattr(actor, "instructor_profile", None)
    if not profile or not profile.is_active:
        return False
    assignments = profile.assignments.filter(is_active=True)
    if session is not None:
        if assignments.filter(session=session).exists():
            return True
        return assignments.filter(course=session.course).exists()
    if course is not None:
        return assignments.filter(course=course).exists()
    return assignments.exists()


def _require_trainer(actor, *, course=None, session=None, capability=Capability.TRAINING_MANAGE):
    if has_capability(actor, capability) or has_capability(actor, Capability.TRAINING_APPROVE):
        return
    if has_capability(actor, Capability.TRAINING_INSTRUCT) and instructor_teaches(
        actor, course=course, session=session
    ):
        return
    raise PermissionDenied("You are not assigned to teach this training.")


def _safe(fn, *args, **kwargs) -> bool:
    try:
        return bool(fn(*args, **kwargs))
    except Exception:  # pragma: no cover - a mail failure must never break a flow
        logger.exception("Training notification failed")
        return False


# ---------------------------------------------------------------------------
# Task 1 — categories
# ---------------------------------------------------------------------------


@transaction.atomic
def upsert_category(
    *, actor, category: TrainingCategory | None = None, **fields
) -> TrainingCategory:
    _require(actor, Capability.TRAINING_MANAGE)
    target = category or TrainingCategory()
    for key, value in fields.items():
        setattr(target, key, value)
    target.full_clean(exclude=["image", "slug", "parent"])
    target.save()
    record_audit(
        actor=actor,
        action="training.category.saved",
        target=target,
        after={"name": target.name, "is_active": target.is_active},
    )
    return target


@transaction.atomic
def set_category_active(category: TrainingCategory, *, actor, active: bool) -> TrainingCategory:
    _require(actor, Capability.TRAINING_MANAGE)
    category.is_active = active
    category.save(update_fields=["is_active", "updated_at"])
    record_audit(
        actor=actor, action="training.category.active", target=category, after={"is_active": active}
    )
    return category


# ---------------------------------------------------------------------------
# Task 2 — courses, modules, lessons, resources
# ---------------------------------------------------------------------------


@transaction.atomic
def create_course(*, actor, **fields) -> Course:
    _require(actor, Capability.TRAINING_MANAGE)
    course = Course(created_by=actor, **fields)
    course.save()
    record_audit(
        actor=actor, action="training.course.created", target=course, after={"title": course.title}
    )
    return course


@transaction.atomic
def update_course(course: Course, *, actor, **fields) -> Course:
    _require(actor, Capability.TRAINING_MANAGE)
    before = {"title": course.title, "status": course.status}
    for key, value in fields.items():
        setattr(course, key, value)
    course.save()
    record_audit(
        actor=actor, action="training.course.updated", target=course, before=before, after=fields
    )
    return course


@transaction.atomic
def _advance_course(course: Course, to_status: str, *, actor) -> Course:
    allowed = COURSE_TRANSITIONS.get(course.status, frozenset())
    if to_status not in allowed:
        raise ValidationError(f"Cannot move this course from '{course.status}' to '{to_status}'.")
    previous = course.status
    course.status = to_status
    update_fields = ["status", "updated_at"]
    if to_status == CourseStatus.PUBLISHED and not course.published_at:
        course.published_at = timezone.now()
        update_fields.append("published_at")
    course.save(update_fields=update_fields)
    record_audit(
        actor=actor,
        action="training.course.status_changed",
        target=course,
        before={"status": previous},
        after={"status": to_status},
    )
    return course


@transaction.atomic
def transition_course(course: Course, to_status: str, *, actor) -> Course:
    _require(actor, Capability.TRAINING_MANAGE, Capability.TRAINING_APPROVE, any_of=True)
    if to_status == CourseStatus.PUBLISHED:
        _require(actor, Capability.TRAINING_APPROVE)
    return _advance_course(course, to_status, actor=actor)


def publish_course(course: Course, *, actor) -> Course:
    return transition_course(course, CourseStatus.PUBLISHED, actor=actor)


def archive_course(course: Course, *, actor) -> Course:
    return transition_course(course, CourseStatus.ARCHIVED, actor=actor)


@transaction.atomic
def add_module(*, actor, course: Course, title: str, description: str = "", sort_order=None):
    _require(actor, Capability.TRAINING_MANAGE)
    if sort_order is None:
        last = course.modules.order_by("-sort_order").first()
        sort_order = (last.sort_order + 1) if last else 1
    module = CourseModule.objects.create(
        course=course, title=title, description=description, sort_order=sort_order
    )
    record_audit(actor=actor, action="training.module.created", target=module)
    return module


@transaction.atomic
def update_module(module: CourseModule, *, actor, **fields) -> CourseModule:
    _require(actor, Capability.TRAINING_MANAGE)
    for key, value in fields.items():
        setattr(module, key, value)
    module.save()
    return module


@transaction.atomic
def add_lesson(module: CourseModule, *, actor, **fields) -> CourseLesson:
    _require(actor, Capability.TRAINING_MANAGE)
    lesson = CourseLesson(module=module, **fields)
    lesson.save()
    record_audit(
        actor=actor, action="training.lesson.created", target=lesson, after={"title": lesson.title}
    )
    return lesson


@transaction.atomic
def update_lesson(lesson: CourseLesson, *, actor, **fields) -> CourseLesson:
    _require(actor, Capability.TRAINING_MANAGE)
    for key, value in fields.items():
        setattr(lesson, key, value)
    lesson.save()
    return lesson


@transaction.atomic
def add_resource(
    *, actor, course: Course, lesson: CourseLesson | None = None, **fields
) -> CourseResource:
    _require(actor, Capability.TRAINING_MANAGE)
    resource = CourseResource(course=course, lesson=lesson, **fields)
    resource.full_clean(exclude=["file"])
    resource.save()
    record_audit(actor=actor, action="training.resource.created", target=resource)
    return resource


def can_access_resource(user, resource: CourseResource) -> bool:
    """Private learning resources are only visible to staff, instructors and
    students with a live enrolment on the course."""
    if not getattr(user, "is_authenticated", False):
        return False
    if has_capability(user, Capability.TRAINING_MANAGE, Capability.TRAINING_APPROVE, any_of=True):
        return True
    if instructor_teaches(user, course=resource.course):
        return True
    return Enrollment.objects.filter(
        student=user,
        session__course=resource.course,
        status__in=CONFIRMED_ENROLLMENT_STATUSES,
    ).exists()


def can_access_lesson(user, lesson: CourseLesson) -> bool:
    if lesson.is_preview:
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    if has_capability(user, Capability.TRAINING_MANAGE, Capability.TRAINING_APPROVE, any_of=True):
        return True
    if instructor_teaches(user, course=lesson.course):
        return True
    return Enrollment.objects.filter(
        student=user,
        session__course=lesson.course,
        status__in=CONFIRMED_ENROLLMENT_STATUSES,
    ).exists()


# ---------------------------------------------------------------------------
# Task 3 — instructors
# ---------------------------------------------------------------------------


@transaction.atomic
def create_instructor_profile(*, actor, user, **fields) -> InstructorProfile:
    _require(actor, Capability.TRAINING_MANAGE)
    if InstructorProfile.objects.filter(user=user).exists():
        raise ValidationError("This user already has an instructor profile.")
    profile = InstructorProfile.objects.create(user=user, **fields)
    record_audit(actor=actor, action="training.instructor.created", target=profile)
    return profile


@transaction.atomic
def update_instructor_profile(profile: InstructorProfile, *, actor, **fields) -> InstructorProfile:
    _require(actor, Capability.TRAINING_MANAGE)
    for key, value in fields.items():
        setattr(profile, key, value)
    profile.save()
    record_audit(actor=actor, action="training.instructor.updated", target=profile, after=fields)
    return profile


@transaction.atomic
def set_instructor_active(profile: InstructorProfile, *, actor, active: bool) -> InstructorProfile:
    _require(actor, Capability.TRAINING_MANAGE)
    profile.is_active = active
    profile.save(update_fields=["is_active", "updated_at"])
    record_audit(
        actor=actor,
        action="training.instructor.status",
        target=profile,
        after={"is_active": active},
    )
    return profile


@transaction.atomic
def assign_instructor(
    *,
    instructor: InstructorProfile,
    actor,
    course: Course | None = None,
    session=None,
    role: str = "",
) -> InstructorAssignment:
    _require(actor, Capability.TRAINING_MANAGE)
    if course is None and session is None:
        raise ValidationError("An assignment needs a course or a session.")
    if session is not None and course is None:
        course = session.course
    assignment, created = InstructorAssignment.objects.get_or_create(
        instructor=instructor,
        course=course,
        session=session,
        defaults={"role": role, "assigned_by": actor, "is_active": True},
    )
    if not created:
        assignment.is_active = True
        assignment.role = role or assignment.role
        assignment.assigned_by = actor
        assignment.save(update_fields=["is_active", "role", "assigned_by", "updated_at"])
    record_audit(actor=actor, action="training.instructor.assigned", target=assignment)
    return assignment


@transaction.atomic
def deactivate_assignment(assignment: InstructorAssignment, *, actor) -> InstructorAssignment:
    _require(actor, Capability.TRAINING_MANAGE)
    assignment.is_active = False
    assignment.save(update_fields=["is_active", "updated_at"])
    record_audit(actor=actor, action="training.instructor.unassigned", target=assignment)
    return assignment


# ---------------------------------------------------------------------------
# Task 4 — sessions
# ---------------------------------------------------------------------------


@transaction.atomic
def upsert_venue(*, actor, venue: TrainingVenue | None = None, **fields) -> TrainingVenue:
    _require(actor, Capability.TRAINING_MANAGE)
    target = venue or TrainingVenue()
    for key, value in fields.items():
        setattr(target, key, value)
    target.save()
    record_audit(actor=actor, action="training.venue.saved", target=target)
    return target


def _validate_session_dates(*, start_date, end_date, enrollment_deadline) -> None:
    if end_date < start_date:
        raise ValidationError("The end date must be on or after the start date.")
    if enrollment_deadline and enrollment_deadline > start_date:
        raise ValidationError("The enrolment deadline must be on or before the start date.")


@transaction.atomic
def create_session(*, actor, course: Course, **fields) -> TrainingSession:
    _require(actor, Capability.TRAINING_MANAGE)
    start_date = fields.get("start_date")
    end_date = fields.get("end_date")
    _validate_session_dates(
        start_date=start_date,
        end_date=end_date,
        enrollment_deadline=fields.get("enrollment_deadline"),
    )
    fields.setdefault("reference", generate_reference("TRN"))
    session = TrainingSession(course=course, created_by=actor, **fields)
    session.save()
    record_audit(actor=actor, action="training.session.created", target=session)
    return session


@transaction.atomic
def update_session(session: TrainingSession, *, actor, **fields) -> TrainingSession:
    _require(actor, Capability.TRAINING_MANAGE)
    start_date = fields.get("start_date", session.start_date)
    end_date = fields.get("end_date", session.end_date)
    enrollment_deadline = fields.get("enrollment_deadline", session.enrollment_deadline)
    _validate_session_dates(
        start_date=start_date, end_date=end_date, enrollment_deadline=enrollment_deadline
    )
    rescheduled = "start_date" in fields and fields["start_date"] != session.start_date
    for key, value in fields.items():
        setattr(session, key, value)
    session.save()
    record_audit(actor=actor, action="training.session.updated", target=session, after=fields)
    if rescheduled:
        for enrollment in session.enrollments.filter(status__in=CONFIRMED_ENROLLMENT_STATUSES):
            _safe(notifications.session_rescheduled, session, enrollment)
    return session


@transaction.atomic
def transition_session(
    session: TrainingSession, to_status: str, *, actor, note: str = ""
) -> TrainingSession:
    _require(actor, Capability.TRAINING_MANAGE)
    allowed = SESSION_TRANSITIONS.get(session.status, frozenset())
    if to_status not in allowed:
        raise ValidationError(f"Cannot move this session from '{session.status}' to '{to_status}'.")
    previous = session.status
    session.status = to_status
    session.save(update_fields=["status", "updated_at"])
    record_audit(
        actor=actor,
        action="training.session.status_changed",
        target=session,
        before={"status": previous},
        after={"status": to_status},
        note=note,
    )
    if to_status == SessionStatus.CANCELLED:
        for enrollment in session.enrollments.filter(status__in=ACTIVE_ENROLLMENT_STATUSES):
            _safe(notifications.training_cancelled, enrollment)
    return session


@transaction.atomic
def add_schedule_entry(*, actor, session: TrainingSession, **fields) -> TrainingSessionSchedule:
    _require(actor, Capability.TRAINING_MANAGE)
    entry = TrainingSessionSchedule(session=session, **fields)
    entry.save()
    record_audit(actor=actor, action="training.schedule.created", target=entry)
    return entry


# ---------------------------------------------------------------------------
# Task 5 — enrolment
# ---------------------------------------------------------------------------


def _session_accepts_enrollment(session: TrainingSession) -> bool:
    if session.status not in {SessionStatus.SCHEDULED, SessionStatus.ENROLLMENT_OPEN}:
        return False
    if session.status == SessionStatus.SCHEDULED:
        # Scheduled sessions must be explicitly opened for enrolment.
        return False
    if session.enrollment_deadline and session.enrollment_deadline < timezone.localdate():
        return False
    return True


@transaction.atomic
def submit_enrollment(
    *, student, session: TrainingSession, actor=None, note: str = "", request=None
) -> Enrollment:
    """Create an enrolment request, enforcing capacity transactionally."""
    actor = actor or student
    if student.id != getattr(actor, "id", None) and not has_capability(
        actor, Capability.TRAINING_MANAGE
    ):
        raise PermissionDenied("You cannot enrol another student.")
    if session.course.status != CourseStatus.PUBLISHED:
        raise ValidationError("This course is not open for enrolment.")
    if not _session_accepts_enrollment(session):
        raise ValidationError("This session is not currently open for enrolment.")

    locked = TrainingSession.objects.select_for_update().get(pk=session.pk)
    if Enrollment.objects.filter(
        student=student, session=locked, status__in=ACTIVE_ENROLLMENT_STATUSES
    ).exists():
        raise ValidationError("You are already enrolled in this session.")

    held = locked.enrollments.filter(status__in=ACTIVE_ENROLLMENT_STATUSES).count()
    waitlisted = bool(locked.capacity) and held >= locked.capacity
    paid = locked.is_paid

    if waitlisted:
        status = EnrollmentStatus.WAITLISTED
        payment_status = EnrollmentPaymentStatus.NOT_REQUIRED
    elif paid:
        status = EnrollmentStatus.PAYMENT_PENDING
        payment_status = EnrollmentPaymentStatus.PENDING
    else:
        status = EnrollmentStatus.CONFIRMED
        payment_status = EnrollmentPaymentStatus.NOT_REQUIRED

    enrollment = Enrollment.objects.create(
        reference=generate_reference("ENR"),
        student=student,
        session=locked,
        status=status,
        payment_status=payment_status,
        confirmed_at=timezone.now() if status == EnrollmentStatus.CONFIRMED else None,
        note=note,
    )
    EnrollmentStatusHistory = _history_model()
    EnrollmentStatusHistory.objects.create(
        enrollment=enrollment, to_status=status, actor=actor, note="Enrolment submitted."
    )
    record_audit(
        actor=actor,
        action="training.enrollment.submitted",
        target=enrollment,
        after={"status": status, "session": locked.reference},
        request=request,
    )
    _safe(notifications.enrollment_submitted, enrollment)
    if status == EnrollmentStatus.CONFIRMED:
        _safe(notifications.enrollment_confirmed, enrollment)
        _safe(notification_events.training_enrollment_confirmed, enrollment)
    return enrollment


def _history_model():
    from .models import EnrollmentStatusHistory

    return EnrollmentStatusHistory


@transaction.atomic
def _advance_enrollment(
    enrollment: Enrollment,
    to_status: str,
    *,
    actor,
    note: str = "",
    request=None,
    enforce_capacity: bool = True,
) -> Enrollment:
    allowed = ENROLLMENT_TRANSITIONS.get(enrollment.status, frozenset())
    if to_status not in allowed:
        raise ValidationError(
            f"Cannot move this enrolment from '{enrollment.status}' to '{to_status}'."
        )
    if to_status == EnrollmentStatus.CONFIRMED and enforce_capacity:
        session = enrollment.session
        if session.capacity:
            held = (
                session.enrollments.filter(status__in=ACTIVE_ENROLLMENT_STATUSES)
                .exclude(pk=enrollment.pk)
                .count()
            )
            if held >= session.capacity:
                raise ValidationError("This session is full — no seat is available to confirm.")
    previous = enrollment.status
    enrollment.status = to_status
    update_fields = ["status", "updated_at"]
    if to_status == EnrollmentStatus.CONFIRMED and not enrollment.confirmed_at:
        enrollment.confirmed_at = timezone.now()
        update_fields.append("confirmed_at")
    if to_status == EnrollmentStatus.CANCELLED:
        enrollment.cancelled_at = timezone.now()
        update_fields.append("cancelled_at")
    if to_status == EnrollmentStatus.COMPLETED:
        enrollment.completed_at = timezone.now()
        update_fields.append("completed_at")
    enrollment.save(update_fields=update_fields)
    _history_model().objects.create(
        enrollment=enrollment, from_status=previous, to_status=to_status, actor=actor, note=note
    )
    record_audit(
        actor=actor,
        action="training.enrollment.status_changed",
        target=enrollment,
        before={"status": previous},
        after={"status": to_status},
        request=request,
    )
    if to_status == EnrollmentStatus.CONFIRMED:
        _safe(notifications.enrollment_confirmed, enrollment)
        _safe(notification_events.training_enrollment_confirmed, enrollment)
    return enrollment


@transaction.atomic
def transition_enrollment(
    enrollment: Enrollment, to_status: str, *, actor, note: str = "", request=None
) -> Enrollment:
    _require(actor, Capability.TRAINING_MANAGE)
    return _advance_enrollment(
        enrollment, to_status, actor=actor, note=note, request=request, enforce_capacity=False
    )


@transaction.atomic
def cancel_own_enrollment(enrollment: Enrollment, *, actor) -> Enrollment:
    if enrollment.student_id != getattr(actor, "id", None) and not has_capability(
        actor, Capability.TRAINING_MANAGE
    ):
        raise PermissionDenied("You cannot cancel this enrolment.")
    if enrollment.status in {EnrollmentStatus.COMPLETED, EnrollmentStatus.CANCELLED}:
        raise ValidationError("This enrolment can no longer be cancelled.")
    return _advance_enrollment(
        enrollment, EnrollmentStatus.CANCELLED, actor=actor, note="Cancelled by student."
    )


@transaction.atomic
def settle_enrollment_payment(
    enrollment: Enrollment, *, payment, source: str = "", request=None
) -> Enrollment:
    """Apply a *verified* payment to an enrolment (idempotent per payment)."""
    amount = Decimal(str(payment.verified_amount or payment.expected_amount or 0))
    if amount <= 0:
        return enrollment
    enrollment = Enrollment.objects.select_for_update().get(pk=enrollment.pk)
    already = _payment_already_applied(enrollment, payment)
    if already:
        return enrollment
    enrollment.amount_paid = (enrollment.amount_paid or Decimal("0")) + amount
    fee = enrollment.session.fee or Decimal("0")
    if enrollment.amount_paid >= fee:
        enrollment.payment_status = EnrollmentPaymentStatus.PAID
    else:
        enrollment.payment_status = EnrollmentPaymentStatus.PARTIALLY_PAID
    references = list(enrollment.settled_payment_references or [])
    reference = str(getattr(payment, "reference", "") or payment.pk)
    if reference not in references:
        references.append(reference)
    enrollment.settled_payment_references = references
    enrollment.save(
        update_fields=[
            "amount_paid",
            "payment_status",
            "settled_payment_references",
            "updated_at",
        ]
    )
    record_audit(
        actor=None,
        action="training.payment.settled",
        target=enrollment,
        after={"amount": str(amount), "paid": str(enrollment.amount_paid), "source": source},
        request=request,
    )
    _safe(notifications.payment_verified, enrollment)
    if (
        enrollment.payment_status == EnrollmentPaymentStatus.PAID
        and enrollment.status == EnrollmentStatus.PAYMENT_PENDING
    ):
        _advance_enrollment(
            enrollment,
            EnrollmentStatus.CONFIRMED,
            actor=None,
            note="Payment verified.",
            enforce_capacity=False,
        )
    return enrollment


def _payment_already_applied(enrollment: Enrollment, payment) -> bool:
    """Whether this verified payment is already reflected in ``amount_paid``."""
    reference = str(getattr(payment, "reference", "") or payment.pk)
    return reference in list(enrollment.settled_payment_references or [])


# ---------------------------------------------------------------------------
# Task 8 — attendance
# ---------------------------------------------------------------------------


@transaction.atomic
def create_attendance_session(
    *, actor, session: TrainingSession, date, topic: str = "", schedule_entry=None
) -> AttendanceSession:
    _require_trainer(actor, session=session)
    register, created = AttendanceSession.objects.get_or_create(
        session=session,
        date=date,
        defaults={"topic": topic, "schedule_entry": schedule_entry, "marked_by": actor},
    )
    if not created:
        raise ValidationError("An attendance register already exists for this date.")
    record_audit(actor=actor, action="training.attendance.register_created", target=register)
    return register


@transaction.atomic
def record_attendance(
    *,
    actor,
    attendance_session: AttendanceSession,
    enrollment: Enrollment,
    status: str,
    note: str = "",
) -> AttendanceRecord:
    """Create or update one attendance record (prevents duplicates)."""
    _require_trainer(actor, session=attendance_session.session)
    if not _valid_attendance_status(status):
        raise ValidationError("Unknown attendance status.")
    if enrollment.session_id != attendance_session.session_id:
        raise ValidationError("This student is not enrolled in the session.")
    record, created = AttendanceRecord.objects.update_or_create(
        attendance_session=attendance_session,
        enrollment=enrollment,
        defaults={
            "status": status,
            "note": note,
            "marked_by": actor,
            "marked_at": timezone.now(),
        },
    )
    record_audit(
        actor=actor,
        action="training.attendance.recorded",
        target=record,
        after={"status": status, "created": created},
    )
    recompute_progress(enrollment)
    return record


def _valid_attendance_status(status: str) -> bool:
    return status in AttendanceStatus.values


def bulk_mark_attendance(*, actor, attendance_session: AttendanceSession, entries) -> int:
    """Mark several students at once. ``entries`` is ``[(enrollment, status, note)]``."""
    count = 0
    for enrollment, status, note in entries:
        record_attendance(
            actor=actor,
            attendance_session=attendance_session,
            enrollment=enrollment,
            status=status,
            note=note or "",
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Task 9 — assessments
# ---------------------------------------------------------------------------


@transaction.atomic
def create_assessment(*, actor, course: Course, **fields) -> Assessment:
    _require(actor, Capability.TRAINING_MANAGE)
    assessment = Assessment(course=course, **fields)
    assessment.save()
    record_audit(actor=actor, action="training.assessment.created", target=assessment)
    return assessment


@transaction.atomic
def add_question(*, actor, assessment: Assessment, **fields) -> AssessmentQuestion:
    _require(actor, Capability.TRAINING_MANAGE)
    question = AssessmentQuestion(assessment=assessment, **fields)
    question.save()
    return question


@transaction.atomic
def add_option(*, actor, question: AssessmentQuestion, **fields) -> AssessmentOption:
    _require(actor, Capability.TRAINING_MANAGE)
    option = AssessmentOption(question=question, **fields)
    option.save()
    return option


@transaction.atomic
def publish_assessment(assessment: Assessment, *, actor) -> Assessment:
    _require(actor, Capability.TRAINING_MANAGE)
    if not assessment.questions.exists():
        raise ValidationError("Add at least one question before publishing.")
    assessment.is_published = True
    assessment.save(update_fields=["is_published", "updated_at"])
    record_audit(actor=actor, action="training.assessment.published", target=assessment)
    for enrollment in Enrollment.objects.filter(
        session__course=assessment.course, status__in=CONFIRMED_ENROLLMENT_STATUSES
    ):
        _safe(notifications.assessment_published, assessment, enrollment)
    return assessment


@transaction.atomic
def submit_assessment(
    *, enrollment: Enrollment, assessment: Assessment, answers: dict, actor
) -> AssessmentSubmission:
    """Submit an attempt; auto-grade objective questions where possible."""
    if enrollment.student_id != getattr(actor, "id", None):
        raise PermissionDenied("You cannot submit this assessment.")
    if enrollment.status not in CONFIRMED_ENROLLMENT_STATUSES:
        raise ValidationError("Only confirmed students can submit assessments.")
    if not assessment.is_published:
        raise ValidationError("This assessment is not available.")
    if assessment.deadline and timezone.now() > assessment.deadline:
        raise ValidationError("The submission deadline has passed.")

    previous = assessment.submissions.filter(enrollment=enrollment).count()
    if assessment.max_attempts and previous >= assessment.max_attempts:
        raise ValidationError("You have reached the maximum number of attempts.")

    score, fully_graded, marks = _grade_auto(enrollment, assessment, answers)
    submission = AssessmentSubmission.objects.create(
        assessment=assessment,
        enrollment=enrollment,
        student=enrollment.student,
        attempt_number=previous + 1,
        answers=answers,
        submitted_at=timezone.now(),
    )
    _store_marks(submission, marks)
    if fully_graded:
        _finalise_result(submission, score=score, graded_by=None)
    else:
        submission.status = SubmissionStatus.SUBMITTED
        submission.save(update_fields=["status", "updated_at"])
    record_audit(actor=actor, action="training.assessment.submitted", target=submission)
    recompute_progress(enrollment)
    return submission


def _grade_auto(enrollment, assessment, answers):
    score = Decimal("0")
    fully_graded = True
    marks: dict[str, dict] = {}
    for question in assessment.questions.all():
        raw = answers.get(str(question.pk))
        if question.question_type == "short_answer":
            fully_graded = False
            marks[str(question.pk)] = {"answer": str(raw or "").strip()}
            continue
        if question.question_type == "multiple_choice":
            selected = str(raw) if raw is not None else ""
            correct = question.options.filter(is_correct=True).first()
            is_correct = bool(correct and selected == str(correct.pk))
        else:  # true_false
            selected = str(raw).lower() if raw is not None else ""
            correct = question.options.filter(is_correct=True).first()
            expected = "true" if (correct and correct.is_correct) else "false"
            is_correct = selected == expected
        marks[str(question.pk)] = {"correct": bool(is_correct)}
        if is_correct:
            score += question.points
    return score, fully_graded, marks


def _store_marks(submission: AssessmentSubmission, marks: dict) -> None:
    data = dict(submission.answers or {})
    data["__marks"] = marks
    submission.answers = data
    submission.save(update_fields=["answers", "updated_at"])


def _finalise_result(submission: AssessmentSubmission, *, score, graded_by) -> AssessmentResult:
    assessment = submission.assessment
    max_score = assessment.max_score or Decimal("0")
    percentage = Decimal("0")
    if max_score:
        percentage = (score / max_score * Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    passed = percentage >= (assessment.passing_score or Decimal("0"))
    submission.score = score
    submission.status = SubmissionStatus.GRADED
    submission.graded_by = graded_by
    submission.graded_at = timezone.now()
    submission.save(update_fields=["score", "status", "graded_by", "graded_at", "updated_at"])
    result, _ = AssessmentResult.objects.update_or_create(
        submission=submission,
        defaults={
            "enrollment": submission.enrollment,
            "assessment": assessment,
            "score": score,
            "max_score": max_score,
            "percentage": percentage,
            "passed": passed,
            "feedback": submission.feedback,
            "graded_by": graded_by,
        },
    )
    _safe(notifications.assessment_result_available, submission)
    return result


@transaction.atomic
def grade_submission(
    submission: AssessmentSubmission, *, actor, score, feedback: str = ""
) -> AssessmentResult:
    """Instructor manual grading of a submission."""
    course = submission.assessment.course
    _require_trainer(actor, course=course)
    score = Decimal(str(score))
    if score < 0:
        raise ValidationError("Score cannot be negative.")
    submission.feedback = feedback
    submission.save(update_fields=["feedback", "updated_at"])
    result = _finalise_result(submission, score=score, graded_by=actor)
    record_audit(
        actor=actor,
        action="training.assessment.graded",
        target=submission,
        after={"score": str(score)},
    )
    recompute_progress(submission.enrollment)
    return result


# ---------------------------------------------------------------------------
# Task 10 — progress
# ---------------------------------------------------------------------------


@transaction.atomic
def mark_lesson_complete(
    *, actor, enrollment: Enrollment, lesson: CourseLesson, completed: bool = True
) -> LessonProgress:
    """Explicitly mark a lesson complete/incomplete (server-side validated)."""
    if enrollment.student_id != getattr(actor, "id", None) and not has_capability(
        actor, Capability.TRAINING_MANAGE
    ):
        raise PermissionDenied("You cannot update this progress.")
    if lesson.module.course_id != enrollment.session.course_id:
        raise ValidationError("This lesson is not part of the enrolled course.")
    if enrollment.status not in CONFIRMED_ENROLLMENT_STATUSES:
        raise ValidationError("Only confirmed students can record progress.")
    progress, _ = LessonProgress.objects.update_or_create(
        enrollment=enrollment,
        lesson=lesson,
        defaults={
            "is_completed": completed,
            "completed_at": timezone.now() if completed else None,
            "last_viewed_at": timezone.now(),
        },
    )
    record_audit(
        actor=actor,
        action="training.progress.lesson",
        target=progress,
        after={"lesson": str(lesson.pk), "completed": completed},
    )
    recompute_progress(enrollment)
    return progress


@transaction.atomic
def record_lesson_view(*, actor, enrollment: Enrollment, lesson: CourseLesson) -> LessonProgress:
    if enrollment.student_id != getattr(actor, "id", None):
        raise PermissionDenied("You cannot update this progress.")
    progress, _ = LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lesson)
    progress.last_viewed_at = timezone.now()
    progress.save(update_fields=["last_viewed_at", "updated_at"])
    return progress


def _completion_satisfied(progress: CourseProgress, attendance_percentage: Decimal) -> bool:
    if not progress.total_lessons and not progress.required_assessments:
        return False
    if progress.total_lessons and progress.completed_lessons < progress.total_lessons:
        return False
    if (
        progress.required_assessments
        and progress.assessments_passed < progress.required_assessments
    ):
        return False
    if COMPLETION_ATTENDANCE_THRESHOLD and attendance_percentage < COMPLETION_ATTENDANCE_THRESHOLD:
        return False
    return True


@transaction.atomic
def recompute_progress(enrollment: Enrollment) -> CourseProgress:
    """Recompute and persist course progress from real records only."""
    course = enrollment.session.course
    lessons = selectors.course_lessons(course)
    total_lessons = len(lessons)
    completed_lessons = enrollment.lesson_progress.filter(is_completed=True).count()

    required = course.assessments.filter(is_published=True, completion_required=True)
    required_count = required.count()
    passed_count = 0
    for assessment in required:
        if enrollment.assessment_results.filter(assessment=assessment, passed=True).exists():
            passed_count += 1

    attendance_percentage = selectors.attendance_summary(enrollment)["percentage"]

    progress, _ = CourseProgress.objects.get_or_create(enrollment=enrollment)
    progress.total_lessons = total_lessons
    progress.completed_lessons = completed_lessons
    progress.required_assessments = required_count
    progress.assessments_passed = passed_count
    progress.attendance_percentage = attendance_percentage

    satisfied = _completion_satisfied(progress, attendance_percentage)
    if satisfied and not progress.is_completed:
        progress.is_completed = True
        progress.completed_at = timezone.now()
    elif not satisfied and progress.is_completed:
        progress.is_completed = False
        progress.completed_at = None
    progress.save()
    if progress.is_completed and enrollment.status == EnrollmentStatus.CONFIRMED:
        _advance_enrollment(
            enrollment, EnrollmentStatus.COMPLETED, actor=None, note="Course completed."
        )
    return progress


def is_course_complete(enrollment: Enrollment) -> bool:
    progress = getattr(enrollment, "progress", None)
    return bool(progress and progress.is_completed)


# ---------------------------------------------------------------------------
# Task 11 — certificates
# ---------------------------------------------------------------------------


@transaction.atomic
def create_certificate_template(*, actor, **fields) -> CertificateTemplate:
    _require(actor, Capability.TRAINING_APPROVE)
    template = CertificateTemplate(**fields)
    template.save()
    record_audit(actor=actor, action="training.certificate_template.created", target=template)
    return template


def certificate_number(prefix: str = "CERT") -> str:
    from secrets import token_hex

    return f"{prefix}-{timezone.now():%Y}-{token_hex(3).upper()}"


@transaction.atomic
def issue_certificate(
    *, actor, enrollment: Enrollment, template: CertificateTemplate | None = None, request=None
) -> Certificate:
    """Issue a certificate. Requires ``TRAINING_APPROVE`` and verified completion."""
    _require(actor, Capability.TRAINING_APPROVE)
    course = enrollment.session.course
    if not course.certificate_eligible:
        raise ValidationError("This course is not certificate eligible.")
    if enrollment.status != EnrollmentStatus.COMPLETED and not is_course_complete(enrollment):
        raise ValidationError("Completion requirements are not yet satisfied.")
    if Certificate.objects.filter(
        student=enrollment.student, course=course, status=CertificateStatus.ISSUED
    ).exists():
        raise ValidationError("A certificate has already been issued for this course.")
    certificate = Certificate.objects.create(
        certificate_number=certificate_number(),
        student=enrollment.student,
        course=course,
        session=enrollment.session,
        enrollment=enrollment,
        template=template,
        issued_by=actor,
    )
    record_audit(
        actor=actor,
        action="training.certificate.issued",
        target=certificate,
        after={"number": certificate.certificate_number},
        request=request,
    )
    _safe(notifications.certificate_issued, certificate)
    _safe(notification_events.certificate_issued, certificate)
    return certificate


@transaction.atomic
def revoke_certificate(certificate: Certificate, *, actor, reason: str) -> Certificate:
    _require(actor, Capability.TRAINING_APPROVE)
    if certificate.status == CertificateStatus.REVOKED:
        raise ValidationError("This certificate is already revoked.")
    certificate.status = CertificateStatus.REVOKED
    certificate.revoked_at = timezone.now()
    certificate.revocation_reason = reason[:300]
    certificate.save(update_fields=["status", "revoked_at", "revocation_reason", "updated_at"])
    record_audit(
        actor=actor,
        action="training.certificate.revoked",
        target=certificate,
        after={"reason": reason},
    )
    return certificate


@transaction.atomic
def verify_certificate(code: str) -> Certificate | None:
    """Public verification; records the attempt and returns the certificate."""
    from .models import CertificateVerificationLog

    certificate = selectors.certificate_by_code(code)
    CertificateVerificationLog.objects.create(
        certificate=certificate if certificate and certificate.is_valid else None,
        code_attempted=(code or "")[:120],
        found=bool(certificate),
    )
    return certificate

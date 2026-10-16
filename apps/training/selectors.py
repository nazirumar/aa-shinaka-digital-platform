"""Read-only queries for the training academy.

Writes live in :mod:`apps.training.services`; these helpers only read. Reporting
deliberately separates enrolment *requests*, *confirmed* students, completed
courses and *verified* revenue — a pending request is never counted as a
confirmed participant, and an unverified payment is never counted as revenue.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from apps.orders.payment_models import Payment, PaymentState

from .models import (
    ACTIVE_ENROLLMENT_STATUSES,
    CONFIRMED_ENROLLMENT_STATUSES,
    Assessment,
    AttendanceRecord,
    AttendanceStatus,
    Certificate,
    CertificateStatus,
    Course,
    CourseLesson,
    CourseResource,
    Enrollment,
    EnrollmentStatus,
    InstructorProfile,
    SessionStatus,
    TrainingCategory,
    TrainingSession,
)

# States that represent captured training money.
_VERIFIED_PAYMENT_STATES = [
    PaymentState.PAID,
    PaymentState.REFUNDED,
    PaymentState.PARTIALLY_REFUNDED,
]


# ---------------------------------------------------------------------------
# Public catalogue
# ---------------------------------------------------------------------------


def active_categories():
    return (
        TrainingCategory.objects.filter(is_active=True)
        .annotate(published_courses=Count("courses", filter=Q(courses__status="published")))
        .order_by("sort_order", "name")
    )


def published_courses(*, category=None, delivery_mode=None, search=""):
    qs = (
        Course.objects.filter(status="published")
        .select_related("category")
        .order_by("sort_order", "title")
    )
    if category is not None:
        qs = qs.filter(category=category)
    if delivery_mode:
        qs = qs.filter(delivery_mode=delivery_mode)
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(short_description__icontains=search))
    return qs


def published_course(slug):
    return Course.objects.filter(slug=slug, status="published").select_related("category").first()


def course_modules(course):
    return course.modules.prefetch_related("lessons").order_by("sort_order")


def course_lessons(course) -> list[CourseLesson]:
    return list(
        CourseLesson.objects.filter(module__course=course)
        .select_related("module")
        .order_by("module__sort_order", "sort_order")
    )


def course_resources(course):
    return course.resources.select_related("lesson").order_by("sort_order", "title")


def upcoming_sessions(*, course=None, limit=None):
    today = timezone.localdate()
    qs = (
        TrainingSession.objects.filter(
            status__in=[
                SessionStatus.SCHEDULED,
                SessionStatus.ENROLLMENT_OPEN,
                SessionStatus.ENROLLMENT_CLOSED,
            ],
            end_date__gte=today,
            course__status="published",
        )
        .select_related("course", "venue")
        .order_by("start_date")
    )
    if course is not None:
        qs = qs.filter(course=course)
    if limit:
        qs = qs[:limit]
    return qs


def session(session_id) -> TrainingSession | None:
    return TrainingSession.objects.select_related("course", "venue").filter(pk=session_id).first()


def sessions_for_course(course):
    return course.sessions.select_related("venue").order_by("start_date")


def active_instructors():
    return (
        InstructorProfile.objects.filter(is_active=True, user__is_active=True)
        .select_related("user")
        .order_by("user__first_name", "user__last_name")
    )


def course_instructors(course):
    return (
        InstructorProfile.objects.filter(
            assignments__course=course, assignments__is_active=True, is_active=True
        )
        .select_related("user")
        .distinct()
    )


def featured_courses(limit: int = 3):
    return published_courses().filter(is_featured=True)[:limit]


# ---------------------------------------------------------------------------
# Student portal
# ---------------------------------------------------------------------------


def enrollments_for(user):
    return (
        Enrollment.objects.filter(student=user)
        .select_related("session", "session__course", "session__venue")
        .order_by("-created_at")
    )


def active_enrollments_for(user):
    return enrollments_for(user).filter(status__in=ACTIVE_ENROLLMENT_STATUSES)


def enrollment_for(user, reference) -> Enrollment | None:
    return (
        Enrollment.objects.filter(student=user, reference=reference)
        .select_related("session", "session__course")
        .first()
    )


def enrollment_by_id(user, pk) -> Enrollment | None:
    return enrollments_for(user).filter(pk=pk).first()


def upcoming_enrollments_for(user):
    today = timezone.localdate()
    return (
        enrollments_for(user)
        .filter(
            status__in=CONFIRMED_ENROLLMENT_STATUSES,
            session__end_date__gte=today,
        )
        .order_by("session__start_date")
    )


def attendance_records_for(enrollment):
    return (
        AttendanceRecord.objects.filter(enrollment=enrollment)
        .select_related("attendance_session")
        .order_by("-attendance_session__date")
    )


def attendance_summary(enrollment) -> dict:
    """Attendance percentage from the session's actual attendance registers.

    A record counts as attended when the student was ``present`` or ``late``.
    The denominator is the number of attendance registers held (never a guess).
    """
    records = list(enrollment.attendance_records.all())
    total = len(records)
    attended = sum(
        1
        for record in records
        if record.status in {AttendanceStatus.PRESENT, AttendanceStatus.LATE}
    )
    percentage = Decimal("0")
    if total:
        percentage = (Decimal(attended) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))
    return {
        "total": total,
        "attended": attended,
        "absent": sum(1 for r in records if r.status == AttendanceStatus.ABSENT),
        "late": sum(1 for r in records if r.status == AttendanceStatus.LATE),
        "excused": sum(1 for r in records if r.status == AttendanceStatus.EXCUSED),
        "percentage": percentage,
    }


def submissions_for(enrollment):
    return (
        enrollment.submissions.select_related("assessment")
        .prefetch_related("result")
        .order_by("-created_at")
    )


def published_assessments(course):
    return (
        Assessment.objects.filter(course=course, is_published=True)
        .prefetch_related("questions")
        .order_by("sort_order", "title")
    )


def certificates_for(user):
    return (
        Certificate.objects.filter(student=user)
        .select_related("course", "session")
        .order_by("-issue_date")
    )


def certificate_for(user, pk) -> Certificate | None:
    return certificates_for(user).filter(pk=pk).first()


def certificate_by_code(code: str) -> Certificate | None:
    if not code:
        return None
    return (
        Certificate.objects.select_related("course", "session", "student")
        .filter(verification_code=code)
        .first()
    )


def lesson_progress_map(enrollment) -> dict:
    return {p.lesson_id: p for p in enrollment.lesson_progress.all()}


def course_progress(enrollment):
    return getattr(enrollment, "progress", None)


# ---------------------------------------------------------------------------
# Staff dashboard
# ---------------------------------------------------------------------------


def staff_courses(*, status=None, category=None, search=""):
    qs = Course.objects.select_related("category").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    if category is not None:
        qs = qs.filter(category=category)
    if search:
        qs = qs.filter(title__icontains=search)
    return qs


def staff_sessions(*, status=None, search=""):
    qs = TrainingSession.objects.select_related("course", "venue").order_by("-start_date")
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(Q(reference__icontains=search) | Q(course__title__icontains=search))
    return qs


def staff_enrollments(*, status=None, search=""):
    qs = Enrollment.objects.select_related("student", "session", "session__course").order_by(
        "-created_at"
    )
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(reference__icontains=search)
            | Q(student__email__icontains=search)
            | Q(session__reference__icontains=search)
        )
    return qs


def staff_certificates(*, status=None, search=""):
    qs = Certificate.objects.select_related("student", "course", "session").order_by("-issue_date")
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(certificate_number__icontains=search)
            | Q(student__email__icontains=search)
            | Q(course__title__icontains=search)
        )
    return qs


def sessions_by_instructor(instructor):
    course_ids = list(
        instructor.assignments.filter(is_active=True, course__isnull=False).values_list(
            "course_id", flat=True
        )
    )
    return TrainingSession.objects.filter(course_id__in=course_ids).select_related("course")


# ---------------------------------------------------------------------------
# Metrics & reports
# ---------------------------------------------------------------------------


def overview_metrics() -> dict:
    return {
        "categories": TrainingCategory.objects.count(),
        "courses": Course.objects.count(),
        "published_courses": Course.objects.filter(status="published").count(),
        "sessions": TrainingSession.objects.count(),
        "upcoming_sessions": upcoming_sessions().count(),
        "enrollments": Enrollment.objects.count(),
        "pending_enrollments": Enrollment.objects.filter(
            status__in=[EnrollmentStatus.PENDING, EnrollmentStatus.PAYMENT_PENDING]
        ).count(),
        "confirmed_students": Enrollment.objects.filter(
            status__in=CONFIRMED_ENROLLMENT_STATUSES
        ).count(),
        "completed_enrollments": Enrollment.objects.filter(
            status=EnrollmentStatus.COMPLETED
        ).count(),
        "certificates": Certificate.objects.filter(status=CertificateStatus.ISSUED).count(),
    }


def verified_revenue(currency: str | None = None) -> Decimal:
    """Revenue from *verified* payments on training enrolments only."""
    qs = Payment.objects.filter(
        training_enrollment__isnull=False, status__in=_VERIFIED_PAYMENT_STATES
    )
    if currency:
        qs = qs.filter(currency=currency)
    total = qs.aggregate(total=Sum("verified_amount"))["total"]
    return total or Decimal("0")


def outstanding_payments() -> Decimal:
    """Expected value of confirmed/paid-pending enrolments not yet covered."""
    total = Decimal("0")
    qs = Enrollment.objects.filter(
        status__in=CONFIRMED_ENROLLMENT_STATUSES,
        payment_status__in=["pending", "partially_paid", "failed"],
    ).select_related("session")
    for enrollment in qs:
        balance = (enrollment.session.fee or Decimal("0")) - (
            enrollment.amount_paid or Decimal("0")
        )
        if balance > 0:
            total += balance
    return total


def course_popularity(limit: int = 10):
    return (
        Course.objects.annotate(
            confirmed=Count(
                "sessions__enrollments",
                filter=Q(sessions__enrollments__status__in=CONFIRMED_ENROLLMENT_STATUSES),
            )
        )
        .filter(confirmed__gt=0)
        .order_by("-confirmed", "title")[:limit]
    )


def completion_rate() -> Decimal:
    finished = Enrollment.objects.filter(
        status__in=[EnrollmentStatus.COMPLETED, EnrollmentStatus.CANCELLED]
    ).count()
    completed = Enrollment.objects.filter(status=EnrollmentStatus.COMPLETED).count()
    if not finished:
        return Decimal("0")
    return (Decimal(completed) / Decimal(finished) * Decimal("100")).quantize(Decimal("0.01"))


def attendance_rate() -> Decimal:
    total = AttendanceRecord.objects.count()
    if not total:
        return Decimal("0")
    attended = AttendanceRecord.objects.filter(
        status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]
    ).count()
    return (Decimal(attended) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))


def enrollment_trend(limit: int = 12):
    return list(
        Enrollment.objects.values("session__course__title")
        .annotate(
            total=Count("id"),
            confirmed=Count("id", filter=Q(status__in=CONFIRMED_ENROLLMENT_STATUSES)),
        )
        .order_by("-total")[:limit]
    )


def report_metrics() -> dict:
    return {
        "total_enrollments": Enrollment.objects.count(),
        "confirmed_students": Enrollment.objects.filter(
            status__in=CONFIRMED_ENROLLMENT_STATUSES
        ).count(),
        "pending_enrollments": Enrollment.objects.filter(
            status__in=[EnrollmentStatus.PENDING, EnrollmentStatus.PAYMENT_PENDING]
        ).count(),
        "upcoming_sessions": upcoming_sessions().count(),
        "completion_rate": completion_rate(),
        "attendance_rate": attendance_rate(),
        "certificates_issued": Certificate.objects.filter(status=CertificateStatus.ISSUED).count(),
        "verified_revenue": verified_revenue(),
        "outstanding_payments": outstanding_payments(),
        "course_popularity": list(course_popularity()),
        "trend": enrollment_trend(),
    }


def average_assessment_score(course) -> Decimal:
    value = Assessment.objects.filter(course=course).aggregate(avg=Avg("results__percentage"))[
        "avg"
    ]
    return Decimal(str(round(value, 2))) if value is not None else Decimal("0")


def resources_visible_to(enrollment):
    """Resources for the enrolled course (student access is ownership-checked)."""
    return CourseResource.objects.filter(course=enrollment.session.course).select_related("lesson")

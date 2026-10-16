"""Training Academy domain models (Phase 9).

The academy is a self-contained learning-management domain: configurable
training categories, courses (modules → lessons → private resources),
instructors, scheduled sessions, enrolments, attendance, assessments, progress
tracking and certificates. It is deliberately separate from the four
service divisions in :mod:`apps.services` (training was deferred out of that
phase) and it reuses the Phase 6 payment infrastructure for settlement rather
than duplicating any provider logic.

Design rules:

* Money is always ``Decimal``. No training fee, deposit or refund policy is ever
  invented — those are staff-entered configuration.
* Course content, instructors and credentials are only ever what a human
  entered. Nothing is fabricated, and no external accreditation is claimed.
* Enrolment capacity is enforced transactionally against **confirmed** seats;
  a pending request is never counted as a confirmed participant.
* Learning resources and assessment answer keys are private; they are only
  served through authorised views.
* A certificate is only issued once the configured completion requirements are
  genuinely satisfied, and it is verifiable by a non-guessable public code.
"""

from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

User = settings.AUTH_USER_MODEL


def generate_reference(prefix: str) -> str:
    """Human-readable, collision-resistant reference (``TRN-XX-YYYYMMDD-XXXXXX``)."""
    return f"{prefix}-{timezone.now():%Y%m%d}-{secrets.token_hex(3).upper()}"


def generate_verification_code() -> str:
    """Non-guessable public certificate verification code."""
    return secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class UUIDTimeStampedModel(models.Model):
    """Timestamped base with a UUID primary key (matches the platform PKs)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


class SluggedMixin(models.Model):
    """Fills ``slug`` from ``title``/``name`` when left blank (unique per model)."""

    slug_source_field = "title"

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self._ensure_slug()
        return super().save(*args, **kwargs)

    def _ensure_slug(self) -> None:
        source = getattr(self, self.slug_source_field, "") or ""
        if self.slug or not source:
            return
        base = slugify(source)[:180] or "item"
        candidate = base
        model = type(self)
        suffix = 2
        while model.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        self.slug = candidate


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CourseStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class DeliveryMode(models.TextChoices):
    IN_PERSON = "in_person", "In person"
    ONLINE = "online", "Online"
    HYBRID = "hybrid", "Hybrid"
    SELF_PACED = "self_paced", "Self-paced"


class LessonType(models.TextChoices):
    TEXT = "text", "Text lesson"
    DOCUMENT = "document", "Document"
    VIDEO = "video", "Video"
    ACTIVITY = "activity", "Practical activity"


class ResourceType(models.TextChoices):
    DOCUMENT = "document", "Document"
    VIDEO = "video", "Video link"
    LINK = "link", "External link"
    IMAGE = "image", "Image"
    OTHER = "other", "Other"


class SessionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SCHEDULED = "scheduled", "Scheduled"
    ENROLLMENT_OPEN = "enrollment_open", "Enrolment open"
    ENROLLMENT_CLOSED = "enrollment_closed", "Enrolment closed"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class EnrollmentStatus(models.TextChoices):
    PENDING = "pending", "Pending review"
    PAYMENT_PENDING = "payment_pending", "Payment pending"
    CONFIRMED = "confirmed", "Confirmed"
    WAITLISTED = "waitlisted", "Waitlisted"
    CANCELLED = "cancelled", "Cancelled"
    COMPLETED = "completed", "Completed"


class EnrollmentPaymentStatus(models.TextChoices):
    NOT_REQUIRED = "not_required", "Not required"
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    PARTIALLY_PAID = "partially_paid", "Partially paid"
    REFUNDED = "refunded", "Refunded"
    FAILED = "failed", "Failed"


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"
    EXCUSED = "excused", "Excused"


class AssessmentType(models.TextChoices):
    QUIZ = "quiz", "Quiz"
    ASSIGNMENT = "assignment", "Assignment"
    PRACTICAL = "practical", "Practical assessment"
    EXAM = "exam", "Examination"


class QuestionType(models.TextChoices):
    MULTIPLE_CHOICE = "multiple_choice", "Multiple choice"
    TRUE_FALSE = "true_false", "True / false"
    SHORT_ANSWER = "short_answer", "Short answer"


class SubmissionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    GRADED = "graded", "Graded"
    RETURNED = "returned", "Returned"


class CertificateStatus(models.TextChoices):
    ISSUED = "issued", "Issued"
    REVOKED = "revoked", "Revoked"


# Enrolment states that still hold a place or await one on a session.
ACTIVE_ENROLLMENT_STATUSES = frozenset(
    {EnrollmentStatus.PENDING, EnrollmentStatus.PAYMENT_PENDING, EnrollmentStatus.CONFIRMED}
)
# Enrolment states that count as a confirmed participant (capacity + reporting).
CONFIRMED_ENROLLMENT_STATUSES = frozenset({EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED})


COURSE_TRANSITIONS: dict[str, frozenset[str]] = {
    CourseStatus.DRAFT: frozenset({CourseStatus.PUBLISHED, CourseStatus.ARCHIVED}),
    CourseStatus.PUBLISHED: frozenset({CourseStatus.DRAFT, CourseStatus.ARCHIVED}),
    CourseStatus.ARCHIVED: frozenset({CourseStatus.DRAFT, CourseStatus.PUBLISHED}),
}


SESSION_TRANSITIONS: dict[str, frozenset[str]] = {
    SessionStatus.DRAFT: frozenset({SessionStatus.SCHEDULED, SessionStatus.CANCELLED}),
    SessionStatus.SCHEDULED: frozenset(
        {SessionStatus.ENROLLMENT_OPEN, SessionStatus.ENROLLMENT_CLOSED, SessionStatus.CANCELLED}
    ),
    SessionStatus.ENROLLMENT_OPEN: frozenset(
        {SessionStatus.ENROLLMENT_CLOSED, SessionStatus.IN_PROGRESS, SessionStatus.CANCELLED}
    ),
    SessionStatus.ENROLLMENT_CLOSED: frozenset(
        {SessionStatus.IN_PROGRESS, SessionStatus.ENROLLMENT_OPEN, SessionStatus.CANCELLED}
    ),
    SessionStatus.IN_PROGRESS: frozenset({SessionStatus.COMPLETED, SessionStatus.CANCELLED}),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.CANCELLED: frozenset(),
}


ENROLLMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    EnrollmentStatus.PENDING: frozenset(
        {
            EnrollmentStatus.PAYMENT_PENDING,
            EnrollmentStatus.CONFIRMED,
            EnrollmentStatus.WAITLISTED,
            EnrollmentStatus.CANCELLED,
        }
    ),
    EnrollmentStatus.PAYMENT_PENDING: frozenset(
        {
            EnrollmentStatus.CONFIRMED,
            EnrollmentStatus.WAITLISTED,
            EnrollmentStatus.CANCELLED,
        }
    ),
    EnrollmentStatus.CONFIRMED: frozenset({EnrollmentStatus.COMPLETED, EnrollmentStatus.CANCELLED}),
    EnrollmentStatus.WAITLISTED: frozenset(
        {EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED, EnrollmentStatus.CANCELLED}
    ),
    EnrollmentStatus.COMPLETED: frozenset(),
    EnrollmentStatus.CANCELLED: frozenset(),
}


# ---------------------------------------------------------------------------
# Task 1 — training categories
# ---------------------------------------------------------------------------


class TrainingCategory(SluggedMixin, UUIDTimeStampedModel):
    """A configurable training category (never a hardcoded list)."""

    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="training/categories/", blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    sort_order = models.IntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    slug_source_field = "name"

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name = "Training category"
        verbose_name_plural = "Training categories"

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Task 2 — courses, modules, lessons, resources
# ---------------------------------------------------------------------------


class Course(SluggedMixin, UUIDTimeStampedModel):
    """A training course. Publication state gates public visibility."""

    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.ForeignKey(
        TrainingCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="courses",
    )
    short_description = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    learning_objectives = models.TextField(
        blank=True, help_text="One objective per line; staff-entered only."
    )
    prerequisites = models.TextField(blank=True)
    duration_hours = models.DecimalField(
        max_digits=6, decimal_places=1, default=0, validators=[MinValueValidator(0)]
    )
    delivery_mode = models.CharField(
        max_length=16, choices=DeliveryMode.choices, default=DeliveryMode.IN_PERSON
    )
    featured_image = models.ImageField(upload_to="training/courses/", blank=True)
    status = models.CharField(
        max_length=16, choices=CourseStatus.choices, default=CourseStatus.DRAFT, db_index=True
    )
    certificate_eligible = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False, db_index=True)
    sort_order = models.IntegerField(default=0, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="courses_created",
    )

    class Meta:
        ordering = ("sort_order", "-published_at", "title")
        indexes = [models.Index(fields=["status", "is_featured"])]

    def __str__(self) -> str:
        return self.title

    @property
    def is_live(self) -> bool:
        if self.status != CourseStatus.PUBLISHED:
            return False
        return self.published_at is None or self.published_at <= timezone.now()

    @property
    def objectives_list(self) -> list[str]:
        return [
            line.strip() for line in (self.learning_objectives or "").splitlines() if line.strip()
        ]


class CourseModule(UUIDTimeStampedModel):
    """An ordered module within a course."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=220)
    description = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0, db_index=True)

    class Meta:
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["course", "sort_order"], name="uniq_course_module_order"
            )
        ]

    def __str__(self) -> str:
        return f"{self.course.title} · {self.title}"


class CourseLesson(UUIDTimeStampedModel):
    """An ordered lesson inside a module."""

    module = models.ForeignKey(CourseModule, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=220)
    lesson_type = models.CharField(
        max_length=16, choices=LessonType.choices, default=LessonType.TEXT
    )
    content_text = models.TextField(blank=True)
    video_url = models.URLField(blank=True)
    is_preview = models.BooleanField(
        default=False, help_text="Preview lessons are visible to signed-out visitors."
    )
    estimated_minutes = models.PositiveIntegerField(default=0)
    sort_order = models.IntegerField(default=0, db_index=True)

    class Meta:
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["module", "sort_order"], name="uniq_lesson_module_order"
            )
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def course(self) -> Course:
        return self.module.course


class CourseResource(UUIDTimeStampedModel):
    """A private learning resource attached to a course or a lesson."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="resources")
    lesson = models.ForeignKey(
        CourseLesson,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="resources",
    )
    title = models.CharField(max_length=220)
    resource_type = models.CharField(
        max_length=16, choices=ResourceType.choices, default=ResourceType.DOCUMENT
    )
    file = models.FileField(upload_to="training/resources/%Y/%m/", blank=True)
    external_url = models.URLField(blank=True)
    description = models.TextField(blank=True)
    is_downloadable = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0, db_index=True)

    class Meta:
        ordering = ("sort_order", "created_at")

    def __str__(self) -> str:
        return self.title


# ---------------------------------------------------------------------------
# Task 3 — instructors
# ---------------------------------------------------------------------------


class InstructorProfile(UUIDTimeStampedModel):
    """A staff instructor profile. Only staff-entered, verifiable details."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="instructor_profile")
    professional_title = models.CharField(max_length=180, blank=True)
    biography = models.TextField(blank=True)
    expertise = models.TextField(blank=True, help_text="Comma-separated areas of expertise.")
    profile_image = models.ImageField(upload_to="training/instructors/", blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ("user__first_name", "user__last_name")
        verbose_name = "Instructor profile"

    def __str__(self) -> str:
        return f"{self.user.full_name or self.user.email} — {self.professional_title}".strip(" —")

    @property
    def expertise_list(self) -> list[str]:
        return [part.strip() for part in (self.expertise or "").split(",") if part.strip()]


class InstructorAssignment(UUIDTimeStampedModel):
    """Assigns an instructor to a course and/or a specific session."""

    instructor = models.ForeignKey(
        InstructorProfile, on_delete=models.CASCADE, related_name="assignments"
    )
    course = models.ForeignKey(
        Course,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="instructor_assignments",
    )
    session = models.ForeignKey(
        "TrainingSession",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="instructor_assignments",
    )
    role = models.CharField(
        max_length=120, blank=True, help_text="e.g. Lead instructor, Assistant."
    )
    is_active = models.BooleanField(default=True, db_index=True)
    assigned_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="instructor_assignments_made",
    )

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=Q(course__isnull=False) | Q(session__isnull=False),
                name="chk_instructor_assignment_target",
            ),
            models.UniqueConstraint(
                fields=["instructor", "course"],
                condition=Q(course__isnull=False),
                name="uniq_instructor_course",
            ),
            models.UniqueConstraint(
                fields=["instructor", "session"],
                name="uniq_instructor_session",
            ),
        ]

    def __str__(self) -> str:
        target = self.session or self.course
        return f"{self.instructor} → {target}"


# ---------------------------------------------------------------------------
# Task 4 — sessions
# ---------------------------------------------------------------------------


class TrainingVenue(UUIDTimeStampedModel):
    """A physical training venue."""

    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.ForeignKey(
        "locations.State",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_venues",
    )
    capacity = models.PositiveIntegerField(default=0)
    facilities = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class TrainingSession(UUIDTimeStampedModel):
    """A scheduled delivery of a course (cohort)."""

    reference = models.CharField(max_length=60, unique=True, db_index=True)
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="sessions")
    title = models.CharField(max_length=220, blank=True)
    venue = models.ForeignKey(
        TrainingVenue,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions",
    )
    delivery_mode = models.CharField(
        max_length=16, choices=DeliveryMode.choices, default=DeliveryMode.IN_PERSON
    )
    start_date = models.DateField()
    end_date = models.DateField()
    enrollment_deadline = models.DateField(null=True, blank=True)
    capacity = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    min_participants = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(
        max_length=20, choices=SessionStatus.choices, default=SessionStatus.DRAFT, db_index=True
    )
    location_notes = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions_created",
    )

    class Meta:
        ordering = ("start_date", "reference")
        indexes = [models.Index(fields=["status", "start_date"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="chk_session_end_after_start",
            ),
            models.CheckConstraint(condition=Q(fee__gte=0), name="chk_session_fee_nonneg"),
        ]

    def __str__(self) -> str:
        return self.title or f"{self.course.title} ({self.reference})"

    @property
    def is_paid(self) -> bool:
        return self.fee is not None and self.fee > 0

    @property
    def is_full(self) -> bool:
        if not self.capacity:
            return False
        return self.confirmed_seats >= self.capacity

    @property
    def confirmed_seats(self) -> int:
        return self.enrollments.filter(status__in=CONFIRMED_ENROLLMENT_STATUSES).count()

    @property
    def active_seats(self) -> int:
        return self.enrollments.filter(status__in=ACTIVE_ENROLLMENT_STATUSES).count()


class TrainingSessionSchedule(UUIDTimeStampedModel):
    """A dated class meeting within a session (used for attendance)."""

    session = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name="schedule")
    topic = models.CharField(max_length=220)
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    is_cancelled = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0, db_index=True)

    class Meta:
        ordering = ("date", "sort_order")
        constraints = [
            models.UniqueConstraint(
                fields=["session", "date", "sort_order"], name="uniq_session_schedule_entry"
            )
        ]

    def __str__(self) -> str:
        return f"{self.session.reference} · {self.date} · {self.topic}"


# ---------------------------------------------------------------------------
# Task 5 — enrolment
# ---------------------------------------------------------------------------


class Enrollment(UUIDTimeStampedModel):
    """A student's enrolment in one training session."""

    reference = models.CharField(max_length=60, unique=True, db_index=True)
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="enrollments")
    session = models.ForeignKey(
        TrainingSession, on_delete=models.PROTECT, related_name="enrollments"
    )
    status = models.CharField(
        max_length=20,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.PENDING,
        db_index=True,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=EnrollmentPaymentStatus.choices,
        default=EnrollmentPaymentStatus.NOT_REQUIRED,
        db_index=True,
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    settled_payment_references = models.JSONField(
        default=list,
        blank=True,
        editable=False,
        help_text="Payment references already applied to this enrolment (idempotency).",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0), name="chk_enrollment_paid_nonneg"
            ),
            models.UniqueConstraint(
                fields=["student", "session"],
                condition=~Q(status=EnrollmentStatus.CANCELLED),
                name="uniq_active_enrollment",
            ),
        ]
        indexes = [models.Index(fields=["session", "status"])]

    def __str__(self) -> str:
        return f"{self.reference} · {self.student}"

    @property
    def balance_due(self):
        from decimal import Decimal

        return (self.session.fee or Decimal("0")) - (self.amount_paid or Decimal("0"))

    @property
    def is_confirmed(self) -> bool:
        return self.status in CONFIRMED_ENROLLMENT_STATUSES


class EnrollmentStatusHistory(models.Model):
    """Audit trail of enrolment status transitions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=EnrollmentStatus.choices)
    actor = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="enrollment_status_changes",
    )
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.enrollment_id}: {self.from_status} → {self.to_status}"


class EnrollmentRequirement(UUIDTimeStampedModel):
    """A prerequisite / document requirement for a course or session."""

    course = models.ForeignKey(
        Course,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="enrollment_requirements",
    )
    session = models.ForeignKey(
        TrainingSession,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="enrollment_requirements",
    )
    label = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_required = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0, db_index=True)

    class Meta:
        ordering = ("sort_order", "label")
        constraints = [
            models.CheckConstraint(
                condition=Q(course__isnull=False) | Q(session__isnull=False),
                name="chk_enrollment_requirement_target",
            )
        ]

    def __str__(self) -> str:
        return self.label


# ---------------------------------------------------------------------------
# Task 8 — attendance
# ---------------------------------------------------------------------------


class AttendanceSession(UUIDTimeStampedModel):
    """A dated attendance register for a training session."""

    session = models.ForeignKey(
        TrainingSession, on_delete=models.CASCADE, related_name="attendance_sessions"
    )
    schedule_entry = models.ForeignKey(
        TrainingSessionSchedule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attendance_sessions",
    )
    topic = models.CharField(max_length=220, blank=True)
    date = models.DateField()
    marked_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attendance_sessions_marked",
    )

    class Meta:
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(fields=["session", "date"], name="uniq_attendance_session_date")
        ]

    def __str__(self) -> str:
        return f"{self.session.reference} · {self.date}"


class AttendanceRecord(UUIDTimeStampedModel):
    """One student's attendance for one attendance session."""

    attendance_session = models.ForeignKey(
        AttendanceSession, on_delete=models.CASCADE, related_name="records"
    )
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="attendance_records"
    )
    status = models.CharField(
        max_length=10, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT
    )
    note = models.CharField(max_length=200, blank=True)
    marked_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attendance_records_marked",
    )
    marked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["attendance_session", "enrollment"],
                name="uniq_attendance_record",
            )
        ]

    def __str__(self) -> str:
        return f"{self.enrollment.reference} · {self.get_status_display()}"


# ---------------------------------------------------------------------------
# Task 9 — assessments
# ---------------------------------------------------------------------------


class Assessment(UUIDTimeStampedModel):
    """A quiz, assignment, practical or exam attached to a course."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="assessments")
    module = models.ForeignKey(
        CourseModule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assessments",
    )
    title = models.CharField(max_length=220)
    assessment_type = models.CharField(
        max_length=16, choices=AssessmentType.choices, default=AssessmentType.QUIZ
    )
    description = models.TextField(blank=True)
    passing_score = models.DecimalField(
        max_digits=6, decimal_places=2, default=50, validators=[MinValueValidator(0)]
    )
    max_attempts = models.PositiveIntegerField(default=1)
    deadline = models.DateTimeField(null=True, blank=True)
    is_published = models.BooleanField(default=False, db_index=True)
    completion_required = models.BooleanField(
        default=True, help_text="Must be passed for course completion (when published)."
    )
    sort_order = models.IntegerField(default=0, db_index=True)

    class Meta:
        ordering = ("sort_order", "title")

    def __str__(self) -> str:
        return f"{self.course.title} · {self.title}"

    @property
    def max_score(self):
        total = self.questions.aggregate(total=models.Sum("points"))["total"]
        return total or 0


class AssessmentQuestion(UUIDTimeStampedModel):
    """A question within an assessment. Answer keys are never public."""

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="questions")
    question_type = models.CharField(
        max_length=20, choices=QuestionType.choices, default=QuestionType.MULTIPLE_CHOICE
    )
    prompt = models.TextField()
    points = models.DecimalField(
        max_digits=6, decimal_places=2, default=1, validators=[MinValueValidator(0)]
    )
    correct_answer = models.TextField(
        blank=True, help_text="Answer key for short-answer/true-false questions."
    )
    explanation = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0, db_index=True)

    class Meta:
        ordering = ("sort_order", "created_at")

    def __str__(self) -> str:
        return self.prompt[:80]


class AssessmentOption(UUIDTimeStampedModel):
    """An option for a multiple-choice / true-false question."""

    question = models.ForeignKey(
        AssessmentQuestion, on_delete=models.CASCADE, related_name="options"
    )
    text = models.CharField(max_length=400)
    is_correct = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0, db_index=True)

    class Meta:
        ordering = ("sort_order", "created_at")

    def __str__(self) -> str:
        return self.text[:80]


class AssessmentSubmission(UUIDTimeStampedModel):
    """A student's attempt at an assessment."""

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="submissions")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="assessment_submissions"
    )
    attempt_number = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=12, choices=SubmissionStatus.choices, default=SubmissionStatus.DRAFT
    )
    answers = models.JSONField(default=dict, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    graded_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submissions_graded",
    )
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "enrollment", "attempt_number"],
                name="uniq_assessment_attempt",
            )
        ]

    def __str__(self) -> str:
        return f"{self.enrollment.reference} · {self.assessment.title} #{self.attempt_number}"

    @property
    def is_graded(self) -> bool:
        return self.status == SubmissionStatus.GRADED


class AssessmentResult(UUIDTimeStampedModel):
    """The derived, published result of a graded submission."""

    submission = models.OneToOneField(
        AssessmentSubmission, on_delete=models.CASCADE, related_name="result"
    )
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="assessment_results"
    )
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="results")
    score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    max_score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    passed = models.BooleanField(default=False)
    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="results_graded",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.assessment.title} · {self.percentage}%"


# ---------------------------------------------------------------------------
# Task 10 — progress
# ---------------------------------------------------------------------------


class LessonProgress(UUIDTimeStampedModel):
    """A student's progress through a single lesson."""

    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="lesson_progress"
    )
    lesson = models.ForeignKey(
        CourseLesson, on_delete=models.CASCADE, related_name="progress_records"
    )
    is_completed = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(fields=["enrollment", "lesson"], name="uniq_lesson_progress")
        ]

    def __str__(self) -> str:
        return f"{self.enrollment.reference} · {self.lesson.title}"


class CourseProgress(UUIDTimeStampedModel):
    """Aggregate progress for an enrolment (derived and maintained server-side)."""

    enrollment = models.OneToOneField(Enrollment, on_delete=models.CASCADE, related_name="progress")
    completed_lessons = models.PositiveIntegerField(default=0)
    total_lessons = models.PositiveIntegerField(default=0)
    assessments_passed = models.PositiveIntegerField(default=0)
    required_assessments = models.PositiveIntegerField(default=0)
    attendance_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_completed = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Course progress"
        verbose_name_plural = "Course progress"

    def __str__(self) -> str:
        return f"{self.enrollment.reference} · {self.percentage}%"


# ---------------------------------------------------------------------------
# Task 11 — certificates
# ---------------------------------------------------------------------------


class CertificateTemplate(UUIDTimeStampedModel):
    """A reusable certificate design. No accreditation is implied."""

    name = models.CharField(max_length=160, unique=True)
    title = models.CharField(max_length=200, default="Certificate of Completion")
    body_text = models.TextField(
        blank=True,
        help_text="Optional wording; placeholders {student}, {course}, {session}, {date}.",
    )
    footer_text = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Certificate(UUIDTimeStampedModel):
    """An issued certificate. Only issued once completion is verified."""

    certificate_number = models.CharField(max_length=60, unique=True, db_index=True)
    verification_code = models.CharField(
        max_length=80, unique=True, default=generate_verification_code, db_index=True
    )
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="certificates")
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="certificates")
    session = models.ForeignKey(
        TrainingSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="certificates",
    )
    enrollment = models.ForeignKey(
        Enrollment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="certificates",
    )
    template = models.ForeignKey(
        CertificateTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="certificates",
    )
    issue_date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=10, choices=CertificateStatus.choices, default=CertificateStatus.ISSUED
    )
    issued_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="certificates_issued",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ("-issue_date", "-created_at")

    def __str__(self) -> str:
        return self.certificate_number

    @property
    def is_valid(self) -> bool:
        return self.status == CertificateStatus.ISSUED


class CertificateVerificationLog(models.Model):
    """Records public verification attempts (minimal, privacy-conscious)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    certificate = models.ForeignKey(
        Certificate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verification_logs",
    )
    code_attempted = models.CharField(max_length=120)
    found = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.code_attempted


# ---------------------------------------------------------------------------
# Notifications (dedupe)
# ---------------------------------------------------------------------------


class TrainingNotificationLog(models.Model):
    """One row per notification sent, keyed on a stable dedupe key."""

    dedupe_key = models.CharField(max_length=180, unique=True)
    event = models.CharField(max_length=80, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.dedupe_key

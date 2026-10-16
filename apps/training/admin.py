"""Read-only Django admin registrations for the training academy.

The admin is deliberately view-only: all writes go through
:mod:`apps.training.services` so transitions, capacity checks, grading and
certificate authorisation cannot be bypassed.
"""

from __future__ import annotations

from django.contrib import admin

from .models import (
    Assessment,
    AssessmentOption,
    AssessmentQuestion,
    AssessmentResult,
    AssessmentSubmission,
    AttendanceRecord,
    AttendanceSession,
    Certificate,
    CertificateTemplate,
    CertificateVerificationLog,
    Course,
    CourseLesson,
    CourseModule,
    CourseResource,
    Enrollment,
    InstructorAssignment,
    InstructorProfile,
    TrainingCategory,
    TrainingNotificationLog,
    TrainingSession,
    TrainingSessionSchedule,
    TrainingVenue,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(TrainingCategory)
class TrainingCategoryAdmin(ReadOnlyAdmin):
    list_display = ("name", "parent", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Course)
class CourseAdmin(ReadOnlyAdmin):
    list_display = ("title", "category", "delivery_mode", "status", "certificate_eligible")
    list_filter = ("status", "delivery_mode", "certificate_eligible")
    search_fields = ("title",)


@admin.register(CourseModule)
class CourseModuleAdmin(ReadOnlyAdmin):
    list_display = ("course", "title", "sort_order")


@admin.register(CourseLesson)
class CourseLessonAdmin(ReadOnlyAdmin):
    list_display = ("module", "title", "lesson_type", "sort_order")


@admin.register(CourseResource)
class CourseResourceAdmin(ReadOnlyAdmin):
    list_display = ("title", "course", "lesson", "resource_type")


@admin.register(InstructorProfile)
class InstructorProfileAdmin(ReadOnlyAdmin):
    list_display = ("user", "professional_title", "is_active")
    list_filter = ("is_active",)


@admin.register(InstructorAssignment)
class InstructorAssignmentAdmin(ReadOnlyAdmin):
    list_display = ("instructor", "course", "session", "role", "is_active")
    list_filter = ("is_active",)


@admin.register(TrainingVenue)
class TrainingVenueAdmin(ReadOnlyAdmin):
    list_display = ("name", "city", "state", "capacity", "is_active")
    list_filter = ("is_active",)


@admin.register(TrainingSession)
class TrainingSessionAdmin(ReadOnlyAdmin):
    list_display = ("reference", "course", "start_date", "end_date", "status", "fee", "currency")
    list_filter = ("status", "delivery_mode")
    search_fields = ("reference", "course__title")
    date_hierarchy = "start_date"


@admin.register(TrainingSessionSchedule)
class TrainingSessionScheduleAdmin(ReadOnlyAdmin):
    list_display = ("session", "date", "topic", "is_cancelled")


@admin.register(Enrollment)
class EnrollmentAdmin(ReadOnlyAdmin):
    list_display = ("reference", "student", "session", "status", "payment_status")
    list_filter = ("status", "payment_status")
    search_fields = ("reference", "student__email")
    date_hierarchy = "created_at"


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(ReadOnlyAdmin):
    list_display = ("session", "date", "topic")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(ReadOnlyAdmin):
    list_display = ("attendance_session", "enrollment", "status", "marked_by")
    list_filter = ("status",)


@admin.register(Assessment)
class AssessmentAdmin(ReadOnlyAdmin):
    list_display = ("title", "course", "assessment_type", "is_published", "passing_score")
    list_filter = ("assessment_type", "is_published")


@admin.register(AssessmentQuestion)
class AssessmentQuestionAdmin(ReadOnlyAdmin):
    list_display = ("assessment", "question_type", "points")


@admin.register(AssessmentOption)
class AssessmentOptionAdmin(ReadOnlyAdmin):
    list_display = ("question", "text", "is_correct")


@admin.register(AssessmentSubmission)
class AssessmentSubmissionAdmin(ReadOnlyAdmin):
    list_display = ("assessment", "enrollment", "attempt_number", "status", "score")
    list_filter = ("status",)


@admin.register(AssessmentResult)
class AssessmentResultAdmin(ReadOnlyAdmin):
    list_display = ("assessment", "enrollment", "score", "percentage", "passed")
    list_filter = ("passed",)


@admin.register(CertificateTemplate)
class CertificateTemplateAdmin(ReadOnlyAdmin):
    list_display = ("name", "title", "is_active")
    list_filter = ("is_active",)


@admin.register(Certificate)
class CertificateAdmin(ReadOnlyAdmin):
    list_display = ("certificate_number", "student", "course", "issue_date", "status")
    list_filter = ("status",)
    search_fields = ("certificate_number", "verification_code", "student__email")


@admin.register(CertificateVerificationLog)
class CertificateVerificationLogAdmin(ReadOnlyAdmin):
    list_display = ("code_attempted", "found", "created_at")
    list_filter = ("found",)


@admin.register(TrainingNotificationLog)
class TrainingNotificationLogAdmin(ReadOnlyAdmin):
    list_display = ("event", "dedupe_key", "created_at")
    list_filter = ("event",)

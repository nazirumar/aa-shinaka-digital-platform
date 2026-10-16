"""Forms for the training academy (public, student portal and staff dashboard).

Student forms collect intent only; every write still passes through
:mod:`apps.training.services` for validation and authorisation. Staff forms are
capability-gated in the views, never in the template.
"""

from __future__ import annotations

from django import forms

from apps.accounts.forms import TailwindFormMixin

from .models import (
    Assessment,
    AssessmentOption,
    AssessmentQuestion,
    AttendanceStatus,
    CertificateTemplate,
    Course,
    CourseLesson,
    CourseModule,
    CourseResource,
    DeliveryMode,
    Enrollment,
    EnrollmentStatus,
    InstructorProfile,
    SessionStatus,
    TrainingCategory,
    TrainingSession,
    TrainingSessionSchedule,
    TrainingVenue,
)
from .validators import validate_image_file, validate_resource_file


class TrainingForm(TailwindFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class TrainingModelForm(TailwindFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class _DateInput(forms.DateInput):
    input_type = "date"


class _DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"


# ---------------------------------------------------------------------------
# Task 1 — categories
# ---------------------------------------------------------------------------


class CategoryForm(TrainingModelForm):
    class Meta:
        model = TrainingCategory
        fields = ["name", "description", "image", "parent", "sort_order", "is_active"]


# ---------------------------------------------------------------------------
# Task 2 — courses
# ---------------------------------------------------------------------------


class CourseForm(TrainingModelForm):
    class Meta:
        model = Course
        fields = [
            "title",
            "category",
            "short_description",
            "description",
            "learning_objectives",
            "prerequisites",
            "duration_hours",
            "delivery_mode",
            "featured_image",
            "certificate_eligible",
            "is_featured",
            "sort_order",
        ]


class ModuleForm(TrainingModelForm):
    class Meta:
        model = CourseModule
        fields = ["title", "description", "sort_order"]


class LessonForm(TrainingModelForm):
    class Meta:
        model = CourseLesson
        fields = [
            "title",
            "lesson_type",
            "content_text",
            "video_url",
            "is_preview",
            "estimated_minutes",
            "sort_order",
        ]


class ResourceForm(TrainingModelForm):
    class Meta:
        model = CourseResource
        fields = [
            "title",
            "resource_type",
            "file",
            "external_url",
            "description",
            "is_downloadable",
            "sort_order",
        ]

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            validate_resource_file(file)
        return file

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("file") and not cleaned.get("external_url"):
            raise forms.ValidationError("Provide a file or an external URL.")
        return cleaned


# ---------------------------------------------------------------------------
# Task 3 — instructors
# ---------------------------------------------------------------------------


class InstructorProfileForm(TrainingModelForm):
    class Meta:
        model = InstructorProfile
        fields = [
            "user",
            "professional_title",
            "biography",
            "expertise",
            "profile_image",
            "is_active",
        ]

    def clean_profile_image(self):
        image = self.cleaned_data.get("profile_image")
        if image:
            validate_image_file(image)
        return image


class AssignmentForm(TrainingForm):
    instructor = forms.ModelChoiceField(
        queryset=InstructorProfile.objects.filter(is_active=True).select_related("user")
    )
    course = forms.ModelChoiceField(queryset=Course.objects.all(), required=False)
    session = forms.ModelChoiceField(queryset=TrainingSession.objects.all(), required=False)
    role = forms.CharField(required=False, max_length=120)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("course") and not cleaned.get("session"):
            raise forms.ValidationError("Choose a course, a session, or both.")
        return cleaned


# ---------------------------------------------------------------------------
# Task 4 — sessions
# ---------------------------------------------------------------------------


class VenueForm(TrainingModelForm):
    class Meta:
        model = TrainingVenue
        fields = ["name", "address", "city", "state", "capacity", "facilities", "is_active"]


class SessionForm(TrainingModelForm):
    class Meta:
        model = TrainingSession
        fields = [
            "course",
            "title",
            "venue",
            "delivery_mode",
            "start_date",
            "end_date",
            "enrollment_deadline",
            "capacity",
            "min_participants",
            "fee",
            "currency",
            "status",
            "location_notes",
        ]
        widgets = {
            "start_date": _DateInput(),
            "end_date": _DateInput(),
            "enrollment_deadline": _DateInput(),
        }


class ScheduleForm(TrainingModelForm):
    class Meta:
        model = TrainingSessionSchedule
        fields = ["topic", "date", "start_time", "end_time", "location", "sort_order"]
        widgets = {"date": _DateInput()}


# ---------------------------------------------------------------------------
# Task 5 — enrolment
# ---------------------------------------------------------------------------


class EnrollmentActionForm(TrainingForm):
    status = forms.ChoiceField(choices=EnrollmentStatus.choices)
    note = forms.CharField(required=False, max_length=300)

    def __init__(self, *args, enrollment: Enrollment | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if enrollment is not None:
            from .models import ENROLLMENT_TRANSITIONS

            allowed = ENROLLMENT_TRANSITIONS.get(enrollment.status, frozenset())
            self.fields["status"].choices = [
                (value, label) for value, label in EnrollmentStatus.choices if value in allowed
            ]


# ---------------------------------------------------------------------------
# Task 8 — attendance
# ---------------------------------------------------------------------------


class AttendanceRegisterForm(TrainingForm):
    date = forms.DateField(widget=_DateInput)
    topic = forms.CharField(required=False, max_length=220)


class AttendanceStatusForm(TrainingForm):
    status = forms.ChoiceField(choices=AttendanceStatus.choices)
    note = forms.CharField(required=False, max_length=200)


# ---------------------------------------------------------------------------
# Task 9 — assessments
# ---------------------------------------------------------------------------


class AssessmentForm(TrainingModelForm):
    class Meta:
        model = Assessment
        fields = [
            "title",
            "module",
            "assessment_type",
            "description",
            "passing_score",
            "max_attempts",
            "deadline",
            "completion_required",
            "sort_order",
        ]
        widgets = {"deadline": _DateTimeInput()}


class QuestionForm(TrainingModelForm):
    class Meta:
        model = AssessmentQuestion
        fields = [
            "prompt",
            "question_type",
            "points",
            "correct_answer",
            "explanation",
            "sort_order",
        ]


class OptionForm(TrainingModelForm):
    class Meta:
        model = AssessmentOption
        fields = ["text", "is_correct", "sort_order"]


class GradeSubmissionForm(TrainingForm):
    score = forms.DecimalField(max_digits=7, decimal_places=2, min_value=0)
    feedback = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


# ---------------------------------------------------------------------------
# Task 11 — certificates
# ---------------------------------------------------------------------------


class CertificateTemplateForm(TrainingModelForm):
    class Meta:
        model = CertificateTemplate
        fields = ["name", "title", "body_text", "footer_text", "is_active"]


class CertificateIssueForm(TrainingForm):
    template = forms.ModelChoiceField(
        queryset=CertificateTemplate.objects.filter(is_active=True), required=False
    )


class CertificateRevokeForm(TrainingForm):
    reason = forms.CharField(max_length=300, widget=forms.Textarea(attrs={"rows": 3}))


# ---------------------------------------------------------------------------
# Public filters
# ---------------------------------------------------------------------------


class CourseFilterForm(TrainingForm):
    q = forms.CharField(required=False, max_length=120)
    category = forms.ModelChoiceField(
        queryset=TrainingCategory.objects.filter(is_active=True), required=False
    )
    delivery_mode = forms.ChoiceField(
        choices=[("", "All modes"), *DeliveryMode.choices], required=False
    )


class SessionStatusFilterForm(TrainingForm):
    status = forms.ChoiceField(choices=[("", "All"), *SessionStatus.choices], required=False)


def course_lesson_choice_queryset(course):
    return CourseLesson.objects.filter(module__course=course)


__all__ = [
    "AssessmentForm",
    "AssignmentForm",
    "AttendanceRegisterForm",
    "AttendanceStatusForm",
    "CategoryForm",
    "CertificateIssueForm",
    "CertificateRevokeForm",
    "CertificateTemplateForm",
    "CourseFilterForm",
    "CourseForm",
    "GradeSubmissionForm",
    "InstructorProfileForm",
    "LessonForm",
    "ModuleForm",
    "OptionForm",
    "QuestionForm",
    "ResourceForm",
    "SessionForm",
    "SessionStatusFilterForm",
    "TrainingForm",
    "TrainingModelForm",
    "VenueForm",
    "course_lesson_choice_queryset",
]

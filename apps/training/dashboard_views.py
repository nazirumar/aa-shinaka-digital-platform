"""Staff dashboard views for the training academy (``/dashboard/training/``).

Every view enforces a capability server-side. ``TRAINING_MANAGE`` unlocks the
operational screens; course publication, certificate issuance and revocation
require ``TRAINING_APPROVE``. Instructors with an active assignment (or the
``TRAINING_INSTRUCT`` capability) may record attendance and grade assessments.

Writes always go through :mod:`apps.training.services` so they are validated,
transactional and audited. Lists support search, filtering and pagination.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability

from . import selectors, services
from .forms import (
    AssessmentForm,
    AssignmentForm,
    AttendanceRegisterForm,
    CategoryForm,
    CertificateTemplateForm,
    CourseForm,
    GradeSubmissionForm,
    InstructorProfileForm,
    LessonForm,
    ModuleForm,
    OptionForm,
    QuestionForm,
    ResourceForm,
    ScheduleForm,
    SessionForm,
    VenueForm,
)
from .models import (
    ENROLLMENT_TRANSITIONS,
    SESSION_TRANSITIONS,
    Assessment,
    AssessmentQuestion,
    AttendanceRecord,
    AttendanceSession,
    Certificate,
    CertificateTemplate,
    Course,
    CourseModule,
    CourseStatus,
    Enrollment,
    EnrollmentStatus,
    InstructorAssignment,
    InstructorProfile,
    SessionStatus,
    TrainingCategory,
    TrainingSession,
    TrainingVenue,
)


def _errors(exc) -> str:
    return "; ".join(getattr(exc, "messages", [str(exc)]))


def training_staff_required(view):
    """Require authentication plus ``TRAINING_MANAGE`` or ``TRAINING_APPROVE``."""

    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not has_capability(
            request.user, Capability.TRAINING_MANAGE, Capability.TRAINING_APPROVE, any_of=True
        ):
            raise PermissionDenied("You do not have permission to manage training.")
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def training_approve_required(view):
    """Require the ``TRAINING_APPROVE`` capability."""

    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not has_capability(request.user, Capability.TRAINING_APPROVE):
            raise PermissionDenied("You do not have permission to approve training.")
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def _base_context(request, **extra):
    context = {
        "active_nav": "training",
        "breadcrumbs": [
            {"label": "Dashboard", "url": "dashboard:home"},
            {"label": "Training", "url": "training_dashboard:home"},
        ],
    }
    context.update(extra)
    return context


def _get_or_none(model, pk):
    if not pk:
        return None
    return model.objects.filter(pk=pk).first()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@training_staff_required
def dashboard_home(request):
    return render(
        request,
        "dashboard/training/home.html",
        _base_context(
            request,
            page_title="Training academy",
            metrics=selectors.overview_metrics(),
            recent_enrollments=Enrollment.objects.select_related(
                "student", "session", "session__course"
            ).order_by("-created_at")[:8],
            recent_certificates=selectors.staff_certificates()[:5],
            upcoming_sessions=selectors.upcoming_sessions(limit=6),
            popularity=list(selectors.course_popularity(limit=6)),
        ),
    )


# ---------------------------------------------------------------------------
# Task 1 — categories
# ---------------------------------------------------------------------------


@training_staff_required
def category_list(request):
    categories = TrainingCategory.objects.order_by("sort_order", "name")
    page_obj = Paginator(categories, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "dashboard/training/category_list.html",
        _base_context(
            request,
            page_title="Training categories",
            categories=page_obj,
            page_obj=page_obj,
        ),
    )


@training_staff_required
def category_create(request):
    form = CategoryForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        image = data.pop("image", None)
        try:
            category = TrainingCategory(**data)
            category.save()
            if image:
                category.image = image
                category.save(update_fields=["image", "updated_at"])
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Category created.")
            return redirect("training_dashboard:category_list")
    return render(
        request,
        "dashboard/training/form.html",
        _base_context(
            request,
            page_title="New category",
            form=form,
            form_title="New training category",
            cancel_url="training_dashboard:category_list",
        ),
    )


@training_staff_required
def category_edit(request, pk):
    category = _get_or_none(TrainingCategory, pk)
    if category is None:
        messages.error(request, "Category not found.")
        return redirect("training_dashboard:category_list")
    form = CategoryForm(request.POST or None, request.FILES or None, instance=category)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        image = data.pop("image", None)
        for key, value in data.items():
            setattr(category, key, value)
        try:
            category.save()
            if image:
                category.image = image
                category.save(update_fields=["image", "updated_at"])
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Category updated.")
            return redirect("training_dashboard:category_list")
    return render(
        request,
        "dashboard/training/form.html",
        _base_context(
            request,
            page_title=category.name,
            form=form,
            form_title=f"Edit {category.name}",
            cancel_url="training_dashboard:category_list",
        ),
    )


@training_staff_required
@require_POST
def category_toggle(request, pk):
    category = _get_or_none(TrainingCategory, pk)
    if category is None:
        messages.error(request, "Category not found.")
        return redirect("training_dashboard:category_list")
    services.set_category_active(category, actor=request.user, active=not category.is_active)
    messages.success(request, "Category updated.")
    return redirect("training_dashboard:category_list")


# ---------------------------------------------------------------------------
# Task 2 — courses
# ---------------------------------------------------------------------------


@training_staff_required
def course_list(request):
    status = request.GET.get("status") or ""
    search = request.GET.get("q") or ""
    courses = selectors.staff_courses(status=status or None, search=search)
    page_obj = _paginate(request, courses, 20)
    return render(
        request,
        "dashboard/training/course_list.html",
        _base_context(
            request,
            page_title="Courses",
            courses=page_obj,
            page_obj=page_obj,
            status_choices=CourseStatus.choices,
            current_status=status,
            search=search,
        ),
    )


def _paginate(request, queryset, per_page):
    from django.core.paginator import Paginator

    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


@training_staff_required
def course_create(request):
    form = CourseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            course = services.create_course(actor=request.user, **form.cleaned_data)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Course created.")
            return redirect("training_dashboard:course_detail", pk=course.pk)
    return render(
        request,
        "dashboard/training/form.html",
        _base_context(
            request,
            page_title="New course",
            form=form,
            form_title="New training course",
            cancel_url="training_dashboard:course_list",
        ),
    )


@training_staff_required
def course_detail(request, pk):
    course = _get_or_none(Course, pk)
    if course is None:
        messages.error(request, "Course not found.")
        return redirect("training_dashboard:course_list")
    return render(
        request,
        "dashboard/training/course_detail.html",
        _base_context(
            request,
            page_title=course.title,
            course=course,
            modules=course.modules.prefetch_related("lessons").order_by("sort_order"),
            resources=course.resources.select_related("lesson").order_by("sort_order"),
            sessions=course.sessions.order_by("start_date"),
            instructors=selectors.course_instructors(course),
            assessments=course.assessments.order_by("sort_order"),
            can_approve=has_capability(request.user, Capability.TRAINING_APPROVE),
            module_form=ModuleForm(),
            lesson_form=LessonForm(),
            resource_form=ResourceForm(),
            assessment_form=AssessmentForm(),
        ),
    )


@training_staff_required
def course_edit(request, pk):
    course = _get_or_none(Course, pk)
    if course is None:
        messages.error(request, "Course not found.")
        return redirect("training_dashboard:course_list")
    form = CourseForm(request.POST or None, request.FILES or None, instance=course)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_course(course, actor=request.user, **form.cleaned_data)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Course updated.")
            return redirect("training_dashboard:course_detail", pk=course.pk)
    return render(
        request,
        "dashboard/training/form.html",
        _base_context(
            request,
            page_title=f"Edit {course.title}",
            form=form,
            form_title=f"Edit {course.title}",
            cancel_url="training_dashboard:course_detail",
            cancel_kwargs={"pk": course.pk},
        ),
    )


@training_approve_required
@require_POST
def course_publish(request, pk):
    course = _get_or_none(Course, pk)
    if course is None:
        messages.error(request, "Course not found.")
        return redirect("training_dashboard:course_list")
    try:
        services.transition_course(course, CourseStatus.PUBLISHED, actor=request.user)
    except Exception as exc:  # noqa: BLE001
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Course published.")
    return redirect("training_dashboard:course_detail", pk=course.pk)


@training_staff_required
@require_POST
def course_archive(request, pk):
    course = _get_or_none(Course, pk)
    if course is None:
        messages.error(request, "Course not found.")
        return redirect("training_dashboard:course_list")
    try:
        services.transition_course(course, CourseStatus.ARCHIVED, actor=request.user)
    except Exception as exc:  # noqa: BLE001
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Course archived.")
    return redirect("training_dashboard:course_detail", pk=course.pk)


@training_staff_required
def module_create(request, pk):
    course = _get_or_none(Course, pk)
    if course is None:
        messages.error(request, "Course not found.")
        return redirect("training_dashboard:course_list")
    form = ModuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.add_module(actor=request.user, course=course, **form.cleaned_data)
        messages.success(request, "Module added.")
    else:
        messages.error(request, "Please correct the module form.")
    return redirect("training_dashboard:course_detail", pk=course.pk)


@training_staff_required
def lesson_create(request, module_pk):
    module = _get_or_none(CourseModule, module_pk)
    if module is None:
        messages.error(request, "Module not found.")
        return redirect("training_dashboard:course_list")
    form = LessonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.add_lesson(module, actor=request.user, **form.cleaned_data)
        messages.success(request, "Lesson added.")
    else:
        messages.error(request, "Please correct the lesson form.")
    return redirect("training_dashboard:course_detail", pk=module.course_id)


@training_staff_required
def resource_create(request, pk):
    course = _get_or_none(Course, pk)
    if course is None:
        messages.error(request, "Course not found.")
        return redirect("training_dashboard:course_list")
    form = ResourceForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        services.add_resource(actor=request.user, course=course, **form.cleaned_data)
        messages.success(request, "Resource added.")
    else:
        messages.error(request, "Please correct the resource form.")
    return redirect("training_dashboard:course_detail", pk=course.pk)


# ---------------------------------------------------------------------------
# Task 3 — instructors
# ---------------------------------------------------------------------------


@training_staff_required
def instructor_list(request):
    instructors = InstructorProfile.objects.select_related("user").order_by(
        "user__first_name", "user__last_name"
    )
    assignments = InstructorAssignment.objects.select_related(
        "instructor__user", "course", "session"
    ).order_by("-created_at")
    return render(
        request,
        "dashboard/training/instructor_list.html",
        _base_context(
            request,
            page_title="Instructors",
            instructors=_paginate(request, instructors, 20),
            assignments=assignments,
            assignment_form=AssignmentForm(),
        ),
    )


@training_staff_required
def instructor_create(request):
    form = InstructorProfileForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        user = data.pop("user")
        try:
            services.create_instructor_profile(actor=request.user, user=user, **data)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Instructor profile created.")
            return redirect("training_dashboard:instructor_list")
    return render(
        request,
        "dashboard/training/form.html",
        _base_context(
            request,
            page_title="New instructor",
            form=form,
            form_title="New instructor profile",
            cancel_url="training_dashboard:instructor_list",
        ),
    )


@training_staff_required
def instructor_edit(request, pk):
    profile = _get_or_none(InstructorProfile, pk)
    if profile is None:
        messages.error(request, "Instructor not found.")
        return redirect("training_dashboard:instructor_list")
    form = InstructorProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        data.pop("user", None)
        try:
            services.update_instructor_profile(profile, actor=request.user, **data)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Instructor updated.")
            return redirect("training_dashboard:instructor_list")
    return render(
        request,
        "dashboard/training/form.html",
        _base_context(
            request,
            page_title="Edit instructor",
            form=form,
            form_title=f"Edit {profile}",
            cancel_url="training_dashboard:instructor_list",
        ),
    )


@training_staff_required
@require_POST
def instructor_toggle(request, pk):
    profile = _get_or_none(InstructorProfile, pk)
    if profile is None:
        messages.error(request, "Instructor not found.")
        return redirect("training_dashboard:instructor_list")
    services.set_instructor_active(profile, actor=request.user, active=not profile.is_active)
    messages.success(request, "Instructor status updated.")
    return redirect("training_dashboard:instructor_list")


@training_staff_required
def assignment_create(request):
    form = AssignmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.assign_instructor(
                instructor=data["instructor"],
                actor=request.user,
                course=data.get("course"),
                session=data.get("session"),
                role=data.get("role", ""),
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Instructor assigned.")
    else:
        messages.error(request, "Please correct the assignment form.")
    return redirect("training_dashboard:instructor_list")


@training_staff_required
@require_POST
def assignment_deactivate(request, pk):
    assignment = _get_or_none(InstructorAssignment, pk)
    if assignment is None:
        messages.error(request, "Assignment not found.")
        return redirect("training_dashboard:instructor_list")
    services.deactivate_assignment(assignment, actor=request.user)
    messages.success(request, "Assignment removed.")
    return redirect("training_dashboard:instructor_list")


# ---------------------------------------------------------------------------
# Task 4 — venues & sessions
# ---------------------------------------------------------------------------


@training_staff_required
def venue_list(request):
    venues = TrainingVenue.objects.order_by("name")
    return render(
        request,
        "dashboard/training/venue_list.html",
        _base_context(request, page_title="Training venues", venues=venues, form=VenueForm()),
    )


@training_staff_required
def venue_create(request):
    form = VenueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.upsert_venue(actor=request.user, **form.cleaned_data)
        messages.success(request, "Venue saved.")
    else:
        messages.error(request, "Please correct the venue form.")
    return redirect("training_dashboard:venue_list")


@training_staff_required
def session_list(request):
    status = request.GET.get("status") or ""
    search = request.GET.get("q") or ""
    sessions = selectors.staff_sessions(status=status or None, search=search)
    return render(
        request,
        "dashboard/training/session_list.html",
        _base_context(
            request,
            page_title="Training sessions",
            sessions=_paginate(request, sessions, 20),
            status_choices=SessionStatus.choices,
            current_status=status,
            search=search,
        ),
    )


@training_staff_required
def session_create(request):
    form = SessionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        course = data.pop("course")
        try:
            session = services.create_session(actor=request.user, course=course, **data)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Session created.")
            return redirect("training_dashboard:session_detail", pk=session.pk)
    return render(
        request,
        "dashboard/training/form.html",
        _base_context(
            request,
            page_title="New session",
            form=form,
            form_title="New training session",
            cancel_url="training_dashboard:session_list",
        ),
    )


@training_staff_required
def session_detail(request, pk):
    session = TrainingSession.objects.filter(pk=pk).select_related("course", "venue").first()
    if session is None:
        messages.error(request, "Session not found.")
        return redirect("training_dashboard:session_list")
    return render(
        request,
        "dashboard/training/session_detail.html",
        _base_context(
            request,
            page_title=session.reference,
            session=session,
            enrollments=session.enrollments.select_related("student").order_by("created_at"),
            schedule=session.schedule.order_by("date", "sort_order"),
            attendance_sessions=session.attendance_sessions.order_by("-date"),
            can_manage=has_capability(request.user, Capability.TRAINING_MANAGE),
            allowed_statuses=[
                (value, label)
                for value, label in SessionStatus.choices
                if value in SESSION_TRANSITIONS.get(session.status, frozenset())
            ],
            schedule_form=ScheduleForm(),
            attendance_form=AttendanceRegisterForm(),
        ),
    )


@training_staff_required
def session_transition(request, pk):
    session = _get_or_none(TrainingSession, pk)
    if session is None:
        messages.error(request, "Session not found.")
        return redirect("training_dashboard:session_list")
    to_status = request.POST.get("status", "")
    try:
        services.transition_session(
            session, to_status, actor=request.user, note=request.POST.get("note", "")
        )
    except Exception as exc:  # noqa: BLE001
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Session status updated.")
    return redirect("training_dashboard:session_detail", pk=session.pk)


@training_staff_required
def schedule_create(request, pk):
    session = _get_or_none(TrainingSession, pk)
    if session is None:
        messages.error(request, "Session not found.")
        return redirect("training_dashboard:session_list")
    form = ScheduleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.add_schedule_entry(actor=request.user, session=session, **form.cleaned_data)
        messages.success(request, "Schedule entry added.")
    else:
        messages.error(request, "Please correct the schedule form.")
    return redirect("training_dashboard:session_detail", pk=session.pk)


# ---------------------------------------------------------------------------
# Task 5 — enrolments
# ---------------------------------------------------------------------------


@training_staff_required
def enrollment_list(request):
    status = request.GET.get("status") or ""
    search = request.GET.get("q") or ""
    enrollments = selectors.staff_enrollments(status=status or None, search=search)
    page_obj = _paginate(request, enrollments, 25)
    return render(
        request,
        "dashboard/training/enrollment_list.html",
        _base_context(
            request,
            page_title="Enrolments",
            enrollments=page_obj,
            page_obj=page_obj,
            status_choices=EnrollmentStatus.choices,
            current_status=status,
            search=search,
        ),
    )


@training_staff_required
def enrollment_detail(request, reference):
    enrollment = (
        Enrollment.objects.filter(reference=reference)
        .select_related("student", "session", "session__course")
        .first()
    )
    if enrollment is None:
        messages.error(request, "Enrolment not found.")
        return redirect("training_dashboard:enrollment_list")
    return render(
        request,
        "dashboard/training/enrollment_detail.html",
        _base_context(
            request,
            page_title=enrollment.reference,
            enrollment=enrollment,
            history=enrollment.status_history.select_related("actor"),
            allowed_statuses=[
                (value, label)
                for value, label in EnrollmentStatus.choices
                if value in ENROLLMENT_TRANSITIONS.get(enrollment.status, frozenset())
            ],
            payments=enrollment.payments.order_by("-created_at"),
        ),
    )


@training_staff_required
def enrollment_action(request, reference):
    enrollment = Enrollment.objects.filter(reference=reference).first()
    if enrollment is None:
        messages.error(request, "Enrolment not found.")
        return redirect("training_dashboard:enrollment_list")
    to_status = request.POST.get("status", "")
    note = request.POST.get("note", "")
    try:
        services.transition_enrollment(
            enrollment, to_status, actor=request.user, note=note, request=request
        )
    except Exception as exc:  # noqa: BLE001
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Enrolment updated.")
    return redirect("training_dashboard:enrollment_detail", reference=enrollment.reference)


# ---------------------------------------------------------------------------
# Task 8 — attendance
# ---------------------------------------------------------------------------


@training_staff_required
def attendance_session_list(request):
    registers = AttendanceSession.objects.select_related("session__course").order_by("-date")
    return render(
        request,
        "dashboard/training/attendance_list.html",
        _base_context(
            request,
            page_title="Attendance registers",
            registers=_paginate(request, registers, 25),
        ),
    )


@training_staff_required
def attendance_register_create(request, pk):
    session = _get_or_none(TrainingSession, pk)
    if session is None:
        messages.error(request, "Session not found.")
        return redirect("training_dashboard:session_list")
    from .forms import AttendanceRegisterForm

    form = AttendanceRegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            register = services.create_attendance_session(
                actor=request.user, session=session, **form.cleaned_data
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Attendance register created.")
            return redirect("training_dashboard:attendance_detail", pk=register.pk)
    else:
        messages.error(request, "Please correct the register form.")
    return redirect("training_dashboard:session_detail", pk=session.pk)


@training_staff_required
def attendance_detail(request, pk):
    from .models import AttendanceStatus as _Status

    register = AttendanceSession.objects.filter(pk=pk).select_related("session__course").first()
    if register is None:
        messages.error(request, "Register not found.")
        return redirect("training_dashboard:attendance_session_list")
    enrollments = register.session.enrollments.filter(
        status__in=[EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED]
    ).select_related("student")
    records = {
        record.enrollment_id: record
        for record in AttendanceRecord.objects.filter(attendance_session=register)
    }
    return render(
        request,
        "dashboard/training/attendance_detail.html",
        _base_context(
            request,
            page_title=f"Attendance · {register.date}",
            register=register,
            enrollments=enrollments,
            records=records,
            rows=[(enrollment, records.get(enrollment.id)) for enrollment in enrollments],
            statuses=_Status.choices,
        ),
    )


@training_staff_required
def attendance_mark(request, pk):
    from .models import AttendanceStatus as _Status

    register = AttendanceSession.objects.filter(pk=pk).select_related("session").first()
    if register is None:
        messages.error(request, "Register not found.")
        return redirect("training_dashboard:attendance_session_list")
    enrollments = register.session.enrollments.filter(
        status__in=[EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED]
    )
    marked = 0
    for enrollment in enrollments:
        status = request.POST.get(f"status_{enrollment.pk}")
        if status not in _Status.values:
            continue
        services.record_attendance(
            actor=request.user,
            attendance_session=register,
            enrollment=enrollment,
            status=status,
            note=request.POST.get(f"note_{enrollment.pk}", ""),
        )
        marked += 1
    messages.success(request, f"Attendance saved for {marked} student(s).")
    return redirect("training_dashboard:attendance_detail", pk=register.pk)


# ---------------------------------------------------------------------------
# Task 9 — assessments
# ---------------------------------------------------------------------------


@training_staff_required
def assessment_list(request):
    assessments = Assessment.objects.select_related("course").order_by("-created_at")
    return render(
        request,
        "dashboard/training/assessment_list.html",
        _base_context(
            request,
            page_title="Assessments",
            assessments=_paginate(request, assessments, 20),
        ),
    )


@training_staff_required
def assessment_create(request, pk):
    course = _get_or_none(Course, pk)
    if course is None:
        messages.error(request, "Course not found.")
        return redirect("training_dashboard:assessment_list")
    form = AssessmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            assessment = services.create_assessment(
                actor=request.user, course=course, **form.cleaned_data
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Assessment created.")
            return redirect("training_dashboard:assessment_detail", pk=assessment.pk)
    return render(
        request,
        "dashboard/training/form.html",
        _base_context(
            request,
            page_title="New assessment",
            form=form,
            form_title=f"New assessment · {course.title}",
            cancel_url="training_dashboard:course_detail",
            cancel_kwargs={"pk": course.pk},
        ),
    )


@training_staff_required
def assessment_detail(request, pk):
    from .models import AssessmentSubmission

    assessment = Assessment.objects.filter(pk=pk).select_related("course").first()
    if assessment is None:
        messages.error(request, "Assessment not found.")
        return redirect("training_dashboard:assessment_list")
    return render(
        request,
        "dashboard/training/assessment_detail.html",
        _base_context(
            request,
            page_title=assessment.title,
            assessment=assessment,
            questions=assessment.questions.prefetch_related("options").order_by("sort_order"),
            submissions=AssessmentSubmission.objects.filter(assessment=assessment).select_related(
                "student", "enrollment"
            ),
            question_form=QuestionForm(),
            option_form=OptionForm(),
        ),
    )


@training_staff_required
def question_create(request, pk):
    assessment = _get_or_none(Assessment, pk)
    if assessment is None:
        messages.error(request, "Assessment not found.")
        return redirect("training_dashboard:assessment_list")
    form = QuestionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.add_question(actor=request.user, assessment=assessment, **form.cleaned_data)
        messages.success(request, "Question added.")
    else:
        messages.error(request, "Please correct the question form.")
    return redirect("training_dashboard:assessment_detail", pk=assessment.pk)


@training_staff_required
def option_create(request, question_pk):

    question = (
        AssessmentQuestion.objects.filter(pk=question_pk).select_related("assessment").first()
    )
    if question is None:
        messages.error(request, "Question not found.")
        return redirect("training_dashboard:assessment_list")
    form = OptionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.add_option(actor=request.user, question=question, **form.cleaned_data)
        messages.success(request, "Option added.")
    else:
        messages.error(request, "Please correct the option form.")
    return redirect("training_dashboard:assessment_detail", pk=question.assessment_id)


@training_staff_required
@require_POST
def assessment_publish(request, pk):
    assessment = _get_or_none(Assessment, pk)
    if assessment is None:
        messages.error(request, "Assessment not found.")
        return redirect("training_dashboard:assessment_list")
    try:
        services.publish_assessment(assessment, actor=request.user)
    except Exception as exc:  # noqa: BLE001
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Assessment published.")
    return redirect("training_dashboard:assessment_detail", pk=assessment.pk)


@training_staff_required
def submission_grade(request, pk):
    from .models import AssessmentSubmission

    submission = (
        AssessmentSubmission.objects.filter(pk=pk)
        .select_related("assessment", "enrollment", "student")
        .first()
    )
    if submission is None:
        messages.error(request, "Submission not found.")
        return redirect("training_dashboard:assessment_list")
    form = GradeSubmissionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.grade_submission(
                submission,
                actor=request.user,
                score=form.cleaned_data["score"],
                feedback=form.cleaned_data.get("feedback", ""),
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, _errors(exc))
        else:
            messages.success(request, "Submission graded.")
            return redirect("training_dashboard:assessment_detail", pk=submission.assessment_id)
    return render(
        request,
        "dashboard/training/form.html",
        _base_context(
            request,
            page_title="Grade submission",
            form=form,
            form_title=f"Grade {submission.student} · {submission.assessment.title}",
            cancel_url="training_dashboard:assessment_detail",
            cancel_kwargs={"pk": submission.assessment_id},
        ),
    )


# ---------------------------------------------------------------------------
# Task 11 — certificates
# ---------------------------------------------------------------------------


@training_staff_required
def certificate_list(request):
    status = request.GET.get("status") or ""
    search = request.GET.get("q") or ""
    certificates = selectors.staff_certificates(status=status or None, search=search)
    page_obj = _paginate(request, certificates, 25)
    return render(
        request,
        "dashboard/training/certificate_list.html",
        _base_context(
            request,
            page_title="Certificates",
            certificates=page_obj,
            page_obj=page_obj,
            current_status=status,
            search=search,
            can_approve=has_capability(request.user, Capability.TRAINING_APPROVE),
            completed_enrollments=Enrollment.objects.filter(
                status=EnrollmentStatus.COMPLETED
            ).select_related("session__course", "student"),
            templates=CertificateTemplate.objects.filter(is_active=True),
        ),
    )


@training_approve_required
def certificate_issue(request, reference):
    from .models import CertificateTemplate

    enrollment = (
        Enrollment.objects.filter(reference=reference)
        .select_related("student", "session__course")
        .first()
    )
    if enrollment is None:
        messages.error(request, "Enrolment not found.")
        return redirect("training_dashboard:certificate_list")
    template = _get_or_none(CertificateTemplate, request.POST.get("template"))
    try:
        services.issue_certificate(
            actor=request.user, enrollment=enrollment, template=template, request=request
        )
    except Exception as exc:  # noqa: BLE001
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Certificate issued.")
    return redirect("training_dashboard:certificate_list")


@training_approve_required
def certificate_revoke(request, pk):
    certificate = _get_or_none(Certificate, pk)
    if certificate is None:
        messages.error(request, "Certificate not found.")
        return redirect("training_dashboard:certificate_list")
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "A revocation reason is required.")
        return redirect("training_dashboard:certificate_list")
    try:
        services.revoke_certificate(certificate, actor=request.user, reason=reason)
    except Exception as exc:  # noqa: BLE001
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Certificate revoked.")
    return redirect("training_dashboard:certificate_list")


@training_approve_required
def certificate_template_list(request):
    from .models import CertificateTemplate

    templates = CertificateTemplate.objects.order_by("name")
    form = CertificateTemplateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.create_certificate_template(actor=request.user, **form.cleaned_data)
        messages.success(request, "Certificate template saved.")
        return redirect("training_dashboard:certificate_template_list")
    return render(
        request,
        "dashboard/training/certificate_template_list.html",
        _base_context(request, page_title="Certificate templates", templates=templates, form=form),
    )


# ---------------------------------------------------------------------------
# Task 15 — reports
# ---------------------------------------------------------------------------


@training_staff_required
def reports(request):
    return render(
        request,
        "dashboard/training/reports.html",
        _base_context(request, page_title="Training reports", report=selectors.report_metrics()),
    )

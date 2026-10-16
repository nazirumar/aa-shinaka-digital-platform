"""Student training-portal views (``/account/training/...``).

Students only ever see their own enrolments, attendance, submissions and
certificates. Every read is scoped to ``request.user``; every write is
ownership-checked in the service layer. Private learning resources are served
only through an authorised download view.
"""

from __future__ import annotations

import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.orders import payments as order_payments

from . import documents, selectors, services
from .models import (
    Assessment,
    Certificate,
    CertificateStatus,
    CourseResource,
    Enrollment,
    EnrollmentStatus,
)


def _errors(exc) -> str:
    return "; ".join(getattr(exc, "messages", [str(exc)]))


def _owned_enrollment(request, reference) -> Enrollment:
    enrollment = selectors.enrollment_for(request.user, reference)
    if enrollment is None:
        raise Http404("Enrolment not found.")
    return enrollment


@login_required
def student_home(request):
    return render(
        request,
        "training/customer/home.html",
        {
            "page_title": "My training",
            "enrollments": selectors.enrollments_for(request.user)[:5],
            "upcoming": selectors.upcoming_enrollments_for(request.user)[:5],
            "certificates": selectors.certificates_for(request.user)[:5],
        },
    )


@login_required
def my_courses(request):
    return render(
        request,
        "training/customer/my_courses.html",
        {
            "page_title": "My courses",
            "enrollments": selectors.enrollments_for(request.user),
        },
    )


@login_required
def upcoming_sessions(request):
    return render(
        request,
        "training/customer/upcoming_sessions.html",
        {
            "page_title": "Upcoming sessions",
            "enrollments": selectors.upcoming_enrollments_for(request.user),
        },
    )


@login_required
def enrollment_list(request):
    return render(
        request,
        "training/customer/enrollment_list.html",
        {"page_title": "My enrolments", "enrollments": selectors.enrollments_for(request.user)},
    )


def _enrollment_or_404(request, reference) -> Enrollment:
    enrollment = selectors.enrollment_for(request.user, reference)
    if enrollment is None:
        raise Http404("Enrolment not found.")
    return enrollment


@login_required
def enrollment_detail(request, reference):
    enrollment = _enrollment_or_404(request, reference)
    progress_map = selectors.lesson_progress_map(enrollment)
    course = enrollment.session.course
    modules = (
        course.modules.prefetch_related("lessons").order_by("sort_order")
        if enrollment.status in {EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED}
        else course.modules.none()
    )
    module_rows = [
        {
            "module": module,
            "lessons": [
                {"lesson": lesson, "progress": progress_map.get(lesson.id)}
                for lesson in module.lessons.all()
            ],
        }
        for module in modules
    ]
    return render(
        request,
        "training/customer/enrollment_detail.html",
        {
            "page_title": f"Enrolment {enrollment.reference}",
            "enrollment": enrollment,
            "course": course,
            "modules": modules,
            "module_rows": module_rows,
            "progress_map": progress_map,
            "progress": selectors.course_progress(enrollment),
            "attendance": selectors.attendance_summary(enrollment),
            "attendance_records": selectors.attendance_records_for(enrollment),
            "assessments": selectors.published_assessments(course),
            "submissions": selectors.submissions_for(enrollment),
            "resources": selectors.course_resources(course),
            "certificates": enrollment.certificates.all(),
            "history": enrollment.status_history.all(),
        },
    )


@require_POST
@login_required
def enrollment_pay(request, reference):
    enrollment = _enrollment_or_404(request, reference)
    balance = enrollment.balance_due
    try:
        payment = order_payments.initialize_training_payment(
            enrollment, actor=request.user, amount=balance, request=request
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
        return redirect("training_account:enrollment_detail", reference=enrollment.reference)
    url = order_payments.latest_authorization_url(payment)
    if not url:
        messages.info(request, "We could not open the payment page. Please try again.")
        return redirect("training_account:enrollment_detail", reference=enrollment.reference)
    return redirect(url)


@require_POST
@login_required
def enrollment_cancel(request, reference):
    enrollment = _enrollment_or_404(request, reference)
    try:
        services.cancel_own_enrollment(enrollment, actor=request.user)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Enrolment cancelled.")
    return redirect("training_account:enrollment_detail", reference=enrollment.reference)


@require_POST
@login_required
def lesson_complete(request, reference, lesson_id):
    enrollment = _enrollment_or_404(request, reference)
    lesson = enrollment.session.course.modules.values_list("lessons__id", flat=True)
    from .models import CourseLesson

    lesson_obj = CourseLesson.objects.filter(pk=lesson_id, pk__in=list(lesson)).first()
    if lesson_obj is None:
        raise Http404("Lesson not found.")
    completed = request.POST.get("completed", "true") != "false"
    try:
        services.mark_lesson_complete(
            actor=request.user, enrollment=enrollment, lesson=lesson_obj, completed=completed
        )
        services.record_lesson_view(actor=request.user, enrollment=enrollment, lesson=lesson_obj)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
    else:
        messages.success(request, "Progress updated.")
    return redirect("training_account:enrollment_detail", reference=enrollment.reference)


@login_required
def resource_download(request, pk):
    resource = CourseResource.objects.filter(pk=pk).select_related("course", "lesson").first()
    if resource is None:
        raise Http404("Resource not found.")
    if not services.can_access_resource(request.user, resource):
        raise PermissionDenied("You cannot access this resource.")
    if resource.external_url and not resource.file:
        return redirect(resource.external_url)
    if not resource.file:
        raise Http404("Resource file not found.")
    return FileResponse(
        resource.file.open("rb"),
        as_attachment=True,
        filename=os.path.basename(resource.file.name),
    )


def _assessment_for(enrollment, assessment_id) -> Assessment:
    assessment = Assessment.objects.filter(
        pk=assessment_id, course=enrollment.session.course
    ).first()
    if assessment is None or not assessment.is_published:
        raise Http404("Assessment not found.")
    return assessment


@login_required
def assessment_take(request, reference, assessment_id):
    enrollment = _enrollment_or_404(request, reference)
    if enrollment.status not in {EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED}:
        raise PermissionDenied("Only confirmed students can take assessments.")
    assessment = _assessment_for(enrollment, assessment_id)
    questions = assessment.questions.prefetch_related("options").order_by("sort_order")
    existing = assessment.submissions.filter(enrollment=enrollment).order_by("-attempt_number")
    attempts_used = existing.count()
    at_limit = bool(assessment.max_attempts) and attempts_used >= assessment.max_attempts

    if request.method == "POST":
        if at_limit:
            messages.error(request, "You have reached the maximum number of attempts.")
            return redirect(
                "training_account:assessment_take", reference=reference, assessment_id=assessment_id
            )
        answers = {}
        for question in questions:
            key = f"q_{question.pk}"
            if question.question_type == "short_answer":
                answers[str(question.pk)] = request.POST.get(key, "").strip()
            else:
                answers[str(question.pk)] = request.POST.get(key, "")
        try:
            submission = services.submit_assessment(
                enrollment=enrollment, assessment=assessment, answers=answers, actor=request.user
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _errors(exc))
        else:
            messages.success(request, f"Attempt {submission.attempt_number} submitted.")
            return redirect(
                "training_account:assessment_take", reference=reference, assessment_id=assessment_id
            )
    return render(
        request,
        "training/customer/assessment_take.html",
        {
            "page_title": assessment.title,
            "enrollment": enrollment,
            "assessment": assessment,
            "questions": questions,
            "submissions": existing,
            "at_limit": at_limit,
            "attempts_used": attempts_used,
        },
    )


@login_required
def certificate_list(request):
    return render(
        request,
        "training/customer/certificate_list.html",
        {"page_title": "My certificates", "certificates": selectors.certificates_for(request.user)},
    )


@login_required
def certificate_download(request, pk):
    certificate = selectors.certificate_for(request.user, pk)
    if certificate is None:
        raise Http404("Certificate not found.")
    payload = documents.certificate_pdf(certificate)
    response = HttpResponse(payload, content_type="application/pdf")
    filename = f"{certificate.certificate_number}.pdf"
    disposition = "inline" if request.GET.get("inline") else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


@login_required
def payment_history(request):
    enrollments = selectors.enrollments_for(request.user).prefetch_related("payments")
    return render(
        request,
        "training/customer/payment_history.html",
        {"page_title": "Training payments", "enrollments": enrollments},
    )


@login_required
def certificate_view(request, pk):
    certificate = (
        Certificate.objects.filter(pk=pk, student=request.user)
        .select_related("course", "session")
        .first()
    )
    if certificate is None:
        raise Http404("Certificate not found.")
    return render(
        request,
        "training/customer/certificate_detail.html",
        {
            "page_title": f"Certificate {certificate.certificate_number}",
            "certificate": certificate,
            "is_valid": certificate.status == CertificateStatus.ISSUED,
        },
    )

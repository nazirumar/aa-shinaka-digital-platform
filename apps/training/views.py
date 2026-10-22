"""Public training-academy views (``/training/...``) and the payment callback.

Reads come from :mod:`apps.training.selectors`; writes go through
:mod:`apps.training.services`. Only *published* courses and their real, scheduled
sessions are ever shown. Draft content, answer keys and private resources are
never exposed here.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core.ratelimit import rate_limit
from apps.orders import payments as order_payments
from apps.orders.payment_models import PaymentProvider, PaymentState
from apps.seo import canonical_from_request, seo_context

from . import selectors, services
from .forms import CourseFilterForm
from .models import CertificateStatus, EnrollmentStatus, TrainingSession


def _seo(
    *,
    title: str,
    description: str = "",
    canonical: str = "",
    noindex: bool = False,
    og_type: str = "website",
) -> dict:
    """SEO context for this app. Signature kept for existing call sites.

    Previously this helper returned only a title and description, so every
    training page emitted a query-string canonical and could be indexed even
    when filtered.
    """
    return seo_context(
        title=title,
        description=description,
        canonical=canonical,
        noindex=noindex,
        og_type=og_type,
    )


def _errors(exc) -> str:
    return "; ".join(getattr(exc, "messages", [str(exc)]))


def training_home(request):
    return render(
        request,
        "training/home.html",
        {
            **_seo(
                title="Training academy",
                description=(
                    "Practical agricultural training courses and scheduled sessions "
                    "from AA Shinaka."
                ),
                canonical=canonical_from_request(request),
            ),
            "categories": selectors.active_categories(),
            "featured_courses": selectors.featured_courses(limit=3),
            "courses": selectors.published_courses()[:6],
            "sessions": selectors.upcoming_sessions(limit=6),
            "instructors": selectors.active_instructors()[:4],
            "breadcrumbs": [{"label": "Home", "url": "core:home"}, {"label": "Training"}],
        },
    )


def course_list(request):
    form = CourseFilterForm(request.GET or None)
    category = None
    delivery_mode = ""
    search = ""
    if form.is_valid():
        category = form.cleaned_data.get("category")
        delivery_mode = form.cleaned_data.get("delivery_mode") or ""
        search = form.cleaned_data.get("q") or ""
    courses = selectors.published_courses(
        category=category, delivery_mode=delivery_mode, search=search
    )
    page_obj = Paginator(courses, 9).get_page(request.GET.get("page"))
    return render(
        request,
        "training/course_list.html",
        {
            **_seo(
                title="Courses",
                canonical=canonical_from_request(request),
                # Filtered/paginated course lists consolidate onto the base URL.
                noindex=bool(set(request.GET) & {"page", "category", "delivery_mode", "q"}),
            ),
            "courses": page_obj,
            "page_obj": page_obj,
            "form": form,
            "categories": selectors.active_categories(),
        },
    )


def category_detail(request, slug):
    category = selectors.active_categories().filter(slug=slug).first()
    if category is None:
        raise Http404("Category not found.")
    page_obj = Paginator(selectors.published_courses(category=category), 9).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "training/category_detail.html",
        {
            **_seo(
                title=category.name,
                description=category.description,
                canonical=canonical_from_request(request),
            ),
            "category": category,
            "courses": page_obj,
        },
    )


def course_detail(request, slug):
    course = selectors.published_course(slug)
    if course is None:
        raise Http404("Course not found.")
    modules = selectors.course_modules(course).prefetch_related("lessons")
    return render(
        request,
        "training/course_detail.html",
        {
            **_seo(
                title=course.title,
                description=course.short_description,
                canonical=canonical_from_request(request),
            ),
            "course": course,
            "modules": modules,
            "instructors": selectors.course_instructors(course),
            "sessions": selectors.upcoming_sessions(course=course),
            "assessments": selectors.published_assessments(course),
            "breadcrumbs": [
                {"label": "Home", "url": "core:home"},
                {"label": "Training", "url": "training:training_home"},
                {"label": course.title},
            ],
        },
    )


def session_list(request):
    return render(
        request,
        "training/session_list.html",
        {
            **_seo(
                title="Upcoming training sessions",
                canonical=canonical_from_request(request),
            ),
            "sessions": selectors.upcoming_sessions(),
        },
    )


def session_detail(request, pk):
    session = selectors.session(pk)
    if session is None or session.course.status != "published":
        raise Http404("Session not found.")
    return render(
        request,
        "training/session_detail.html",
        {
            **_seo(
                title=session.title or session.course.title,
                canonical=canonical_from_request(request),
            ),
            "session": session,
            "course": session.course,
            "schedule": session.schedule.order_by("date", "sort_order"),
            "seats_left": max(session.capacity - session.confirmed_seats, 0),
        },
    )


@require_POST
@login_required
def enroll(request, pk):
    session = TrainingSession.objects.select_related("course").filter(pk=pk).first()
    if session is None:
        raise Http404("Session not found.")
    try:
        enrollment = services.submit_enrollment(
            student=request.user, session=session, actor=request.user, request=request
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _errors(exc))
        return redirect("training:session_detail", pk=pk)
    if enrollment.status == EnrollmentStatus.WAITLISTED:
        messages.info(request, "This session is full — you have been added to the waitlist.")
    else:
        messages.success(request, f"Enrolment {enrollment.reference} submitted.")
    return redirect("training_account:enrollment_detail", reference=enrollment.reference)


# ---------------------------------------------------------------------------
# Public certificate verification
# ---------------------------------------------------------------------------


@rate_limit(
    scope="certificate_verify",
    limit=settings.FORM_RATE_LIMIT_ATTEMPTS,
    window=settings.FORM_RATE_LIMIT_WINDOW,
)
def certificate_verify(request, code: str = ""):
    """Public verification: reveal only the minimum approved information."""
    submitted = code or request.GET.get("code", "") or request.POST.get("code", "")
    certificate = None
    if submitted:
        certificate = services.verify_certificate(submitted)
    return render(
        request,
        "training/certificate_verify.html",
        {
            # A verification lookup is a utility page, not content: keep it out
            # of the index (and out of the sitemap) entirely.
            **_seo(
                title="Verify a certificate",
                canonical=canonical_from_request(request),
                noindex=True,
            ),
            "submitted": submitted,
            "certificate": certificate,
            "is_valid": bool(certificate and certificate.status == CertificateStatus.ISSUED),
        },
    )


# ---------------------------------------------------------------------------
# Payment callback (re-verifies server-side through Phase 6)
# ---------------------------------------------------------------------------


@login_required
def payment_callback(request, reference):
    from .models import Enrollment

    enrollment = Enrollment.objects.select_related("session").filter(reference=reference).first()
    if enrollment is None:
        messages.error(request, "Enrolment not found.")
        return redirect("training_account:home")
    if enrollment.student_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied("You cannot view this enrolment.")

    reference_value = request.GET.get("reference") or request.GET.get("trxref") or ""
    queryset = enrollment.payments.filter(provider=PaymentProvider.PAYSTACK)
    payment = None
    if reference_value:
        payment = (
            queryset.filter(reference=reference_value).first()
            or queryset.filter(provider_reference=reference_value).first()
        )
    if payment is None:
        payment = queryset.order_by("-created_at").first()
    if payment is None:
        messages.error(request, "We could not find a payment for this enrolment.")
        return redirect("training_account:enrollment_detail", reference=enrollment.reference)

    try:
        order_payments.verify_payment(payment, request=request, source="callback")
    except ValidationError as exc:
        messages.error(request, _errors(exc))
    except Exception:  # pragma: no cover - never expose provider errors
        messages.warning(request, "We could not confirm your payment yet. Please refresh.")
    else:
        payment.refresh_from_db()
        if payment.status == PaymentState.PAID:
            messages.success(request, "Payment confirmed. Thank you!")
        elif payment.requires_review:
            messages.info(request, "Payment received — our finance team will verify it shortly.")
        else:
            messages.info(request, "We have not received confirmation of your payment yet.")
    return redirect("training_account:enrollment_detail", reference=enrollment.reference)

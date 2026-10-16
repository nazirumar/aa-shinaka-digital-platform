"""Training notification helpers (Task 14).

Reuses the Phase 6 email helper (``apps.orders.notifications.send_notification``)
so there is a single templating/mail path. Every notification is recorded in
:class:`~apps.training.models.TrainingNotificationLog` keyed on a stable dedupe
key, so a retried or duplicated call never double-notifies.
"""

from __future__ import annotations

from apps.orders.notifications import send_notification

from .models import TrainingNotificationLog


def notify_once(
    *, event: str, dedupe_key: str, to: str, subject: str, heading: str, intro: str, **extra
) -> bool:
    """Send ``heading``/``intro`` once for ``dedupe_key``; return whether it sent."""
    if not to:
        return False
    _, created = TrainingNotificationLog.objects.get_or_create(
        dedupe_key=dedupe_key[:180], defaults={"event": event}
    )
    if not created:
        return False
    send_notification(to=to, subject=subject, heading=heading, intro=intro, **extra)
    return True


def _student_email(enrollment) -> str:
    return getattr(getattr(enrollment, "student", None), "email", "")


def _session_label(enrollment) -> str:
    session = enrollment.session
    return session.title or session.course.title


def enrollment_submitted(enrollment) -> bool:
    return notify_once(
        event="training_enrollment_submitted",
        dedupe_key=f"training-enrollment-submitted:{enrollment.pk}",
        to=_student_email(enrollment),
        subject=f"Enrolment received — {_session_label(enrollment)}",
        heading="Enrolment submitted",
        intro=(
            f"We received your enrolment request ({enrollment.reference}) for "
            f"{_session_label(enrollment)}. "
            + (
                "Please complete payment to confirm your place."
                if enrollment.session.is_paid
                else "Our training team will confirm your place shortly."
            )
        ),
    )


def enrollment_confirmed(enrollment) -> bool:
    return notify_once(
        event="training_enrollment_confirmed",
        dedupe_key=f"training-enrollment-confirmed:{enrollment.pk}",
        to=_student_email(enrollment),
        subject=f"Enrolment confirmed — {_session_label(enrollment)}",
        heading="Enrolment confirmed",
        intro=(
            f"Your place on {_session_label(enrollment)} is confirmed "
            f"(reference {enrollment.reference}). We look forward to welcoming you."
        ),
    )


def payment_verified(enrollment) -> bool:
    return notify_once(
        event="training_payment_verified",
        dedupe_key=f"training-payment-verified:{enrollment.pk}:{enrollment.amount_paid}",
        to=_student_email(enrollment),
        subject=f"Payment received — {_session_label(enrollment)}",
        heading="Payment received",
        intro=(
            f"We have received your training payment for {_session_label(enrollment)} "
            f"(reference {enrollment.reference})."
        ),
    )


def session_reminder(enrollment, *, dedupe_suffix: str = "start") -> bool:
    return notify_once(
        event="training_session_reminder",
        dedupe_key=(
            f"training-session-reminder:{enrollment.session_id}:{enrollment.pk}:{dedupe_suffix}"
        ),
        to=_student_email(enrollment),
        subject=f"Upcoming session — {_session_label(enrollment)}",
        heading="Session reminder",
        intro=(
            f"Your session {_session_label(enrollment)} starts on "
            f"{enrollment.session.start_date:%d %b %Y}. We look forward to seeing you."
        ),
    )


def session_rescheduled(session, enrollment) -> bool:
    return notify_once(
        event="training_session_rescheduled",
        dedupe_key=f"training-session-rescheduled:{session.pk}:{session.start_date}",
        to=_student_email(enrollment),
        subject=f"Session rescheduled — {_session_label(enrollment)}",
        heading="Session rescheduled",
        intro=(
            f"{_session_label(enrollment)} has been rescheduled to start on "
            f"{session.start_date:%d %b %Y}."
        ),
    )


def training_cancelled(enrollment) -> bool:
    return notify_once(
        event="training_cancelled",
        dedupe_key=f"training-cancelled:{enrollment.pk}",
        to=_student_email(enrollment),
        subject=f"Session cancelled — {_session_label(enrollment)}",
        heading="Session cancelled",
        intro=(
            f"Unfortunately {_session_label(enrollment)} has been cancelled. "
            "Our team will be in touch about next steps."
        ),
    )


def assessment_published(assessment, enrollment) -> bool:
    return notify_once(
        event="training_assessment_published",
        dedupe_key=f"training-assessment-published:{assessment.pk}:{enrollment.pk}",
        to=_student_email(enrollment),
        subject=f"New assessment — {assessment.title}",
        heading="Assessment available",
        intro=(
            f"A new assessment, {assessment.title}, is now available for {assessment.course.title}."
        ),
    )


def assessment_result_available(submission) -> bool:
    enrollment = submission.enrollment
    assessment = submission.assessment
    return notify_once(
        event="training_assessment_result",
        dedupe_key=f"training-assessment-result:{submission.pk}",
        to=_student_email(enrollment),
        subject=f"Assessment result — {assessment.title}",
        heading="Assessment result available",
        intro=(
            f"Your result for {assessment.title} is now available "
            f"(reference {enrollment.reference})."
        ),
    )


def certificate_issued(certificate) -> bool:
    return notify_once(
        event="training_certificate_issued",
        dedupe_key=f"training-certificate-issued:{certificate.pk}",
        to=getattr(certificate.student, "email", ""),
        subject=f"Certificate issued — {certificate.course.title}",
        heading="Certificate issued",
        intro=(
            f"Congratulations! Your certificate {certificate.certificate_number} for "
            f"{certificate.course.title} has been issued. You can download it from your "
            "training dashboard."
        ),
    )

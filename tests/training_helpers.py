"""Reusable builders for the Phase 9 training-academy tests.

Arranging fixtures may write directly to the ORM where a step is not itself
under test, but anything that *is* the behaviour under test goes through the
service layer (``apps.training.services`` / ``apps.orders.payments``) so the
real validation, capacity enforcement, transitions, payment settlement and
permission checks are exercised. Money is always ``Decimal``.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.training import services
from apps.training.models import (
    CourseStatus,
    DeliveryMode,
    SessionStatus,
    TrainingCategory,
    TrainingSession,
)


def make_category(*, actor, name="Crop Production", **fields) -> TrainingCategory:
    return services.upsert_category(actor=actor, name=name, **fields)


def make_course(*, actor, category=None, publish=True, approver=None, **fields):
    fields.setdefault("title", "Foundation Course")
    fields.setdefault("delivery_mode", DeliveryMode.IN_PERSON)
    fields.setdefault("duration_hours", Decimal("8.0"))
    course = services.create_course(actor=actor, category=category, **fields)
    if publish:
        # Publishing requires TRAINING_APPROVE, so default to an approver.
        from apps.accounts.models import User, UserRole
        from apps.accounts.roles import sync_user_groups

        if approver is None:
            approver = User.objects.filter(is_superuser=True).first()
            if approver is None:
                approver = User.objects.create_superuser(
                    email="approver@example.com",
                    password="test-pass-12345",
                    first_name="Approver",
                    last_name="User",
                    role=UserRole.ADMINISTRATOR,
                )
                sync_user_groups(approver)
        services.transition_course(course, CourseStatus.PUBLISHED, actor=approver)
        course.refresh_from_db()
    return course


def make_module(*, actor, course, title="Module 1", sort_order=1):
    return services.add_module(actor=actor, course=course, title=title, sort_order=sort_order)


def make_lesson(*, actor, module, title="Lesson 1", sort_order=1, **fields):
    fields.setdefault("lesson_type", "text")
    return services.add_lesson(module, actor=actor, title=title, sort_order=sort_order, **fields)


def make_venue(*, actor, name="Ibadan Hall", **fields):
    return services.upsert_venue(actor=actor, name=name, **fields)


def make_session(
    *,
    actor,
    course,
    status=SessionStatus.ENROLLMENT_OPEN,
    start_in_days=7,
    duration_days=2,
    fee="0",
    capacity=10,
    **fields,
) -> TrainingSession:
    today = timezone.localdate()
    fields.setdefault("title", "Cohort 1")
    fields.setdefault("start_date", today + timedelta(days=start_in_days))
    fields.setdefault("end_date", today + timedelta(days=start_in_days + duration_days))
    return services.create_session(
        actor=actor,
        course=course,
        status=status,
        capacity=capacity,
        fee=Decimal(str(fee)),
        **fields,
    )


def make_instructor(*, actor, user, **fields):
    return services.create_instructor_profile(actor=actor, user=user, **fields)


def enroll(*, student, session, actor=None, note=""):
    return services.submit_enrollment(
        student=student, session=session, actor=actor or student, note=note
    )


def make_assessment(
    *,
    actor,
    course,
    title="Quiz",
    publish=False,
    completion_required=True,
    max_attempts=1,
    passing_score="50",
    **fields,
):
    assessment = services.create_assessment(
        actor=actor,
        course=course,
        title=title,
        completion_required=completion_required,
        max_attempts=max_attempts,
        passing_score=Decimal(str(passing_score)),
        **fields,
    )
    if publish:
        if not assessment.questions.exists():
            add_mc_question(actor=actor, assessment=assessment, prompt="Q1")
        services.publish_assessment(assessment, actor=actor)
        assessment.refresh_from_db()
    return assessment


def add_mc_question(
    *, actor, assessment, prompt="Question", points="1", correct_first=True, options=("A", "B")
):
    question = services.add_question(
        actor=actor,
        assessment=assessment,
        prompt=prompt,
        question_type="multiple_choice",
        points=Decimal(str(points)),
    )
    for index, text in enumerate(options, start=1):
        services.add_option(
            actor=actor,
            question=question,
            text=text,
            is_correct=(index == 1 if correct_first else False),
            sort_order=index,
        )
    return question


def add_short_answer(*, actor, assessment, prompt="Describe", points="5"):
    return services.add_question(
        actor=actor,
        assessment=assessment,
        prompt=prompt,
        question_type="short_answer",
        points=Decimal(str(points)),
    )


def answer_map(*, questions, correct=True):
    """Build POST answers for objective questions, picking the correct option."""
    answers = {}
    for question in questions:
        options = list(question.options.order_by("sort_order").all())
        if not options:
            continue
        correct_option = next((option for option in options if option.is_correct), None)
        if correct:
            chosen = correct_option or options[0]
        else:
            wrong = [option for option in options if option != correct_option]
            chosen = wrong[0] if wrong else options[0]
        answers[str(question.pk)] = str(chosen.pk)
    return answers

"""Celery tasks for the training academy."""

from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from . import notifications
from .models import (
    CONFIRMED_ENROLLMENT_STATUSES,
    SessionStatus,
    TrainingSession,
)

REMINDABLE_STATUSES = [
    SessionStatus.SCHEDULED,
    SessionStatus.ENROLLMENT_OPEN,
    SessionStatus.ENROLLMENT_CLOSED,
]


@shared_task(name="training.send_session_reminders")
def send_session_reminders(*, within_days: int = 3) -> int:
    """Email a reminder to confirmed students of sessions starting soon.

    Date-keyed dedupe keys make repeat runs idempotent.
    """
    today = timezone.localdate()
    horizon = today + timedelta(days=within_days)
    sessions = TrainingSession.objects.filter(
        status__in=REMINDABLE_STATUSES,
        start_date__gte=today,
        start_date__lte=horizon,
    )
    sent = 0
    for session in sessions:
        for enrollment in session.enrollments.filter(status__in=CONFIRMED_ENROLLMENT_STATUSES):
            if notifications.session_reminder(enrollment, dedupe_suffix=str(session.start_date)):
                sent += 1
    return sent

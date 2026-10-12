"""Celery application factory.

Start a worker with::

    uv run celery -A config worker -l info
    uv run celery -A config beat -l info
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("aa_shinaka")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> None:  # pragma: no cover - operational helper
    """Trivial task used to smoke-test a running worker."""
    print(f"Request: {self.request!r}")

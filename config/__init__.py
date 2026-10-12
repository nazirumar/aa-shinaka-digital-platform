"""Expose the Celery app so it loads on Django startup."""

from .celery import app as celery_app

__all__ = ("celery_app",)

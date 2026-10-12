"""Development settings. Relaxed security, verbose errors, console email."""

from .base import *  # noqa: F403
from .base import BASE_DIR, MIDDLEWARE, env  # noqa: F401

DEBUG = True

# Django's staticfiles app serves static files in DEBUG; WhiteNoise is only
# needed behind a real WSGI server. Removing it avoids a missing-STATIC_ROOT
# warning during local development and tests.
MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

INTERNAL_IPS = ["127.0.0.1"]

# Run Celery tasks inline during local development unless a broker is running.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

# Fail fast on startup if the database is misconfigured.
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405

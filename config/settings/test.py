"""Test settings.

Extend the development settings with fast, deterministic overrides so the suite
runs quickly in CI and never touches a real mail server, broker or password
hash. ``pytest`` loads this module (see ``[tool.pytest.ini_options]``).
"""

from __future__ import annotations

import tempfile

from .dev import *  # noqa: F403
from .dev import BASE_DIR, env  # noqa: F401

DEBUG = False

# Tests assert on auth behaviour, not hashing cost: MD5 keeps the suite fast.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Never dispatch background work during unit tests.
CELERY_TASK_ALWAYS_EAGER = True

# Capture outbound mail in memory instead of printing it.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Never call a live payment provider from the test suite.
PAYSTACK_ENABLED = False
PAYSTACK_SECRET_KEY = ""
PAYSTACK_PUBLIC_KEY = ""

# A throwaway media directory keeps generated files out of the repository.
MEDIA_ROOT = tempfile.mkdtemp(prefix="aa-shinaka-test-media-")

# Deterministic, in-process cache for rate limiting.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

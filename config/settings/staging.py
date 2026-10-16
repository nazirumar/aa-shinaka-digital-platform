"""Staging settings.

Staging is a **production-shaped** environment used to verify a release before
the owner approves a controlled production launch. It inherits every hardened
production control (``DEBUG=False``, secure cookies, HSTS, SSL redirect, Redis
cache, real email) and adds one rule the brief requires:

    **Staging must never move real money.**

A live Paystack key or an enabled live mode therefore fails fast at import time
via :func:`config.settings._guards.assert_staging_paystack_is_test_only`.

Operational isolation is enforced outside the code as well: use a **separate
database, Redis instance, media volume and `.env.staging`** from production (see
``deploy/.env.staging.example`` and ``deploy/docker-compose.staging.yml``). The
settings module deliberately does not guess the host, domain or credentials — all
of it comes from the environment.

Run with::

    DJANGO_SETTINGS_MODULE=config.settings.staging python manage.py check --deploy
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from ._guards import DeploymentGuardError, assert_staging_paystack_is_test_only
from .base import env  # noqa: F401
from .prod import *  # noqa: F403

# A marker other code (and the deployment verifier) can key on.
ENVIRONMENT = "staging"
STAGING = True

# ---------------------------------------------------------------------------
# Hard guard: staging is test-mode only.
# ---------------------------------------------------------------------------
try:
    assert_staging_paystack_is_test_only(
        live_mode=PAYSTACK_LIVE_MODE,  # noqa: F405
        secret_key=env("PAYSTACK_SECRET_KEY", default=""),
    )
except DeploymentGuardError as exc:  # pragma: no cover - exercised via subprocess
    raise ImproperlyConfigured(str(exc)) from exc

# ---------------------------------------------------------------------------
# Staging should exercise the *enforcing* upload policy so the release gate
# behaves exactly as it will in production (fail closed on scanner errors).
# ---------------------------------------------------------------------------
UPLOAD_SCAN_ENFORCEMENT = env("UPLOAD_SCAN_ENFORCEMENT", default="enforce")

# ---------------------------------------------------------------------------
# Keep HSTS short/optional on staging so an operator can roll back a broken TLS
# setup without the 30-day pin; production keeps the longer value from prod.py.
# ---------------------------------------------------------------------------
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = False

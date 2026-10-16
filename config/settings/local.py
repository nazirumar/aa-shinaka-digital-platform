"""Local-test settings — the production shape over plain HTTP, on a laptop.

This module lets a developer run the **entire production container stack**
(nginx, Gunicorn, PostgreSQL, Redis, Celery worker + beat, a capture inbox) with
``deploy/docker-compose.local.yml`` and exercise it end-to-end before any VPS,
domain or certificate exists.

It inherits every production control and relaxes **only** the three things that
make plain-HTTP local testing impossible:

    * ``CSRF_TRUSTED_ORIGINS`` may be an ``http://`` origin;
    * the session and CSRF cookies are not ``Secure``-only, because the browser
      would otherwise refuse to send them over ``http://localhost``;
    * the HTTPS redirect and HSTS are off, so ``http://localhost:8080`` answers.

Everything else stays exactly as production: ``DEBUG=False``, Redis cache, real
SMTP delivery (pointed at a local capture inbox), the Paystack live-key guard,
upload-scan enforcement and structured logging.

NEVER run this module on staging or production. It is selected only by
``deploy/docker-compose.local.yml``; ``deploy/scripts/validate_env.sh`` refuses
to bless a production/staging env file that selects it.

Paystack stays test-only here for the same reason as staging: no live money is
ever moved from a developer machine.
"""

from __future__ import annotations

from .base import env  # noqa: F401
from .prod import *  # noqa: F403

# A marker other code (and the deployment verifier) can key on.
ENVIRONMENT = "local"
LOCAL = True

# ---------------------------------------------------------------------------
# Plain-HTTP allowances (the only production controls relaxed here).
# ---------------------------------------------------------------------------
# prod.py only accepts https:// origins, so deploy/.env.local leaves
# CSRF_TRUSTED_ORIGINS unset and this module supplies the local origin. The
# `or` also covers an empty-but-present value (django-environ parses "" to []).
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[]) or [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# No TLS terminator in front of the local stack.
SECURE_PROXY_SSL_HEADER = None

# ---------------------------------------------------------------------------
# Paystack: test mode only, exactly as on staging.
# ---------------------------------------------------------------------------
PAYSTACK_LIVE_MODE = False  # noqa: F405

# ---------------------------------------------------------------------------
# Upload scanning mirrors production's scanner but tolerates a missing scanner
# so a developer without the `scanning` profile is not blocked. "log" is the
# codebase's non-enforcing value (see apps/core/upload_security.py); production
# and staging keep "enforce".
# ---------------------------------------------------------------------------
UPLOAD_SCAN_ENFORCEMENT = env("UPLOAD_SCAN_ENFORCEMENT", default="log")

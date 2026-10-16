"""Production settings.

These settings assume the application runs behind a TLS-terminating reverse
proxy (nginx or the platform load balancer) and that every secret is injected
through the environment. They fail loudly at import time when a required value
is missing or obviously insecure, so a misconfigured deployment never boots in
a half-secure state.

Generate a secret key with::

    uv run python -c "import secrets; print(secrets.token_urlsafe(64))"
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import DATABASES, SECRET_KEY, env  # noqa: F401

DEBUG = False

# ---------------------------------------------------------------------------
# Required secrets & hosts — no insecure fallbacks in production.
# ---------------------------------------------------------------------------
if SECRET_KEY.startswith("django-insecure") or SECRET_KEY == (
    "change-me-generate-a-50-char-random-string"
):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a strong, unique value in production."
    )
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is too short for production (use at least 50 characters)."
    )

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["*"]:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must list the real hostnames in production (never '*')."
    )

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
# Behind HTTPS every trusted origin must be an https:// origin.
for _origin in CSRF_TRUSTED_ORIGINS:
    if not _origin.startswith("https://"):
        raise ImproperlyConfigured(
            f"CSRF_TRUSTED_ORIGINS entries must use https:// (got {_origin!r})."
        )

# ---------------------------------------------------------------------------
# Database & cache — least-privilege credentials come from the environment.
# ---------------------------------------------------------------------------
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=600)
DATABASES["default"]["ATOMIC_REQUESTS"] = env.bool("DB_ATOMIC_REQUESTS", default=True)
DATABASES["default"]["OPTIONS"].setdefault("connect_timeout", 10)
if env.bool("DB_SSLMODE_REQUIRE", default=True):
    # PostgreSQL SSL mode name for psycopg; safe to require on managed hosts.
    DATABASES["default"]["OPTIONS"].setdefault("sslmode", "require")

# Rate limiting and any shared state must be backed by Redis in production.
_cache_url = env("CACHE_URL", default="")
if not _cache_url.startswith("redis"):
    raise ImproperlyConfigured(
        "CACHE_URL must point at Redis in production (e.g. redis://127.0.0.1:6379/2)."
    )

# ---------------------------------------------------------------------------
# Email — real delivery only. Console/locmem backends are rejected.
# ---------------------------------------------------------------------------
_email_backend = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
if "console" in _email_backend or "locmem" in _email_backend or "dummy" in _email_backend:
    raise ImproperlyConfigured(
        "EMAIL_BACKEND must be a real delivery backend in production (SMTP/API)."
    )
EMAIL_BACKEND = _email_backend
if not EMAIL_HOST or EMAIL_HOST == "localhost":  # noqa: F405
    raise ImproperlyConfigured("EMAIL_HOST must be set to the production mail host.")

# ---------------------------------------------------------------------------
# HTTPS / transport security. HSTS preload stays off until it has been verified
# (see docs/PRODUCTION_RUNBOOK.md) to avoid an irreversible mistake.
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env.bool("USE_X_FORWARDED_HOST", default=True)
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
# Only enable once *all* subdomains are permanently HTTPS: preload is hard to undo.
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = env.bool("SESSION_EXPIRE_AT_BROWSER_CLOSE", default=False)

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Static files — hashed, compressed manifest served by WhiteNoise.
# ---------------------------------------------------------------------------
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}
WHITENOISE_MAX_AGE = env.int("WHITENOISE_MAX_AGE", default=60 * 60 * 24 * 365)

# ---------------------------------------------------------------------------
# Password hashing — keep Django's strong defaults, state them explicitly.
# ---------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

# ---------------------------------------------------------------------------
# Error reporting & logging — structured single-line JSON to stdout so it can be
# collected by the container/platform log driver. Customer PII is never logged.
# ---------------------------------------------------------------------------
ADMINS = [("AA Shinaka Operations", env("OPS_EMAIL", default="ops@example.invalid"))]
SERVER_EMAIL = env("SERVER_EMAIL", default=ADMINS[0][1])

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "config.observability.JsonFormatter"},
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", default="INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

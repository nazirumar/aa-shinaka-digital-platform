"""
Base Django settings for the AA Shinaka Digital Business Platform.

Environment-specific modules (``dev``, ``prod``) import from here. All secrets
and deployment-specific values are read from environment variables via
``django-environ``; nothing sensitive is hardcoded.
"""

from pathlib import Path

import environ

# BASE_DIR points at the repository root (…/aa-shinaka-digital-platform).
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", "[::1]"]),
    DB_CONN_MAX_AGE=(int, 60),
    EMAIL_PORT=(int, 587),
    EMAIL_USE_TLS=(bool, True),
    EMAIL_VERIFICATION_TIMEOUT=(int, 60 * 60 * 48),  # 48 hours
    PASSWORD_RESET_TIMEOUT=(int, 60 * 60 * 24),  # 24 hours
    SESSION_COOKIE_AGE=(int, 60 * 60 * 24 * 14),  # 14 days
)

# Read a local .env if present. Never commit this file.
environ.Env.read_env(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-change-me-in-production")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.contrib.humanize",
]

LOCAL_APPS = [
    "apps.core",
    "apps.locations",
    "apps.accounts",
    # Staff MFA (TOTP) — Phase 13. Separate app label so its migrations
    # and admin registration stay isolated from the core accounts app.
    "apps.accounts.mfa",
    "apps.catalog",
    "apps.orders",
    "apps.services",
    "apps.export",
    "apps.dashboard",
    "apps.cms",
    "apps.training",
    "apps.notifications",
    "apps.support",
    "apps.analytics",
]

THIRD_PARTY_APPS: list[str] = []

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.unread_notifications",
                "apps.dashboard.context_processors.notifications",
                "apps.cms.context_processors.site_context",
                "apps.orders.context_processors.cart_summary",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database — PostgreSQL via DATABASE_URL
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://aa_shinaka:aa_shinaka_dev_pw@127.0.0.1:5432/aa_shinaka",
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = env("DB_CONN_MAX_AGE")
DATABASES["default"].setdefault("OPTIONS", {})

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "account:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

# Token lifetimes (seconds) used by email verification and password reset.
EMAIL_VERIFICATION_TIMEOUT = env("EMAIL_VERIFICATION_TIMEOUT")
PASSWORD_RESET_TIMEOUT = env("PASSWORD_RESET_TIMEOUT")

# ---------------------------------------------------------------------------
# Cache — used for rate limiting and (in production) shared state.
# ---------------------------------------------------------------------------
CACHES = {
    "default": env.cache("CACHE_URL", default="locmem://"),
}

# ---------------------------------------------------------------------------
# Security (development-safe defaults; production tightens these further)
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env("SESSION_COOKIE_AGE")
CSRF_COOKIE_SAMESITE = "Lax"
# No JavaScript in the project reads the CSRF cookie (HTMX/Alpine submit the
# hidden ``{% csrf_token %}`` input), so the cookie can be kept HTTP-only.
CSRF_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Upload / request-size guards (defence in depth against memory-exhaustion).
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int("FILE_UPLOAD_MAX_MEMORY_SIZE", default=5 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int("DATA_UPLOAD_MAX_MEMORY_SIZE", default=5 * 1024 * 1024)
DATA_UPLOAD_MAX_NUMBER_FIELDS = env.int("DATA_UPLOAD_MAX_NUMBER_FIELDS", default=2000)

# ---------------------------------------------------------------------------
# Upload scanning & quarantine (Phase 13, Step 4)
# ---------------------------------------------------------------------------
# enforce: unscannable uploads are rejected and unscanned files cannot be
# downloaded (fail closed). log: scanner *failures* are audited and allowed
# through; positively identified malware is blocked in both modes.
UPLOAD_SCAN_ENFORCEMENT = env("UPLOAD_SCAN_ENFORCEMENT", default="enforce")
# Optional ClamAV integration. With neither set, only the built-in signature
# scanner (EICAR fixture + executable-header checks) runs.
CLAMAV_SOCKET = env("CLAMAV_SOCKET", default="")
CLAMAV_HOST = env("CLAMAV_HOST", default="")
CLAMAV_PORT = env.int("CLAMAV_PORT", default=3310)
CLAMAV_TIMEOUT = env.int("CLAMAV_TIMEOUT", default=20)
# Hard cap on how much of one upload is read into memory for scanning.
UPLOAD_SCAN_MAX_BYTES = env.int("UPLOAD_SCAN_MAX_BYTES", default=32 * 1024 * 1024)

# Authentication rate limiting (attempts / window in seconds).
LOGIN_RATE_LIMIT_ATTEMPTS = env.int("LOGIN_RATE_LIMIT_ATTEMPTS", default=10)
LOGIN_RATE_LIMIT_WINDOW = env.int("LOGIN_RATE_LIMIT_WINDOW", default=300)
FORM_RATE_LIMIT_ATTEMPTS = env.int("FORM_RATE_LIMIT_ATTEMPTS", default=20)
FORM_RATE_LIMIT_WINDOW = env.int("FORM_RATE_LIMIT_WINDOW", default=3600)

# ---------------------------------------------------------------------------
# Multi-factor authentication (Phase 13, privileged staff only)
# ---------------------------------------------------------------------------
# How long a parked (password-ok, MFA-not-yet-passed) login session survives.
MFA_CHALLENGE_TIMEOUT = env.int("MFA_CHALLENGE_TIMEOUT", default=300)  # 5 minutes
# TOTP verification attempts per window, keyed by user id + client IP.
MFA_RATE_LIMIT_ATTEMPTS = env.int("MFA_RATE_LIMIT_ATTEMPTS", default=5)
MFA_RATE_LIMIT_WINDOW = env.int("MFA_RATE_LIMIT_WINDOW", default=300)

# ---------------------------------------------------------------------------
# Commerce business rules (Phase 5). No rate is invented — defaults are zero.
# ---------------------------------------------------------------------------
# How long an unpaid order's stock reservation is held before it expires.
ORDER_RESERVATION_TTL_HOURS = env.int("ORDER_RESERVATION_TTL_HOURS", default=48)
# Tax is applied only when finance configures a rate (ASSUMPTION-04).
ORDER_TAX_RATE = env("ORDER_TAX_RATE", default="0.00")

# ---------------------------------------------------------------------------
# Paystack (Phase 6). Test mode is the default: nothing is enabled until a
# secret key is configured, and CI never needs live credentials.
# ---------------------------------------------------------------------------
PAYSTACK_ENABLED = env.bool("PAYSTACK_ENABLED", default=False)
PAYSTACK_SECRET_KEY = env("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = env("PAYSTACK_PUBLIC_KEY", default="")
# Phase 13 launch gate: the platform is test-mode only. A live key (sk_live_…)
# is ignored (payments fail closed) unless this is explicitly switched on after
# the owner approves a production launch.
PAYSTACK_LIVE_MODE = env.bool("PAYSTACK_LIVE_MODE", default=False)
# Paystack signs webhooks with the secret key; set this only if you enable a
# separate webhook secret in the dashboard.
PAYSTACK_WEBHOOK_SECRET = env("PAYSTACK_WEBHOOK_SECRET", default="")
PAYSTACK_API_BASE_URL = env("PAYSTACK_API_BASE_URL", default="https://api.paystack.co")
PAYSTACK_CURRENCY = env("PAYSTACK_CURRENCY", default="NGN")
PAYSTACK_TIMEOUT = env.int("PAYSTACK_TIMEOUT", default=20)
# Absolute URL Paystack redirects to after checkout. Leave blank to derive it
# from the request (recommended); set it explicitly behind a proxy.
PAYSTACK_CALLBACK_URL = env("PAYSTACK_CALLBACK_URL", default="")

# ---------------------------------------------------------------------------
# Notifications & support (Phase 10). Real channels only: email is on by
# default via the configured mail backend; SMS/WhatsApp stay disabled until an
# approved provider is configured. No provider credentials are hardcoded.
# ---------------------------------------------------------------------------
NOTIFICATION_EMAIL_ENABLED = env.bool("NOTIFICATION_EMAIL_ENABLED", default=True)
NOTIFICATION_MAX_ATTEMPTS = env.int("NOTIFICATION_MAX_ATTEMPTS", default=3)
# Absolute site URL used to build links inside notification emails.
SITE_URL = env("SITE_URL", default="")
# Optional channels — inert until a provider is configured and the user opts in.
SMS_PROVIDER_URL = env("SMS_PROVIDER_URL", default="")
SMS_PROVIDER_API_KEY = env("SMS_PROVIDER_API_KEY", default="")
WHATSAPP_PROVIDER_URL = env("WHATSAPP_PROVIDER_URL", default="")
WHATSAPP_PROVIDER_API_KEY = env("WHATSAPP_PROVIDER_API_KEY", default="")

# ---------------------------------------------------------------------------
# Analytics & reporting (Phase 11). Figures are always derived from the
# authoritative source tables; nothing here stores business data.
# ---------------------------------------------------------------------------
# The single currency used for the "base currency" KPIs. Other currencies are
# still reported per currency and are never summed into this one.
ANALYTICS_BASE_CURRENCY = env("ANALYTICS_BASE_CURRENCY", default="NGN")
# Reserved: a mapping of currency code -> rate against the base currency. No
# cross-currency total is ever produced while this is empty.
ANALYTICS_EXCHANGE_RATES = env.dict("ANALYTICS_EXCHANGE_RATES", default={})
# Generated report files are deleted this many days after generation.
ANALYTICS_REPORT_RETENTION_DAYS = env.int("ANALYTICS_REPORT_RETENTION_DAYS", default=30)
# When True the request queues a report and a worker renders it; when False
# (the default) reports render synchronously so no worker is required.
ANALYTICS_EXPORT_ASYNC = env.bool("ANALYTICS_EXPORT_ASYNC", default=False)

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

# English is the source language; Hausa is prepared but not fully translated —
# see locale/ha/LC_MESSAGES/django.po. Content itself is not auto-translated.
LANGUAGES = [
    ("en", "English"),
    ("ha", "Hausa"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Celery / Redis
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://127.0.0.1:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 30
CELERY_TASK_ALWAYS_EAGER = False  # tests override this to True
# Periodically release stock held by abandoned pending-payment orders. The same
# logic is available as ``manage.py expire_orders`` for deployments without beat.
CELERY_BEAT_SCHEDULE = {
    "expire-order-reservations": {
        "task": "orders.expire_reservations",
        "schedule": 60 * 30,  # every 30 minutes
    },
    "reconcile-paystack-payments": {
        "task": "orders.reconcile_payments",
        "schedule": 60 * 60,  # every hour
    },
    "training-send-session-reminders": {
        "task": "training.send_session_reminders",
        "schedule": 60 * 60 * 12,  # twice a day
    },
    # Generate any due scheduled reports (idempotent per period).
    "run-scheduled-reports": {
        "task": "analytics.run_scheduled_reports",
        "schedule": 60 * 60,  # every hour
    },
    # Delete stored report exports past their retention window.
    "cleanup-report-exports": {
        "task": "analytics.cleanup_report_exports",
        "schedule": 60 * 60 * 24,  # daily
    },
}

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="AA Shinaka <no-reply@aashinaka.local>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env("EMAIL_PORT")
EMAIL_USE_TLS = env("EMAIL_USE_TLS")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)

# ---------------------------------------------------------------------------
# Messages -> Tailwind-friendly CSS classes
# ---------------------------------------------------------------------------
from django.contrib.messages import constants as messages  # noqa: E402

MESSAGE_TAGS = {
    messages.DEBUG: "debug",
    messages.INFO: "info",
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "error",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

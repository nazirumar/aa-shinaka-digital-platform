"""Render deployment regression coverage.

These tests pin the production/Render configuration and the crash-proof error
page. They are grouped by the deployment-readiness checklist: database URL
parsing, cache/static configuration, Render host trust, the 500 template, the
Celery-beat fallback for periodic jobs and the failure logging of the original
exception.

Settings-module tests shell out to ``manage.py`` so the production module is
exercised in a clean interpreter (importing it here would require a fully
populated environment and would run the prod guards against the test process).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
from django.template.loader import get_template
from django.test import override_settings
from django.urls import path, reverse

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_500 = REPO_ROOT / "templates" / "500.html"

# A safe, non-secret production environment. Never contains a live credential.
_PROD_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings.prod",
    "DJANGO_SECRET_KEY": "k" * 60,
    "DJANGO_ALLOWED_HOSTS": "example.com",
    "CSRF_TRUSTED_ORIGINS": "https://example.com",
    "CACHE_URL": "redis://localhost:6379/2",
    "DATABASE_URL": "postgres://u:p@localhost:5432/db",
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_HOST": "smtp.example.com",
}

# Values dumped from a fresh interpreter running the production settings.
_DUMP_CODE = (
    "import json;"
    "from django.conf import settings as s;"
    "print(json.dumps({"
    "'DEBUG': s.DEBUG,"
    "'DATABASES': s.DATABASES,"
    "'CACHES': s.CACHES,"
    "'ALLOWED_HOSTS': s.ALLOWED_HOSTS,"
    "'CSRF_TRUSTED_ORIGINS': s.CSRF_TRUSTED_ORIGINS,"
    "'STORAGES': s.STORAGES,"
    "'PAYSTACK_ENABLED': s.PAYSTACK_ENABLED,"
    "'PAYSTACK_LIVE_MODE': s.PAYSTACK_LIVE_MODE,"
    "'SESSION_COOKIE_SECURE': s.SESSION_COOKIE_SECURE,"
    "'CSRF_COOKIE_SECURE': s.CSRF_COOKIE_SECURE,"
    "'SECURE_HSTS_SECONDS': s.SECURE_HSTS_SECONDS,"
    "'SECURE_SSL_REDIRECT': s.SECURE_SSL_REDIRECT,"
    "'SECURE_PROXY_SSL_HEADER': s.SECURE_PROXY_SSL_HEADER,"
    "'CELERY_ENABLED': s.CELERY_ENABLED,"
    "'CELERY_TASK_ALWAYS_EAGER': s.CELERY_TASK_ALWAYS_EAGER,"
    "'CELERY_TASK_ACKS_LATE': s.CELERY_TASK_ACKS_LATE,"
    "'CELERY_TASK_REJECT_ON_WORKER_LOST': s.CELERY_TASK_REJECT_ON_WORKER_LOST,"
    "'MEDIA_ROOT': str(s.MEDIA_ROOT),"
    "'EMAIL_BACKEND': s.EMAIL_BACKEND,"
    "}, default=str))"
)


def _run_manage(args: list[str], extra_env: dict[str, str] | None = None):
    env = {**os.environ, **_PROD_ENV, **(extra_env or {})}
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )


def _dump_settings(extra_env: dict[str, str] | None = None) -> dict:
    result = _run_manage(["shell", "-c", _DUMP_CODE], extra_env)
    assert result.returncode == 0, result.stdout + result.stderr
    # `manage.py shell -c` prints the value; the last line is our JSON.
    return json.loads(result.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def test_database_url_is_parsed_with_ssl_and_timeout():
    settings = _dump_settings(
        {"DATABASE_URL": "postgresql://u:p%40ss@db.internal:5432/app?sslmode=require"}
    )
    db = settings["DATABASES"]["default"]

    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert db["NAME"] == "app"
    assert db["USER"] == "u"
    assert db["PASSWORD"] == "p@ss"  # percent-encoding decoded
    assert db["HOST"] == "db.internal"
    assert db["OPTIONS"]["sslmode"] == "require"
    assert db["OPTIONS"]["connect_timeout"] == 10


def test_database_url_ssl_mode_can_be_disabled_for_internal_hosts():
    settings = _dump_settings({"DB_SSLMODE_REQUIRE": "false"})
    assert "sslmode" not in settings["DATABASES"]["default"]["OPTIONS"]


# ---------------------------------------------------------------------------
# Cache, static files and static storage
# ---------------------------------------------------------------------------


def test_production_cache_uses_redis():
    settings = _dump_settings()
    assert "redis" in settings["CACHES"]["default"]["BACKEND"]


def test_production_static_storage_is_hashed_manifest():
    settings = _dump_settings()
    assert (
        settings["STORAGES"]["staticfiles"]["BACKEND"]
        == "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )


# ---------------------------------------------------------------------------
# Hosts / CSRF (Render-injected values)
# ---------------------------------------------------------------------------


def test_render_hostname_and_url_are_trusted():
    settings = _dump_settings(
        {
            "RENDER_EXTERNAL_HOSTNAME": "aa-shinaka-web-abc1.onrender.com",
            "RENDER_EXTERNAL_URL": "https://aa-shinaka-web-abc1.onrender.com",
        }
    )

    assert "aa-shinaka-web-abc1.onrender.com" in settings["ALLOWED_HOSTS"]
    assert "https://aa-shinaka-web-abc1.onrender.com" in settings["CSRF_TRUSTED_ORIGINS"]


def test_render_origin_is_not_duplicated():
    settings = _dump_settings(
        {
            "CSRF_TRUSTED_ORIGINS": "https://example.com,https://aa-x.onrender.com",
            "RENDER_EXTERNAL_URL": "https://aa-x.onrender.com/",
        }
    )
    assert settings["CSRF_TRUSTED_ORIGINS"].count("https://aa-x.onrender.com") == 1


# ---------------------------------------------------------------------------
# Transport security / payment kill switch
# ---------------------------------------------------------------------------


def test_transport_security_is_not_weakened():
    # .env may relax these locally, so pin the production values explicitly.
    settings = _dump_settings(
        {
            "DJANGO_SECURE_SSL_REDIRECT": "true",
            "DJANGO_SECURE_HSTS_SECONDS": "2592000",
        }
    )

    assert settings["DEBUG"] is False
    assert settings["SESSION_COOKIE_SECURE"] is True
    assert settings["CSRF_COOKIE_SECURE"] is True
    assert settings["SECURE_SSL_REDIRECT"] is True
    assert settings["SECURE_HSTS_SECONDS"] > 0
    assert settings["SECURE_PROXY_SSL_HEADER"] == ["HTTP_X_FORWARDED_PROTO", "https"]


def test_paystack_is_disabled_in_production_by_default():
    settings = _dump_settings()
    assert settings["PAYSTACK_ENABLED"] is False
    assert settings["PAYSTACK_LIVE_MODE"] is False


def test_check_deploy_passes_with_render_like_environment():
    result = _run_manage(["check", "--deploy", "--fail-level", "ERROR"])
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Celery reliability / fallback
# ---------------------------------------------------------------------------


def test_celery_enabled_by_default_with_reliability_guards():
    settings = _dump_settings()
    assert settings["CELERY_ENABLED"] is True
    assert settings["CELERY_TASK_ALWAYS_EAGER"] is False
    assert settings["CELERY_TASK_ACKS_LATE"] is True
    assert settings["CELERY_TASK_REJECT_ON_WORKER_LOST"] is True


def test_celery_disabled_runs_tasks_inline():
    settings = _dump_settings({"CELERY_ENABLED": "false"})
    assert settings["CELERY_ENABLED"] is False
    assert settings["CELERY_TASK_ALWAYS_EAGER"] is True


def test_short_scheduled_jobs_token_is_rejected():
    result = _run_manage(["check"], {"SCHEDULED_JOBS_TOKEN": "too-short"})
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Email backends
# ---------------------------------------------------------------------------


def test_resend_backend_requires_an_api_key():
    result = _run_manage(
        ["check"],
        {"EMAIL_BACKEND": "config.email_backends.ResendEmailBackend", "RESEND_API_KEY": ""},
    )
    assert result.returncode != 0
    assert "RESEND_API_KEY" in result.stdout + result.stderr


def test_resend_backend_accepted_with_api_key():
    result = _run_manage(
        ["check", "--deploy", "--fail-level", "ERROR"],
        {
            "EMAIL_BACKEND": "config.email_backends.ResendEmailBackend",
            "RESEND_API_KEY": "re_test_key",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_resend_backend_posts_to_the_api(settings):
    settings.RESEND_API_KEY = "re_test_key"
    settings.DEFAULT_FROM_EMAIL = "AA Shinaka <no-reply@example.com>"

    from django.core.mail import EmailMultiAlternatives

    from config.email_backends import ResendEmailBackend

    message = EmailMultiAlternatives(
        subject="Verify your email",
        body="Plain body",
        from_email="AA Shinaka <no-reply@example.com>",
        to=["customer@example.com"],
    )
    message.attach_alternative("<p>HTML body</p>", "text/html")

    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    with mock.patch("config.email_backends.urllib.request.urlopen", side_effect=fake_urlopen):
        sent = ResendEmailBackend().send_messages([message])

    assert sent == 1
    request = captured["request"]
    assert request.full_url == "https://api.resend.com/emails"
    assert request.headers["Authorization"] == "Bearer re_test_key"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["to"] == ["customer@example.com"]
    assert payload["subject"] == "Verify your email"
    assert payload["text"] == "Plain body"
    assert payload["html"] == "<p>HTML body</p>"


def test_resend_backend_failure_is_not_silent(settings):
    settings.RESEND_API_KEY = "re_test_key"

    from django.core.mail import EmailMessage

    from config.email_backends import ResendEmailBackend

    with mock.patch(
        "config.email_backends.urllib.request.urlopen",
        side_effect=OSError("network down"),
    ):
        with pytest.raises(OSError):
            ResendEmailBackend(fail_silently=False).send_messages(
                [EmailMessage("hi", "body", None, ["a@example.com"])]
            )
        assert (
            ResendEmailBackend(fail_silently=True).send_messages(
                [EmailMessage("hi", "body", None, ["a@example.com"])]
            )
            == 0
        )


# ---------------------------------------------------------------------------
# 500 error page
# ---------------------------------------------------------------------------


def test_500_template_has_no_template_syntax():
    text = TEMPLATE_500.read_text(encoding="utf-8")

    assert "{{" not in text
    assert "{%" not in text
    assert "extends" not in text


@pytest.mark.django_db
def test_500_template_renders_without_context_or_queries():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as queries:
        html = get_template("500.html").render({})

    assert queries.captured_queries == []
    assert "Something went wrong" in html
    assert "500" in html


# A URLconf used only by the handler test below.
def _boom(request):
    raise RuntimeError("original-boom")


urlpatterns = [path("boom/", _boom)]


@pytest.mark.django_db
def test_original_exception_is_logged_separately_from_the_500_page():
    from django.test import Client

    client = Client(raise_request_exception=False)

    with override_settings(DEBUG=False, ROOT_URLCONF=__name__):
        with mock.patch.object(logging.getLogger("django.request"), "error") as log_error:
            response = client.get("/boom/")

    assert response.status_code == 500
    assert "Something went wrong" in response.content.decode("utf-8")
    assert log_error.called
    # The original exception is logged independently of the error page.
    message, *args = log_error.call_args.args
    assert "internal server error" in (str(message) % tuple(args)).lower()
    assert "original-boom" in str(log_error.call_args.kwargs.get("exc_info"))
    # And rendered by a logger every deployment collects.
    assert log_error.call_args.kwargs["extra"]["status_code"] == 500


# ---------------------------------------------------------------------------
# Periodic jobs fallback: command + endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_run_scheduled_jobs_command_succeeds_without_celery():
    import io

    from django.core.management import call_command

    out = io.StringIO()
    with override_settings(CELERY_ENABLED=False, CELERY_TASK_ALWAYS_EAGER=True):
        call_command("run_scheduled_jobs", "--json", stdout=out)

    payload = json.loads(out.getvalue().strip().splitlines()[-1])
    assert payload["failed"] == 0
    assert "expire_order_reservations" in payload["jobs"]


@pytest.mark.django_db
def test_scheduled_jobs_endpoint_is_disabled_without_a_token(client):
    with override_settings(SCHEDULED_JOBS_TOKEN=""):
        response = client.post(reverse("core:scheduled_jobs"))

    assert response.status_code == 404


@pytest.mark.django_db
def test_scheduled_jobs_endpoint_rejects_a_bad_token(client):
    with override_settings(SCHEDULED_JOBS_TOKEN="t" * 40, SCHEDULED_JOBS_MIN_INTERVAL=0):
        response = client.post(reverse("core:scheduled_jobs"), HTTP_X_SCHEDULED_JOBS_TOKEN="wrong")

    assert response.status_code == 403


@pytest.mark.django_db
def test_scheduled_jobs_endpoint_rejects_get(client):
    with override_settings(SCHEDULED_JOBS_TOKEN="t" * 40, SCHEDULED_JOBS_MIN_INTERVAL=0):
        response = client.get(reverse("core:scheduled_jobs"), HTTP_X_SCHEDULED_JOBS_TOKEN="t" * 40)

    assert response.status_code == 405


@pytest.mark.django_db
def test_scheduled_jobs_endpoint_runs_and_is_throttled(client):
    with override_settings(SCHEDULED_JOBS_TOKEN="t" * 40, SCHEDULED_JOBS_MIN_INTERVAL=60):
        first = client.post(reverse("core:scheduled_jobs"), HTTP_X_SCHEDULED_JOBS_TOKEN="t" * 40)
        second = client.post(reverse("core:scheduled_jobs"), HTTP_X_SCHEDULED_JOBS_TOKEN="t" * 40)

    assert first.status_code == 200
    assert first.json()["failed"] == 0
    assert second.status_code == 429


# ---------------------------------------------------------------------------
# Media configuration
# ---------------------------------------------------------------------------


def test_media_root_can_be_redirected_to_a_mounted_disk():
    settings = _dump_settings({"DJANGO_MEDIA_ROOT": "/var/lib/aa-shinaka/media"})
    assert settings["MEDIA_ROOT"].replace("\\", "/") == "/var/lib/aa-shinaka/media"


# ---------------------------------------------------------------------------
# Static files: the CSS manifest must exist and satisfy the templates
# ---------------------------------------------------------------------------
# Regression for the production 500:
#   ValueError: Missing staticfiles manifest entry for 'css/app.css'
# caused by a Render build that never ran `collectstatic`.


def test_build_script_compiles_css_and_collects_static_files():
    script = (REPO_ROOT / "build.sh").read_text(encoding="utf-8")

    # It must compile Tailwind, collect static, and verify both outputs.
    assert "npm run build:css" in script
    assert "collectstatic" in script
    assert "static/css/app.css" in script
    assert "staticfiles/staticfiles.json" in script
    # And fail fast rather than leave a half-built deploy.
    assert "set -euo pipefail" in script


def test_start_script_applies_migrations_before_serving():
    script = (REPO_ROOT / "start.sh").read_text(encoding="utf-8")

    assert "manage.py migrate" in script
    assert 'exec "$@"' in script


def test_free_blueprint_uses_the_build_and_start_scripts():
    text = (REPO_ROOT / "render.free.yaml").read_text(encoding="utf-8")

    assert "buildCommand: ./build.sh" in text
    assert "./start.sh gunicorn config.wsgi:application" in text
    assert "runtime: python" in text


def _collect_static_into(tmp_path: Path) -> Path:
    """Run the real collectstatic with the production manifest storage."""
    from django.core.management import call_command

    static_root = tmp_path / "staticfiles"
    static_root.mkdir(parents=True, exist_ok=True)
    with override_settings(
        DEBUG=False,
        STATIC_ROOT=str(static_root),
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
        },
    ):
        call_command("collectstatic", "--noinput", verbosity=0)
    return static_root


@pytest.mark.django_db
def test_homepage_renders_with_manifest_storage(client, tmp_path):
    static_root = _collect_static_into(tmp_path)

    # The mistake that broke production: the manifest was never produced.
    manifest_path = static_root / "staticfiles.json"
    assert manifest_path.exists(), "collectstatic did not produce a manifest"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "css/app.css" in manifest["paths"], "manifest is missing css/app.css"

    with override_settings(
        DEBUG=False,
        STATIC_ROOT=str(static_root),
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
        },
    ):
        response = client.get(reverse("core:home"))

    assert response.status_code == 200
    # The hashed stylesheet URL is emitted, proving the manifest was consulted.
    assert b"/static/css/app." in response.content


@pytest.mark.django_db
def test_dashboard_base_renders_with_manifest_storage(owner, tmp_path):
    """The staff layout references the same hashed stylesheet.

    ``dashboard/base.html`` reads ``user.email``/``full_name``/``display_role``
    and ``request.resolver_match``, so it needs a real staff user and a request
    rather than an anonymous context.
    """
    from django.template.loader import render_to_string
    from django.test import RequestFactory

    static_root = _collect_static_into(tmp_path)
    request = RequestFactory().get("/dashboard/")
    request.user = owner

    with override_settings(
        DEBUG=False,
        STATIC_ROOT=str(static_root),
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
        },
    ):
        html = render_to_string("dashboard/base.html", {"user": owner, "request": request})

    assert "/static/css/app." in html

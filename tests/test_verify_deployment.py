"""Phase 14 — tests for the ``verify_deployment`` management command."""

from __future__ import annotations

import json

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.core.management.commands.verify_deployment import FAIL, PASS, WARN


def _run(capsys, tmp_path, *args):
    """Run the command, capturing the JSON report and whether it exited non-zero."""
    report = tmp_path / "report.json"
    exited = False
    try:
        call_command("verify_deployment", "--json", str(report), *args)
    except SystemExit as exc:
        exited = bool(exc.code)
    capsys.readouterr()
    data = json.loads(report.read_text(encoding="utf-8"))
    return exited, data


def _status_by_key(data):
    return {check["key"]: check["status"] for check in data["checks"]}


@pytest.mark.django_db
def test_verify_deployment_reports_database_and_migrations(capsys, tmp_path):
    # Ensure the role groups exist so the roles check can pass.
    call_command("sync_roles")

    exited, data = _run(capsys, tmp_path)
    statuses = _status_by_key(data)

    assert statuses["database_connection"] == PASS
    assert statuses["database_engine"] == PASS
    assert statuses["migrations_applied"] == PASS
    assert statuses["role_groups"] == PASS
    assert statuses["cache"] == PASS
    assert statuses["media_writable"] == PASS
    assert statuses["quarantine_dir"] == PASS
    assert statuses["security_middleware"] == PASS
    # Every check carries the expected shape.
    assert all({"key", "title", "status", "detail"} <= set(c) for c in data["checks"])


@pytest.mark.django_db
def test_verify_deployment_fails_on_insecure_non_debug_settings(capsys, tmp_path):
    """In a non-debug environment an insecure setting is a hard FAIL (exit 1).

    The test settings already run with ``DEBUG=False`` and Secure cookies off,
    so no override is needed.
    """
    exited, data = _run(capsys, tmp_path)

    statuses = _status_by_key(data)
    assert statuses["secure_cookies"] == FAIL
    assert exited is True


@pytest.mark.django_db
def test_verify_deployment_downgrades_in_debug(capsys, tmp_path):
    """In DEBUG the same insecure setting is only a WARN (usable locally)."""
    with override_settings(
        DEBUG=True,
        SESSION_COOKIE_SECURE=False,
        CSRF_COOKIE_SECURE=False,
        SECURE_SSL_REDIRECT=False,
        SECURE_HSTS_SECONDS=0,
    ):
        exited, data = _run(capsys, tmp_path)

    statuses = _status_by_key(data)
    assert statuses["secure_cookies"] == WARN
    assert statuses["ssl_redirect"] == WARN
    assert statuses["hsts"] == WARN
    assert exited is False


@pytest.mark.django_db
def test_verify_deployment_celery_is_not_verified_when_eager(capsys, tmp_path):
    # The test settings run Celery eagerly, so the broker is not exercised.
    _, data = _run(capsys, tmp_path, "--check-celery")
    statuses = _status_by_key(data)
    assert statuses["celery_broker"] == "NOT VERIFIED"


@pytest.mark.django_db
def test_verify_deployment_paystack_guard_passes_without_live_key(capsys, tmp_path):
    with override_settings(
        PAYSTACK_ENABLED=False, PAYSTACK_LIVE_MODE=False, PAYSTACK_SECRET_KEY=""
    ):
        _, data = _run(capsys, tmp_path)
    assert _status_by_key(data)["paystack_test_mode"] == PASS


@pytest.mark.django_db
def test_verify_deployment_warns_on_live_key_without_live_mode(capsys, tmp_path):
    with override_settings(
        PAYSTACK_ENABLED=True,
        PAYSTACK_LIVE_MODE=False,
        PAYSTACK_SECRET_KEY="sk_live_misconfigured",
    ):
        _, data = _run(capsys, tmp_path)
    assert _status_by_key(data)["paystack_test_mode"] == WARN


@pytest.mark.django_db
def test_verify_deployment_staging_profile_flags_live_key(capsys, tmp_path):
    with override_settings(
        ENVIRONMENT="staging",
        PAYSTACK_ENABLED=True,
        PAYSTACK_LIVE_MODE=False,
        PAYSTACK_SECRET_KEY="sk_live_should_not_be_here",
    ):
        _, data = _run(capsys, tmp_path)
    assert _status_by_key(data)["paystack_test_mode"] == WARN

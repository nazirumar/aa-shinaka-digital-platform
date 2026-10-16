"""``verify_deployment`` — environment, database and security verifier.

Phase 14 (staging verification). A single, non-destructive command that answers
"is this environment safe and correctly provisioned to serve the platform?".

It is intentionally *read-only*: it never migrates, never writes business rows
and never calls a payment provider. Run it as a pre-deploy gate and as a
post-deploy smoke component:

    DJANGO_SETTINGS_MODULE=config.settings.staging \\
        python manage.py verify_deployment

Exit codes:
    0  no ``FAIL`` results (``WARN``/``NOT VERIFIED`` allowed)
    1  at least one ``FAIL``
    2  usage / environment error

Security checks are graded for the *configured* environment: while
``DEBUG=True`` (development) an insecure setting is reported as ``WARN`` so the
command is usable locally; in every non-debug environment (staging/production) an
insecure setting is a hard ``FAIL``.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from config.settings._guards import (
    DeploymentGuardError,
    assert_paystack_live_requires_live_mode,
    is_live_paystack_key,
)

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
NOT_VERIFIED = "NOT VERIFIED"

_ORDER = {FAIL: 0, WARN: 1, NOT_VERIFIED: 2, PASS: 3}


@dataclass
class CheckResult:
    key: str
    title: str
    status: str
    detail: str = ""


class Command(BaseCommand):
    help = "Verify the deployment environment (database, security, services)."

    def add_arguments(self, parser):
        parser.add_argument("--json", dest="json_path", default="", help="Write a JSON report.")
        parser.add_argument(
            "--check-celery",
            action="store_true",
            help="Also probe the Celery broker (can block briefly if unreachable).",
        )

    # -- helpers -----------------------------------------------------------
    def _grade(self, ok: bool, strict: bool, *, warn_only: bool = False) -> str:
        """PASS when ok; else FAIL (strict) or WARN (dev / warn_only)."""
        if ok:
            return PASS
        return WARN if (warn_only or not strict) else FAIL

    def handle(self, *args, **options):
        self.results: list[CheckResult] = []
        self.debug = bool(getattr(settings, "DEBUG", False))
        self.strict = not self.debug

        # Independent, ordered groups.
        self._check_core_security()
        self._check_database()
        self._check_roles_and_reference_data()
        self._check_services()
        self._check_payments()
        self._check_storage()

        if options.get("check_celery"):
            self._check_celery()

        self._report(options.get("json_path") or "")

        if any(result.status == FAIL for result in self.results):
            raise SystemExit(1)
        return None

    def _add(self, key: str, title: str, status: str, detail: str = "") -> None:
        self.results.append(CheckResult(key, title, status, detail))

    # -- groups ------------------------------------------------------------
    def _check_core_security(self) -> None:
        env_name = getattr(settings, "ENVIRONMENT", "development" if self.debug else "prod?")

        self._add("environment", "Configured environment", PASS, env_name)

        secret = getattr(settings, "SECRET_KEY", "")
        secret_ok = bool(secret) and len(secret) >= 50 and not secret.startswith("django-insecure")
        self._add(
            "secret_key",
            "SECRET_KEY is strong and unique",
            self._grade(secret_ok, self.strict),
            f"length={len(secret)}",
        )

        hosts = list(getattr(settings, "ALLOWED_HOSTS", []) or [])
        hosts_ok = bool(hosts) and "*" not in hosts
        self._add(
            "allowed_hosts",
            "ALLOWED_HOSTS is explicit (no wildcard)",
            self._grade(hosts_ok, self.strict),
            f"{len(hosts)} host(s)",
        )

        debug_ok = not self.debug
        self._add(
            "debug_off",
            "DEBUG is disabled",
            self._grade(debug_ok, self.strict),
            f"DEBUG={self.debug}",
        )

        secure_cookies = bool(getattr(settings, "SESSION_COOKIE_SECURE", False)) and bool(
            getattr(settings, "CSRF_COOKIE_SECURE", False)
        )
        self._add(
            "secure_cookies",
            "Session & CSRF cookies are Secure",
            self._grade(secure_cookies, self.strict),
        )

        httponly = bool(getattr(settings, "SESSION_COOKIE_HTTPONLY", False)) and bool(
            getattr(settings, "CSRF_COOKIE_HTTPONLY", False)
        )
        self._add("httponly_cookies", "Cookies are HttpOnly", self._grade(httponly, self.strict))

        ssl_redirect = bool(getattr(settings, "SECURE_SSL_REDIRECT", False))
        self._add(
            "ssl_redirect",
            "HTTPS redirect enforced",
            self._grade(ssl_redirect, self.strict),
        )

        hsts = int(getattr(settings, "SECURE_HSTS_SECONDS", 0) or 0)
        self._add(
            "hsts",
            "HSTS enabled",
            self._grade(hsts > 0, self.strict),
            f"max-age={hsts}s",
        )

        proxy_header = getattr(settings, "SECURE_PROXY_SSL_HEADER", None)
        self._add(
            "proxy_ssl_header",
            "Trusted proxy HTTPS header configured",
            self._grade(bool(proxy_header), self.strict, warn_only=True),
            str(proxy_header),
        )

        nosniff = bool(getattr(settings, "SECURE_CONTENT_TYPE_NOSNIFF", False))
        self._add("nosniff", "X-Content-Type-Options: nosniff", self._grade(nosniff, self.strict))

        middleware = list(getattr(settings, "MIDDLEWARE", []) or [])
        has_security = any("SecurityMiddleware" in m for m in middleware)
        self._add(
            "security_middleware",
            "SecurityMiddleware installed",
            self._grade(has_security, self.strict),
        )

    def _check_database(self) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.execute("SELECT version()")
                server_version = cursor.fetchone()[0]
            self._add(
                "database_connection",
                "PostgreSQL connection",
                PASS,
                server_version.split(",")[0][:60],
            )
        except Exception as exc:  # noqa: BLE001 - report any driver error
            self._add("database_connection", "PostgreSQL connection", FAIL, str(exc)[:200])
            return

        self._add(
            "database_engine",
            "Database engine is PostgreSQL",
            PASS if connection.vendor == "postgresql" else WARN,
            connection.vendor,
        )

        try:
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            plan = executor.migration_plan(targets)
            unapplied = [f"{m.app_label}.{m.name}" for m, _backwards in plan]
            self._add(
                "migrations_applied",
                "All migrations applied",
                PASS if not unapplied else FAIL,
                "up to date" if not unapplied else f"{len(unapplied)} unapplied: {unapplied[:5]}",
            )
        except Exception as exc:  # noqa: BLE001
            self._add("migrations_applied", "All migrations applied", FAIL, str(exc)[:200])

    def _check_roles_and_reference_data(self) -> None:
        from django.contrib.auth.models import Group

        from apps.accounts.models import UserRole

        try:
            groups = list(
                Group.objects.filter(name__startswith="role:").values_list("name", flat=True)
            )
            expected = {f"role:{role}" for role in UserRole.values}
            missing = sorted(expected - set(groups))
            self._add(
                "role_groups",
                "Role groups synchronised",
                PASS if not missing else FAIL,
                f"{len(groups)} present"
                + (f"; missing {len(missing)}: {missing}" if missing else ""),
            )
        except Exception as exc:  # noqa: BLE001
            self._add("role_groups", "Role groups synchronised", FAIL, str(exc)[:200])

        try:
            from apps.locations.models import LGA, Country, State

            ng = Country.objects.filter(code="NG").first()
            states = State.objects.count()
            lgas = LGA.objects.count()
            if ng is None:
                status, detail = WARN, "Nigeria (NG) not present"
            elif states == 37 and lgas == 774:
                status, detail = PASS, "37 states / 774 LGAs"
            else:
                status, detail = WARN, f"{states} states / {lgas} LGAs (expected 37 / 774)"
            self._add("reference_data", "Nigeria reference data imported", status, detail)
        except Exception as exc:  # noqa: BLE001
            self._add("reference_data", "Nigeria reference data imported", WARN, str(exc)[:200])

    def _check_services(self) -> None:
        # Cache round-trip.
        try:
            key = "verify_deployment:probe"
            cache.set(key, "ok", 30)
            value = cache.get(key)
            cache.delete(key)
            self._add(
                "cache",
                "Cache backend read/write",
                PASS if value == "ok" else FAIL,
                settings.CACHES["default"]["BACKEND"].rsplit(".", 1)[-1],
            )
        except Exception as exc:  # noqa: BLE001
            self._add("cache", "Cache backend read/write", FAIL, str(exc)[:200])

        # Static storage backend.
        try:
            backend = settings.STORAGES["staticfiles"]["BACKEND"].rsplit(".", 1)[-1]
            self._add("static_storage", "Static files storage", PASS, backend)
        except Exception as exc:  # noqa: BLE001
            self._add("static_storage", "Static files storage", WARN, str(exc)[:200])

    def _check_payments(self) -> None:
        enabled = bool(getattr(settings, "PAYSTACK_ENABLED", False))
        live_mode = bool(getattr(settings, "PAYSTACK_LIVE_MODE", False))
        secret = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
        env_name = getattr(settings, "ENVIRONMENT", "")

        live_key = is_live_paystack_key(secret)
        if env_name == "staging":
            status = WARN if (live_mode or live_key) else PASS
            self._add(
                "paystack_test_mode",
                "Paystack is test-mode only (staging)",
                status,
                f"enabled={enabled} live_mode={live_mode} live_key={live_key}",
            )
        else:
            try:
                assert_paystack_live_requires_live_mode(
                    enabled=enabled, live_mode=live_mode, secret_key=secret
                )
                status, detail = PASS, f"enabled={enabled} live_mode={live_mode}"
            except DeploymentGuardError as exc:
                status, detail = WARN, str(exc)
            self._add("paystack_test_mode", "Paystack live-key guard", status, detail)

    def _check_storage(self) -> None:
        from pathlib import Path

        media = Path(getattr(settings, "MEDIA_ROOT", ""))
        try:
            media.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=media, delete=True):
                pass
            self._add("media_writable", "MEDIA_ROOT is writable", PASS, str(media))
        except Exception as exc:  # noqa: BLE001
            self._add("media_writable", "MEDIA_ROOT is writable", FAIL, str(exc)[:200])

        quarantine = media / "quarantine"
        try:
            quarantine.mkdir(parents=True, exist_ok=True)
            self._add("quarantine_dir", "Upload quarantine directory", PASS, str(quarantine))
        except Exception as exc:  # noqa: BLE001
            self._add("quarantine_dir", "Upload quarantine directory", FAIL, str(exc)[:200])

        policy = getattr(settings, "UPLOAD_SCAN_ENFORCEMENT", "enforce")
        self._add(
            "upload_scan_policy",
            "Upload scanning fails closed",
            self._grade(policy == "enforce", self.strict, warn_only=True),
            f"policy={policy}",
        )

    def _check_celery(self) -> None:
        if bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)):
            self._add(
                "celery_broker",
                "Celery broker reachable",
                NOT_VERIFIED,
                "eager mode configured; broker not exercised",
            )
            return
        try:
            from config.celery import app

            conn = app.connection_for_read()
            try:
                conn.ensure_connection(max_retries=1, timeout=3)
                self._add("celery_broker", "Celery broker reachable", PASS, conn.as_uri())
            finally:
                conn.release()
        except Exception as exc:  # noqa: BLE001
            self._add("celery_broker", "Celery broker reachable", WARN, str(exc)[:200])

    # -- reporting ---------------------------------------------------------
    def _report(self, json_path: str) -> None:
        self.results.sort(key=lambda r: (_ORDER.get(r.status, 9), r.key))
        width = max(len(r.title) for r in self.results) + 2
        self.stdout.write("")
        self.stdout.write("Deployment verification report")
        self.stdout.write("=" * 60)
        for result in self.results:
            style = {
                PASS: self.style.SUCCESS,
                FAIL: self.style.ERROR,
                WARN: self.style.WARNING,
                NOT_VERIFIED: self.style.NOTICE,
            }.get(result.status, str)
            line = f"[{result.status:^12}] {result.title:<{width}} {result.detail}"
            self.stdout.write(style(line))

        counts = {status: sum(1 for r in self.results if r.status == status) for status in _ORDER}
        summary = (
            f"{counts[PASS]} passed, {counts[FAIL]} failed, "
            f"{counts[WARN]} warnings, {counts[NOT_VERIFIED]} not verified"
        )
        self.stdout.write("=" * 60)
        self.stdout.write(summary)

        if json_path:
            payload = {
                "summary": counts,
                "checks": [asdict(r) for r in self.results],
            }
            with open(json_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            self.stdout.write(f"Wrote {json_path}")

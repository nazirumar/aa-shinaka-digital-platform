"""Phase 15 — Docker Compose deployment invariants.

These tests assert the *deployment* shape rather than application behaviour:
that PostgreSQL and Redis can never be reached from the internet, that exactly
one container performs migrations, that only one Celery beat runs, that every
service has a restart policy/health check/resource limits, that uploads survive
container recreation, and that no secret or live payment key can leak into an
image or an env file.

The Compose assertions shell out to `docker compose config`, which is a purely
client-side operation (no daemon, no network, no build). They are skipped when
the Docker CLI is unavailable so the suite still runs on a bare machine.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "deploy"
COMPOSE = DEPLOY / "docker-compose.yml"
STAGING_OVERRIDE = DEPLOY / "docker-compose.staging.yml"
ENV_PRODUCTION = DEPLOY / ".env.production.example"
ENV_STAGING = DEPLOY / ".env.staging.example"
NGINX_TLS = DEPLOY / "nginx" / "aa-shinaka.conf"
NGINX_BOOTSTRAP = DEPLOY / "nginx" / "bootstrap.conf"
DOCKERIGNORE = REPO / ".dockerignore"

DOCKER = shutil.which("docker")
requires_docker = pytest.mark.skipif(
    DOCKER is None, reason="Docker CLI not available (client-side compose config only)"
)

# Services that run the application image and therefore inherit the entrypoint,
# which migrates by default unless told otherwise.
APP_SERVICES = ("migrate", "web", "worker", "beat")


def _compose_config(overlay: Path | None = None, env_file: Path | None = None) -> dict:
    """Render the Compose model to a dict, without needing a Docker daemon.

    The env file is selected through APP_ENV_FILE (which the base file
    interpolates) rather than by requiring a real `deploy/.env.production`:
    the repository must be validatable without any secret file existing.
    """
    assert DOCKER is not None
    service_env = env_file or ENV_PRODUCTION
    # APP_ENV_FILE is resolved relative to the compose file's directory, but an
    # absolute path works too and keeps this self-contained.
    env = {**os.environ, "APP_ENV_FILE": str(service_env)}
    cmd = [
        DOCKER,
        "compose",
        "--env-file",
        str(service_env),
        "-f",
        str(COMPOSE),
    ]
    if overlay is not None:
        cmd += ["-f", str(overlay)]
    cmd += ["config", "--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
    assert proc.returncode == 0, f"compose config failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def prod_config() -> dict:
    return _compose_config()


@pytest.fixture(scope="module")
def staging_config() -> dict:
    return _compose_config(STAGING_OVERRIDE, ENV_STAGING)


def _networks(service: dict) -> set[str]:
    value = service.get("networks") or {}
    return set(value.keys() if isinstance(value, dict) else value)


def _limits(service: dict) -> dict | None:
    return (service.get("deploy") or {}).get("resources", {}).get("limits")


# ---------------------------------------------------------------------------
# Compose model is valid
# ---------------------------------------------------------------------------


@requires_docker
def test_production_compose_config_is_valid(prod_config):
    assert prod_config["services"], "no services rendered"


@requires_docker
def test_staging_compose_config_is_valid(staging_config):
    # Staging must stay isolated: distinct project name and non-default ports.
    assert staging_config["name"] == "aa-shinaka-staging"
    published = {
        str(p.get("published")) for p in staging_config["services"]["nginx"].get("ports", [])
    }
    assert published == {"8080", "8443"}, published


# ---------------------------------------------------------------------------
# Environment-file isolation between staging and production
#
# Compose APPENDS `env_file` lists when an override file is merged, so a staging
# overlay that adds `env_file: [.env.staging]` still loads the production file
# (and hard-fails if it does not exist). The stack therefore selects its env
# file by interpolation instead. These tests pin that down.
# ---------------------------------------------------------------------------


def test_base_compose_selects_the_env_file_by_interpolation():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "${APP_ENV_FILE:-.env.production}" in text


def test_staging_overlay_declares_no_env_file():
    # Check the actual YAML key, not the word (the file explains in comments why
    # it deliberately has no `env_file:`).
    keys = [
        line.strip()
        for line in STAGING_OVERRIDE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert not any(line.startswith("env_file:") for line in keys), (
        "the staging overlay must not declare `env_file`: Compose appends those "
        "entries instead of replacing them, which would make staging load the "
        "production environment file"
    )


def test_env_templates_declare_their_own_env_file():
    assert _env(ENV_PRODUCTION)["APP_ENV_FILE"] == ".env.production"
    assert _env(ENV_STAGING)["APP_ENV_FILE"] == ".env.staging"


@requires_docker
def test_app_env_file_drives_the_container_environment(tmp_path):
    """End-to-end proof that staging loads ONLY its own env file.

    A canary variable is appended to a copy of the staging template and the
    stack is rendered with APP_ENV_FILE pointing at it. If the overlay ever
    re-introduced `env_file: .env.production`, Compose would append it, try to
    read a non-existent production file and fail the render.
    """
    canary = tmp_path / ".env.staging.canary"
    canary.write_text(
        ENV_STAGING.read_text(encoding="utf-8") + "\nAA_PHASE15_CANARY=staging-only\n",
        encoding="utf-8",
    )
    config = _compose_config(STAGING_OVERRIDE, canary)
    for name in APP_SERVICES:
        environment = config["services"][name].get("environment") or {}
        assert environment.get("AA_PHASE15_CANARY") == "staging-only", name


# ---------------------------------------------------------------------------
# Network isolation — nothing but nginx is reachable from outside
# ---------------------------------------------------------------------------


@requires_docker
def test_only_nginx_publishes_host_ports(prod_config):
    for name, service in prod_config["services"].items():
        ports = service.get("ports") or []
        if name == "nginx":
            assert {str(p.get("published")) for p in ports} == {"80", "443"}
        else:
            assert not ports, f"{name} publishes host ports: {ports}"


@requires_docker
def test_postgres_and_redis_have_no_published_ports(prod_config):
    for name in ("db", "redis"):
        assert not prod_config["services"][name].get("ports"), f"{name} is published"


@requires_docker
def test_backend_network_is_internal(prod_config):
    assert prod_config["networks"]["backend"]["internal"] is True
    assert "internal" not in prod_config["networks"]["frontend"]


@requires_docker
def test_db_and_redis_live_only_on_the_internal_network(prod_config):
    for name in ("db", "redis"):
        assert _networks(prod_config["services"][name]) == {"backend"}, name


# ---------------------------------------------------------------------------
# Migrations happen exactly once, in one container
# ---------------------------------------------------------------------------


@requires_docker
def test_no_service_self_migrates_on_boot(prod_config):
    """The entrypoint migrates by default; every app service must opt out.

    Migrations are owned by the one-shot `migrate` service so that scaling the
    web tier (or restarting worker/beat) can never start two migrations at once.
    """
    for name in APP_SERVICES:
        environment = prod_config["services"][name].get("environment") or {}
        assert environment.get("RUN_MIGRATIONS") == "false", (
            f"{name} would migrate on boot (RUN_MIGRATIONS={environment.get('RUN_MIGRATIONS')!r})"
        )


@requires_docker
def test_migrate_service_is_the_release_step(prod_config):
    migrate = prod_config["services"]["migrate"]
    command = " ".join(migrate["command"])
    assert "migrate" in command
    assert migrate.get("restart") == "no"
    environment = migrate.get("environment") or {}
    # Static is collected once, here, into the shared volume.
    assert environment.get("RUN_COLLECTSTATIC") == "true"


@requires_docker
def test_app_services_wait_for_migrations(prod_config):
    for name in ("web", "worker", "beat"):
        depends = prod_config["services"][name].get("depends_on")
        assert depends["migrate"]["condition"] == "service_completed_successfully", name


# ---------------------------------------------------------------------------
# Celery beat runs exactly once
# ---------------------------------------------------------------------------


@requires_docker
def test_only_one_celery_beat_service_exists(prod_config):
    beat_services = [
        name
        for name, service in prod_config["services"].items()
        if " ".join(service.get("command") or []).find("beat") != -1
    ]
    assert beat_services == ["beat"], beat_services


# ---------------------------------------------------------------------------
# Resilience: restart policies, health checks, limits, log rotation, volumes
# ---------------------------------------------------------------------------


@requires_docker
@pytest.mark.parametrize(
    "name",
    ["db", "redis", "migrate", "web", "worker", "beat", "nginx"],
)
def test_service_has_restart_policy_and_log_rotation(prod_config, name):
    service = prod_config["services"][name]
    assert service.get("restart") in {"unless-stopped", "no"}, name
    assert (service.get("logging") or {}).get("driver") == "json-file", name


@requires_docker
@pytest.mark.parametrize("name", ["db", "redis", "web", "nginx"])
def test_long_running_services_have_health_checks(prod_config, name):
    assert prod_config["services"][name].get("healthcheck"), name


@requires_docker
@pytest.mark.parametrize("name", ["db", "redis", "migrate", "web", "worker", "beat", "nginx"])
def test_service_has_resource_limits(prod_config, name):
    limits = _limits(prod_config["services"][name])
    assert limits, f"{name} has no resource limits"
    assert limits.get("memory"), name
    assert limits.get("cpus"), name


@requires_docker
def test_database_and_media_use_persistent_named_volumes(prod_config):
    """Uploads and data must outlive `docker compose down`."""
    named = {v["source"] for v in prod_config["services"]["db"]["volumes"] if v["type"] == "volume"}
    assert "pgdata" in named
    for name in ("web", "worker", "migrate"):
        sources = {
            v["source"]
            for v in prod_config["services"][name].get("volumes", [])
            if v["type"] == "volume"
        }
        assert "media" in sources or name == "migrate", name
    # nginx serves media read-only; it must never be able to write uploads.
    nginx_writes = [
        v
        for v in prod_config["services"]["nginx"]["volumes"]
        if v.get("source") == "media" and v.get("read_only") is not True
    ]
    assert not nginx_writes


@requires_docker
def test_app_containers_drop_privilege_escalation(prod_config):
    for name in ("migrate", "web", "worker", "beat"):
        assert "no-new-privileges:true" in prod_config["services"][name].get("security_opt", []), (
            name
        )


# ---------------------------------------------------------------------------
# Environment template — secrets, payment safety, internal consistency
# ---------------------------------------------------------------------------


def _env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_production_env_template_defines_every_compose_secret():
    values = _env(ENV_PRODUCTION)
    # compose interpolates these with :? so a missing value fails the render.
    for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "DJANGO_SECRET_KEY"):
        assert key in values, f"{key} missing from the production env template"


def test_production_env_template_keeps_paystack_out_of_live_mode():
    values = _env(ENV_PRODUCTION)
    assert values["PAYSTACK_LIVE_MODE"].lower() == "false"
    assert values["PAYSTACK_ENABLED"].lower() == "false"
    assert not values["PAYSTACK_SECRET_KEY"].startswith("sk_live_")
    assert not values["PAYSTACK_PUBLIC_KEY"].startswith("pk_live_")


def test_production_env_template_disables_database_ssl_for_the_internal_network():
    """PostgreSQL runs on the internal Docker network with no TLS listener.

    prod.py defaults DB_SSLMODE_REQUIRE to True (correct for a managed/remote
    database). Leaving that default here would make psycopg refuse to connect to
    the bundled postgres:16-alpine container, so the template pins it to False.
    """
    assert _env(ENV_PRODUCTION)["DB_SSLMODE_REQUIRE"].lower() == "false"
    assert _env(ENV_STAGING)["DB_SSLMODE_REQUIRE"].lower() == "false"


def test_production_env_template_passwords_are_internally_consistent():
    values = _env(ENV_PRODUCTION)
    url = values["DATABASE_URL"]
    userinfo = url.split("://", 1)[1].split("@", 1)[0]
    url_password = userinfo.split(":", 1)[1]
    assert url_password == values["POSTGRES_PASSWORD"], (
        "DATABASE_URL password must match POSTGRES_PASSWORD exactly"
    )
    for key in ("CACHE_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        assert f":{values['REDIS_PASSWORD']}@" in values[key], key


def test_production_env_template_is_still_rejected_as_unfilled():
    """The shipped template must never be usable as-is (placeholders present)."""
    text = ENV_PRODUCTION.read_text(encoding="utf-8")
    assert "EXAMPLE_DOMAIN" in text
    assert "CHANGE_ME" in text


def test_redis_passwords_are_url_safe():
    for path in (ENV_PRODUCTION, ENV_STAGING):
        password = _env(path)["REDIS_PASSWORD"]
        assert password.replace("_", "").isalnum(), f"URL-unsafe REDIS_PASSWORD in {path.name}"


# ---------------------------------------------------------------------------
# nginx — private documents are never served by the web server
# ---------------------------------------------------------------------------


def test_nginx_defaults_to_deny_for_all_media():
    text = NGINX_TLS.read_text(encoding="utf-8")
    deny_block = "location /media/ {\n        return 404;\n    }"
    assert deny_block in text, "nginx must default-deny /media/"


def test_nginx_only_serves_public_media_prefixes():
    text = NGINX_TLS.read_text(encoding="utf-8")
    aliases = [
        line.split("alias", 1)[1].strip().rstrip(";")
        for line in text.splitlines()
        if "alias /srv/media/" in line
    ]
    assert aliases, "expected public media aliases"
    for alias in aliases:
        # Only catalogue/CMS/training imagery may be public. Invoices, payment
        # evidence, export documents, support attachments and analytic exports
        # must never be aliased here.
        assert alias.startswith(
            ("/srv/media/catalog/", "/srv/media/cms/", "/srv/media/training/")
        ), f"unexpected public media alias: {alias}"
    forbidden = ("invoice", "payment", "export", "document", "attachment", "order")
    for alias in aliases:
        assert not any(word in alias.lower() for word in forbidden), alias


def test_nginx_rate_limits_authentication_surfaces():
    text = NGINX_TLS.read_text(encoding="utf-8")
    assert "limit_req_zone" in text
    for path in ("/accounts/login/", "/accounts/password-reset/", "/accounts/register/"):
        assert f"location ^~ {path}" in text, path
        assert "limit_req zone=aa_auth" in text


def test_nginx_hides_server_tokens_and_sends_security_headers():
    text = NGINX_TLS.read_text(encoding="utf-8")
    assert "server_tokens off;" in text
    for header in (
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
    ):
        assert header in text, header


def test_nginx_bootstrap_config_does_not_terminate_tls():
    """The bootstrap config must work before any certificate exists."""
    text = NGINX_BOOTSTRAP.read_text(encoding="utf-8")
    assert "listen 443" not in text
    assert "acme-challenge" in text


def test_nginx_site_config_is_rendered_not_committed_with_a_fake_domain():
    """No fabricated DNS: the active site config is generated per deployment."""
    rendered = DEPLOY / "nginx" / "conf.d" / ".gitignore"
    assert rendered.exists(), "rendered nginx configs must be gitignored"
    ignore = rendered.read_text(encoding="utf-8")
    assert "*" in ignore


# ---------------------------------------------------------------------------
# Image build hygiene
# ---------------------------------------------------------------------------


def test_dockerignore_keeps_secrets_and_host_state_out_of_the_image():
    text = DOCKERIGNORE.read_text(encoding="utf-8")
    active = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for required in (
        ".env",
        "deploy/.env.production",
        "deploy/.env.staging",
        "media/",
        "staticfiles/",
        "deploy/nginx/certs/",
        ".git",
        "node_modules/",
        ".venv/",
        "tests/",
    ):
        assert required in active, f".dockerignore must exclude {required}"


def test_dockerfile_builds_from_the_lockfile_and_runs_unprivileged():
    text = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    assert "uv sync --frozen --no-dev --no-install-project" in text
    assert "COPY pyproject.toml uv.lock ./" in text
    assert "USER app" in text
    assert "npm ci" in text and "npm run build:css" in text

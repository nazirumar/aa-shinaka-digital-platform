"""Guard the default environment values used by settings and tooling.

``django-environ`` validates cache URLs at import time and rejects unknown
schemes with ``ImproperlyConfigured``. A bad default (``locmem://`` instead of
``locmemcache://``) therefore crashes the whole app whenever ``CACHE_URL`` is
not set — a fresh clone, a container started without that variable, or CI.

These tests fail fast on that class of mistake by checking the URLs shipped as
defaults in ``config/settings/base.py``, ``.env.example`` and the CI workflow.
"""

from __future__ import annotations

import re
from pathlib import Path

import environ

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_SETTINGS = REPO_ROOT / "config" / "settings" / "base.py"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

_ENV = environ.Env()


def _assert_valid_cache_url(url: str) -> None:
    """django-environ must be able to resolve ``url`` to a cache backend."""
    config = _ENV.cache_url_config(url)
    assert config.get("BACKEND"), f"{url!r} did not resolve to a cache backend"


def test_base_settings_cache_default_is_a_valid_scheme():
    text = BASE_SETTINGS.read_text(encoding="utf-8")
    match = re.search(r'env\.cache\(\s*"CACHE_URL",\s*default="([^"]+)"\s*\)', text)
    assert match, "CACHE_URL default not found in config/settings/base.py"
    _assert_valid_cache_url(match.group(1))


def test_env_example_cache_url_is_valid():
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
    assert "CACHE_URL" in values, "CACHE_URL missing from .env.example"
    _assert_valid_cache_url(values["CACHE_URL"])


def test_ci_workflow_cache_urls_are_valid():
    urls = re.findall(r"CACHE_URL:\s*(\S+)", CI_WORKFLOW.read_text(encoding="utf-8"))
    assert urls, "CACHE_URL not found in the CI workflow"
    for url in urls:
        _assert_valid_cache_url(url)

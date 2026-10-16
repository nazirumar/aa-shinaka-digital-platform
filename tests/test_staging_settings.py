"""Phase 14 — staging configuration guards.

These tests exercise the pure guard functions in ``config.settings._guards``
which ``config.settings.staging`` calls at import time. Importing the settings
module itself would run the full production validation and require a populated
environment, so the guards are tested directly — the production-specific rules
are already covered by ``tests/test_production_security.py``.
"""

from __future__ import annotations

import pytest

from config.settings._guards import (
    DeploymentGuardError,
    assert_paystack_live_requires_live_mode,
    assert_staging_paystack_is_test_only,
    is_live_paystack_key,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("sk_live_abcdef123456", True),
        ("  sk_live_padded  ", True),
        ("sk_test_abcdef123456", False),
        ("pk_live_abcdef", False),
        ("", False),
        (None, False),
    ],
)
def test_is_live_paystack_key(key, expected):
    assert is_live_paystack_key(key) is expected


def test_staging_accepts_test_keys():
    # Must not raise.
    assert_staging_paystack_is_test_only(live_mode=False, secret_key="sk_test_abc123")


def test_staging_accepts_blank_key():
    assert_staging_paystack_is_test_only(live_mode=False, secret_key="")


def test_staging_rejects_live_mode():
    with pytest.raises(DeploymentGuardError):
        assert_staging_paystack_is_test_only(live_mode=True, secret_key="sk_test_abc")


def test_staging_rejects_live_key():
    with pytest.raises(DeploymentGuardError):
        assert_staging_paystack_is_test_only(live_mode=False, secret_key="sk_live_abc")


def test_production_guard_blocks_live_key_without_live_mode():
    with pytest.raises(DeploymentGuardError):
        assert_paystack_live_requires_live_mode(
            enabled=True, live_mode=False, secret_key="sk_live_abc"
        )


def test_production_guard_allows_live_key_with_live_mode():
    # Must not raise once live mode has been explicitly approved.
    assert_paystack_live_requires_live_mode(enabled=True, live_mode=True, secret_key="sk_live_abc")


def test_production_guard_allows_test_key():
    assert_paystack_live_requires_live_mode(enabled=True, live_mode=False, secret_key="sk_test_abc")

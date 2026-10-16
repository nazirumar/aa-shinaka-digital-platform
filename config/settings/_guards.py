"""Deployment-time safety guards.

Pure functions with **no Django imports** so they can be unit-tested directly and
reused by settings modules (import-time enforcement) and by the
``verify_deployment`` management command (runtime reporting).

Keeping the logic here avoids importing a settings module just to test a rule —
importing ``config.settings.staging`` runs the whole production settings
validation and would require a fully-populated environment.
"""

from __future__ import annotations


class DeploymentGuardError(RuntimeError):
    """Raised when a deployment configuration is unsafe."""


def is_live_paystack_key(secret_key: str | None) -> bool:
    """Return ``True`` when ``secret_key`` looks like a Paystack live key."""
    return bool(secret_key) and secret_key.strip().startswith("sk_live_")


def assert_staging_paystack_is_test_only(
    *,
    live_mode: bool,
    secret_key: str | None,
) -> None:
    """Refuse any staging configuration that could move real money.

    Staging exists to verify the platform against the provider's **test** API.
    A live key or an enabled live mode on staging is a launch-class mistake, so
    the settings module fails fast instead of silently accepting it.
    """
    if live_mode:
        raise DeploymentGuardError(
            "PAYSTACK_LIVE_MODE must be False on staging: staging must never process live payments."
        )
    if is_live_paystack_key(secret_key):
        raise DeploymentGuardError(
            "A live Paystack secret key (sk_live_…) must never be configured on "
            "staging. Use test keys only."
        )


def assert_paystack_live_requires_live_mode(
    *,
    enabled: bool,
    live_mode: bool,
    secret_key: str | None,
) -> None:
    """In production, a live key is only legal once live mode is explicitly on.

    Mirrors the runtime fail-closed guard in ``apps.orders.paystack`` for the
    deployment verifier: a live key with live mode off means payments will be
    refused at runtime (a misconfiguration worth surfacing).
    """
    if is_live_paystack_key(secret_key) and not live_mode:
        raise DeploymentGuardError(
            "A live Paystack secret key (sk_live_…) is configured but "
            "PAYSTACK_LIVE_MODE is False — payments would fail closed. Either "
            "remove the live key or enable live mode after launch approval."
        )

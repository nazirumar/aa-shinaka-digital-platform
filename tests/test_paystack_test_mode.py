"""Phase 13, Step 7 — Paystack stays test-mode only until launch is approved.

The platform must never move real money by accident: a live secret key in the
environment is refused (fail closed) unless ``PAYSTACK_LIVE_MODE`` is explicitly
switched on. No network calls are made in these tests.
"""

from __future__ import annotations

from django.test import override_settings

from apps.orders import paystack

LIVE_SETTINGS = {
    "PAYSTACK_ENABLED": True,
    "PAYSTACK_SECRET_KEY": "sk_live_abcdef1234567890",
    "PAYSTACK_LIVE_MODE": False,
    "PAYSTACK_WEBHOOK_SECRET": "",
    "PAYSTACK_CURRENCY": "NGN",
}

TEST_SETTINGS = {
    "PAYSTACK_ENABLED": True,
    "PAYSTACK_SECRET_KEY": "sk_test_abcdef1234567890",
    "PAYSTACK_LIVE_MODE": False,
    "PAYSTACK_WEBHOOK_SECRET": "",
    "PAYSTACK_CURRENCY": "NGN",
}


@override_settings(**TEST_SETTINGS)
def test_test_key_is_enabled():
    assert paystack.is_enabled() is True
    assert paystack.live_key_blocked() is False


@override_settings(**LIVE_SETTINGS)
def test_live_key_is_blocked_until_launch_approved():
    assert paystack.live_key_blocked() is True
    assert paystack.is_enabled() is False


@override_settings(**{**LIVE_SETTINGS, "PAYSTACK_LIVE_MODE": True})
def test_live_key_enabled_only_when_live_mode_switched_on():
    assert paystack.live_key_blocked() is False
    assert paystack.is_enabled() is True


@override_settings(**LIVE_SETTINGS)
def test_request_refuses_live_key_before_any_network_call():
    try:
        paystack._request("GET", "/transaction/verify/anything")
    except paystack.PaystackError as exc:
        assert exc.code == "live_mode_disabled"
    else:  # pragma: no cover - must always raise
        raise AssertionError("live-key request should have been refused")


@override_settings(PAYSTACK_ENABLED=False, PAYSTACK_SECRET_KEY="")
def test_disabled_when_unconfigured():
    assert paystack.is_enabled() is False
    assert paystack.live_key_blocked() is False


@override_settings(PAYSTACK_ENABLED=True, PAYSTACK_SECRET_KEY="")
def test_disabled_without_a_secret_key():
    assert paystack.is_enabled() is False

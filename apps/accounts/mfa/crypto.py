"""Dependency-free encryption helpers for MFA secrets.

Uses HMAC-SHA256 to derive a keystream from a key and nonce, then XORs
to encrypt/decrypt. Authenticated via HMAC-SHA256 over ciphertext.
"""

from __future__ import annotations

import base64
import hmac
import os
from hashlib import sha256

from django.conf import settings


def _derive_key() -> bytes:
    key_material = (getattr(settings, "MFA_SECRET_KEY", None) or settings.SECRET_KEY).encode(
        "utf-8"
    )
    # Derive a stable encryption key
    return hmac.new(key_material, b"mfa:secret", sha256).digest()


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext and return a base64url-like string (HMAC+nonce+ciphertext)."""
    if not plaintext:
        return ""
    key = _derive_key()
    nonce = os.urandom(16)
    pt = plaintext.encode("utf-8")
    # Simple XOR keystream: HMAC(key, nonce || counter)
    ct = bytearray(len(pt))
    for i in range(len(pt)):
        ctr = i.to_bytes(8, "little")
        ks = hmac.new(key, nonce + ctr, sha256).digest()[0]
        ct[i] = pt[i] ^ ks
    mac = hmac.new(key, b"enc:" + nonce + bytes(ct), sha256).digest()
    payload = mac + nonce + bytes(ct)
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decrypt(token: str) -> str:
    """Decrypt token from encrypt() and return plaintext; raises if tampered."""
    if not token:
        return ""
    key = _derive_key()
    raw = base64.urlsafe_b64decode(token + "=" * ((4 - len(token) % 4) % 4))
    if len(raw) < 32 + 16:
        raise ValueError("Invalid MFA secret token")
    mac = raw[:32]
    nonce = raw[32:48]
    ct = raw[48:]
    expected_mac = hmac.new(key, b"enc:" + nonce + ct, sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("MFA secret token tampered")
    pt = bytearray(len(ct))
    for i in range(len(ct)):
        ctr = i.to_bytes(8, "little")
        ks = hmac.new(key, nonce + ctr, sha256).digest()[0]
        pt[i] = ct[i] ^ ks
    return bytes(pt).decode("utf-8")

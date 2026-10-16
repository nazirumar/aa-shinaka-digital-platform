"""TOTP utilities (dependency-free)."""

from __future__ import annotations

import hashlib
import hmac
import time


def base32_decode(s: str) -> bytes:
    s = s.strip().upper().replace(" ", "")
    missing = (-len(s)) % 8
    if missing:
        s += "=" * missing
    # base32 alphabet
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    b = 0
    n = 0
    out = bytearray()
    for c in s:
        if c in alphabet:
            b = (b << 5) | alphabet.index(c)
            n += 5
            if n >= 8:
                n -= 8
                out.append((b >> n) & 0xFF)
        elif c == "=":
            break
    return bytes(out)


def totp_code(secret_base32: str, *, step: int = 30, digits: int = 6, offset: int = 0) -> str:
    if not secret_base32:
        return "000000"
    key = base32_decode(secret_base32)
    counter = int((time.time() + offset) // step)
    msg = counter.to_bytes(8, "big")
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[19] & 0x0F
    num = (int.from_bytes(h[o : o + 4], "big") & 0x7FFFFFFF) % 10**digits
    return format(num, f"0{digits}d")


def verify_totp(
    secret_base32: str,
    code: str,
    *,
    step: int = 30,
    digits: int = 6,
    window: int = 1,
) -> bool:
    if not code or len(code) != digits:
        return False
    for drift in range(-window, window + 1):
        expected = totp_code(secret_base32, step=step, digits=digits, offset=drift * step)
        if hmac.compare_digest(expected, code):
            return True
    return False


def generate_secret_base32() -> str:
    # 20 bytes = 160 bits for SHA1 TOTP
    import os

    raw = os.urandom(20)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    b = 0
    n = 0
    out = []
    for byte in raw:
        b = (b << 8) | byte
        n += 8
        while n >= 5:
            n -= 5
            out.append(alphabet[(b >> n) & 0x1F])
    return "".join(out)

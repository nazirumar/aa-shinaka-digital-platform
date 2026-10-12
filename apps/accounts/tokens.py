"""Signed, time-limited, single-use email verification tokens.

The token embeds the user id and a per-user nonce. The nonce is rotated on
successful verification, so a token cannot be replayed. Expiry is enforced by
``django.core.signing`` using ``settings.EMAIL_VERIFICATION_TIMEOUT``.
"""

from __future__ import annotations

from django.conf import settings
from django.core import signing

SALT = "aa-shinaka.email-verification"


class EmailTokenError(Exception):
    """Base class for email token problems."""


class EmailTokenExpired(EmailTokenError):
    """The token was well-formed but has expired."""


class EmailTokenInvalid(EmailTokenError):
    """The token is malformed, tampered with, or otherwise unusable."""


def make_email_token(user) -> str:
    payload = {"uid": str(user.pk), "nonce": str(user.email_verification_nonce)}
    return signing.dumps(payload, salt=SALT, compress=True)


def read_email_token(token: str, *, max_age: int | None = None) -> dict:
    """Decode and validate a token, raising on expiry or tampering."""
    age = settings.EMAIL_VERIFICATION_TIMEOUT if max_age is None else max_age
    try:
        return signing.loads(token, salt=SALT, max_age=age)
    except signing.SignatureExpired as exc:
        raise EmailTokenExpired("The verification link has expired.") from exc
    except signing.BadSignature as exc:
        raise EmailTokenInvalid("The verification link is not valid.") from exc

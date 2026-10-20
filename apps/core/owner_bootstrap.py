"""One-shot creation of the first owner (superuser) account.

Managed hosts without an interactive shell — notably **Render Free**, which has no
Shell tab — make ``manage.py createsuperuser`` awkward. This module and its two
thin entry points (a management command and a token-protected HTTP endpoint)
create the owner account safely:

* **Idempotent.** Re-running never duplicates or overwrites the owner.
* **Self-disabling.** As soon as *any* superuser exists the HTTP endpoint refuses
  to run, so a leaked token cannot mint a second owner after setup.
* **Token-gated.** The endpoint is disabled unless ``BOOTSTRAP_OWNER_TOKEN`` is
  set, and requires an exact constant-time match.

Entry points:

* ``manage.py bootstrap_owner --email ... [--password ...]`` (local / any host
  with a shell);
* ``POST /internal/bootstrap-owner/`` with the ``X-Bootstrap-Token`` header
  (hosts with no shell).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.accounts.roles import sync_user_groups

logger = logging.getLogger(__name__)


class BootstrapError(Exception):
    """Raised when the owner cannot be created (bad input or already present)."""


@dataclass(frozen=True)
class BootstrapResult:
    email: str
    created: bool


def owner_exists() -> bool:
    """True once any superuser exists — the endpoint disables itself then."""
    User = get_user_model()
    return User.objects.filter(is_superuser=True).exists()


@transaction.atomic
def ensure_owner(
    *,
    email: str,
    password: str,
    first_name: str = "Owner",
    last_name: str = "",
) -> BootstrapResult:
    """Create the owner superuser if none exists; otherwise leave things alone.

    Raises :class:`BootstrapError` for missing input or an existing account with
    the same email, so callers can surface a clear, non-secret error message.
    """
    email = (email or "").strip().lower()
    if not email:
        raise BootstrapError("An email address is required.")
    if not password:
        raise BootstrapError("A password is required.")

    User = get_user_model()
    if User.objects.filter(is_superuser=True).exists():
        raise BootstrapError("An owner account already exists; bootstrap is disabled.")

    existing = User.objects.filter(email__iexact=email).first()
    if existing is not None:
        raise BootstrapError("An account with this email already exists.")

    user = User.objects.create_superuser(
        email=email,
        password=password,
        first_name=(first_name or "").strip(),
        last_name=(last_name or "").strip(),
    )
    # Mirror the group membership a role change would produce.
    sync_user_groups(user)
    logger.info("Bootstrapped owner account %s.", email)
    return BootstrapResult(email=email, created=True)

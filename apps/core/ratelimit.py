"""Lightweight cache-backed rate limiting.

Uses Django's cache framework (in-process memory in development, Redis in
production). Deliberately dependency-free — no third-party rate-limit package is
required for Phase 2.
"""

from __future__ import annotations

from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse
from django.template.response import TemplateResponse


def get_client_ip(request) -> str:
    """Best-effort client IP, honouring a single proxy hop."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _bucket_key(scope: str, identifier: str) -> str:
    return f"ratelimit:{scope}:{identifier}"


def hit(scope: str, identifier: str, *, limit: int, window: int) -> bool:
    """Register an attempt and return ``True`` if the limit is now exceeded.

    The counter is created on first call and expires after ``window`` seconds.
    """
    key = _bucket_key(scope, identifier)
    if cache.add(key, 1, timeout=window):
        return 1 > limit
    try:
        count = cache.incr(key)
    except ValueError:
        # Key expired between add() and incr(); restart the window.
        cache.set(key, 1, timeout=window)
        count = 1
    return count > limit


def reset(scope: str, identifier: str) -> None:
    cache.delete(_bucket_key(scope, identifier))


def is_rate_limited(scope: str, identifier: str, *, limit: int, window: int) -> bool:
    """Check the current count without incrementing."""
    return (cache.get(_bucket_key(scope, identifier)) or 0) >= limit


def rate_limit_response(request, *, message: str | None = None) -> HttpResponse:
    """Render a 429 response, or a tiny plain-text fallback."""
    if request.headers.get("HX-Request"):
        return HttpResponse(message or "Too many requests.", status=429)
    try:
        response = TemplateResponse(
            request,
            "errors/429.html",
            {"message": message or "Too many requests. Please try again later."},
            status=429,
        )
        return response
    except Exception:  # noqa: BLE001 - template may be unavailable in tests
        return HttpResponse(message or "Too many requests.", status=429)


def rate_limit(*, scope: str, limit: int, window: int, by_ip: bool = True, by_user: bool = False):
    """View decorator that returns 429 when the limit is exceeded.

    Keyed by client IP and/or authenticated user (falling back to the submitted
    email field when available, so a single account cannot be brute-forced from
    a rotating IP pool).
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            identifiers: list[str] = []
            if by_ip:
                identifiers.append(f"ip:{get_client_ip(request)}")
            if by_user and request.user.is_authenticated:
                identifiers.append(f"user:{request.user.pk}")
            email = request.POST.get("email") if request.method == "POST" else None
            if email:
                identifiers.append(f"email:{email.strip().lower()}")

            for identifier in identifiers:
                if hit(scope, identifier, limit=limit, window=window):
                    return rate_limit_response(request)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "get_client_ip",
    "hit",
    "is_rate_limited",
    "rate_limit",
    "rate_limit_response",
    "reset",
]

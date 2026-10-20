from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import Http404, HttpRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .constants import BusinessDivision

logger = logging.getLogger(__name__)


def home(request: HttpRequest):
    """Public landing page.

    The homepage is CMS-driven: content lists (hero banners, divisions,
    testimonials, posts, product previews) are pulled by ``cms`` template tags
    so this view stays free of cross-app imports. ``divisions`` remains the
    fixed company structure used as a fallback before CMS rows are entered.
    """
    context = {
        "divisions": BusinessDivision.choices,
        "page_title": "AA Shinaka Digital Business Platform",
    }
    return render(request, "home.html", context)


def healthcheck(request: HttpRequest) -> JsonResponse:
    """Liveness/readiness probe that also confirms database connectivity."""
    db_ok = True
    db_error = ""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - surface any driver error
        db_ok = False
        db_error = str(exc)

    status = 200 if db_ok else 503
    return JsonResponse(
        {
            "status": "ok" if db_ok else "error",
            "database": db_ok,
            # Exception text can name hosts/roles; only reveal it while debugging.
            "error": db_error if settings.DEBUG else ("unavailable" if db_error else ""),
        },
        status=status,
    )


@csrf_exempt
@require_POST
def run_scheduled_jobs(request: HttpRequest) -> JsonResponse:
    """Token-protected fallback trigger for the Celery-beat periodic jobs.

    Deployments without a worker/beat (notably Render Free) point an external
    scheduler at this endpoint. It is disabled unless ``SCHEDULED_JOBS_TOKEN``
    is configured, requires an exact token match, and is throttled through the
    cache so a leaked token cannot be used to hammer the database.
    """
    expected = str(getattr(settings, "SCHEDULED_JOBS_TOKEN", "") or "")
    if not expected:
        raise Http404

    provided = request.headers.get("X-Scheduled-Jobs-Token", "")
    if not provided or not secrets.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    ):
        logger.warning("Rejected scheduled-jobs request with an invalid token.")
        return JsonResponse({"detail": "Forbidden."}, status=403)

    interval = int(getattr(settings, "SCHEDULED_JOBS_MIN_INTERVAL", 0) or 0)
    if interval > 0:
        try:
            if not cache.add("scheduled-jobs:lock", "1", timeout=interval):
                return JsonResponse({"detail": "Too soon."}, status=429)
        except Exception:  # noqa: BLE001 - a cache outage must not block the jobs
            logger.warning("Scheduled-jobs throttle unavailable; running without it.")

    from .scheduled_jobs import run_all

    result = run_all()
    return JsonResponse(result, status=207 if result["failed"] else 200)

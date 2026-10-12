from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render

from .constants import BusinessDivision


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
        {"status": "ok" if db_ok else "error", "database": db_ok, "error": db_error},
        status=status,
    )

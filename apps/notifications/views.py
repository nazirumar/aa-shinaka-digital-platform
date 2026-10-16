"""Customer notification-centre views (``/account/notifications/``).

Every view is ownership-scoped: a customer can only ever see or change their own
notifications. Destination links are validated with
:func:`apps.notifications.services.safe_url` before any redirect.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from . import selectors, services
from .models import NotificationCategory

PAGE_SIZE = 20


def _list_context(request: HttpRequest) -> dict:
    category = request.GET.get("category", "")
    unread_only = request.GET.get("unread") == "1"
    queryset = selectors.notifications_for(request.user, category=category, unread_only=unread_only)
    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    return {
        "page_title": "Notifications",
        "page_obj": page_obj,
        "notifications": page_obj.object_list,
        "categories": NotificationCategory.choices,
        "selected_category": category,
        "unread_only": unread_only,
        "unread_count": services.unread_count(request.user),
    }


@login_required
def center(request: HttpRequest) -> HttpResponse:
    context = _list_context(request)
    template = (
        "notifications/_list.html"
        if request.headers.get("HX-Request")
        else ("notifications/center.html")
    )
    return render(request, template, context)


@login_required
def unread_badge(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "notifications/_badge.html",
        {"unread_count": services.unread_count(request.user)},
    )


@login_required
@require_POST
def mark_read(request: HttpRequest, pk) -> HttpResponse:
    notification = selectors.notification_for(request.user, pk)
    if notification is None:
        raise Http404("Notification not found.")
    services.mark_read(notification, user=request.user)
    if request.headers.get("HX-Request"):
        return render(request, "notifications/_list.html", _list_context(request))
    return redirect("notifications:center")


@login_required
@require_POST
def mark_all_read(request: HttpRequest) -> HttpResponse:
    services.mark_all_read(request.user)
    if request.headers.get("HX-Request"):
        return render(request, "notifications/_list.html", _list_context(request))
    return redirect("notifications:center")


@login_required
def open_notification(request: HttpRequest, pk) -> HttpResponse:
    """Mark read and follow the notification's safe link (or the centre)."""
    notification = selectors.notification_for(request.user, pk)
    if notification is None:
        raise Http404("Notification not found.")
    services.mark_read(notification, user=request.user)
    return redirect(services.safe_url(notification.url) or "notifications:center")


@login_required
@require_http_methods(["GET", "POST"])
def preferences(request: HttpRequest) -> HttpResponse:
    """Customer notification settings (channels + category opt-outs)."""
    from .forms import NotificationPreferenceForm

    preference = services.get_preference(request.user)
    if request.method == "POST":
        form = NotificationPreferenceForm(request.POST, preference=preference)
        if form.is_valid():
            services.update_preference(
                request.user,
                in_app_enabled=form.cleaned_data["in_app_enabled"],
                email_enabled=form.cleaned_data["email_enabled"],
                sms_enabled=form.cleaned_data["sms_enabled"],
                whatsapp_enabled=form.cleaned_data["whatsapp_enabled"],
                categories=form.category_values(),
            )
            messages.success(request, "Notification preferences saved.")
            return redirect("notifications:preferences")
    else:
        form = NotificationPreferenceForm(preference=preference)
    return render(
        request,
        "notifications/preferences.html",
        {"page_title": "Notification settings", "form": form, "preference": preference},
    )

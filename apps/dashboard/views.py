"""Staff dashboard views (``/dashboard/...``).

Every view requires authentication and enforces capabilities server-side; the
templates only *hide* navigation that a role cannot use.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.forms import StaffCreateForm, StaffEditForm, StaffRoleForm
from apps.accounts.models import User
from apps.accounts.permissions import (
    can_manage_staff,
    can_manage_target,
    capability_required,
)
from apps.accounts.roles import Capability
from apps.accounts.selectors import account_counts, staff_directory
from apps.accounts.services import assign_role, set_staff_active, update_staff
from apps.core.models import FileScanRecord
from apps.core.upload_security import release_scan

from .selectors import activity_for, audit_search, recent_activity, scan_records


@capability_required(Capability.STAFF_VIEW)
def dashboard_home(request: HttpRequest) -> HttpResponse:
    counts = account_counts()
    return render(
        request,
        "dashboard/home.html",
        {
            "page_title": "Dashboard",
            "active_nav": "home",
            "counts": counts,
            "recent_activity": recent_activity(limit=8),
            "breadcrumbs": [{"label": "Dashboard"}],
        },
    )


@capability_required(Capability.STAFF_VIEW)
def staff_list(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")
    staff = staff_directory(query=query, role=role, status=status)
    page = Paginator(staff, 25).get_page(request.GET.get("page"))

    context = {
        "page_title": "Staff",
        "active_nav": "staff",
        "staff": page,
        "page_obj": page,
        "query": query,
        "selected_role": role,
        "selected_status": status,
        "role_choices": User._meta.get_field("role").choices,
        "can_manage": can_manage_staff(request.user),
        "breadcrumbs": [{"label": "Dashboard", "url": "dashboard:home"}, {"label": "Staff"}],
    }
    if request.headers.get("HX-Request"):
        return render(request, "dashboard/staff/_table.html", context)
    return render(request, "dashboard/staff/list.html", context)


@capability_required(Capability.STAFF_MANAGE)
@require_http_methods(["GET", "POST"])
def staff_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = StaffCreateForm(request.POST, actor=request.user, request=request)
        if form.is_valid():
            try:
                staff = form.save()
            except (PermissionDenied, ValidationError) as exc:
                form.add_error(None, getattr(exc, "message", None) or exc.messages[0])
            else:
                messages.success(request, f"Staff account for {staff.email} created.")
                return redirect("dashboard:staff_detail", pk=staff.pk)
    else:
        form = StaffCreateForm(actor=request.user, request=request)
    return render(
        request,
        "dashboard/staff/form.html",
        {
            "form": form,
            "page_title": "Create staff",
            "active_nav": "staff",
            "breadcrumbs": [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Staff", "url": "dashboard:staff_list"},
                {"label": "Create"},
            ],
        },
    )


@capability_required(Capability.STAFF_VIEW)
def staff_detail(request: HttpRequest, pk) -> HttpResponse:
    staff = get_object_or_404(User, pk=pk, is_staff=True)
    return render(
        request,
        "dashboard/staff/detail.html",
        {
            "staff": staff,
            "page_title": staff.full_name,
            "active_nav": "staff",
            "can_manage": can_manage_target(request.user, staff),
            "role_form": StaffRoleForm(actor=request.user, target=staff),
            "activity": activity_for(staff, limit=15),
            "breadcrumbs": [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Staff", "url": "dashboard:staff_list"},
                {"label": staff.full_name},
            ],
        },
    )


@capability_required(Capability.STAFF_MANAGE)
@require_http_methods(["GET", "POST"])
def staff_edit(request: HttpRequest, pk) -> HttpResponse:
    staff = get_object_or_404(User, pk=pk, is_staff=True)
    if not can_manage_target(request.user, staff):
        raise PermissionDenied("You are not allowed to edit this account.")

    profile_form = StaffEditForm(actor=request.user, target=staff)
    role_form = StaffRoleForm(actor=request.user, target=staff)

    if request.method == "POST":
        form_name = request.POST.get("form_name", "profile")
        if form_name == "role":
            role_form = StaffRoleForm(request.POST, actor=request.user, target=staff)
            if role_form.is_valid():
                try:
                    assign_role(
                        actor=request.user,
                        target=staff,
                        role=role_form.cleaned_data["role"],
                        request=request,
                    )
                except PermissionDenied as exc:
                    role_form.add_error(None, str(exc))
                else:
                    messages.success(request, "Role updated.")
                    return redirect("dashboard:staff_detail", pk=staff.pk)
        else:
            profile_form = StaffEditForm(request.POST, actor=request.user, target=staff)
            if profile_form.is_valid():
                try:
                    update_staff(
                        actor=request.user,
                        target=staff,
                        first_name=profile_form.cleaned_data["first_name"],
                        last_name=profile_form.cleaned_data["last_name"],
                        phone=profile_form.cleaned_data.get("phone", ""),
                        request=request,
                    )
                except PermissionDenied as exc:
                    profile_form.add_error(None, str(exc))
                else:
                    messages.success(request, "Staff details updated.")
                    return redirect("dashboard:staff_detail", pk=staff.pk)

    return render(
        request,
        "dashboard/staff/edit.html",
        {
            "staff": staff,
            "profile_form": profile_form,
            "role_form": role_form,
            "page_title": f"Edit {staff.full_name}",
            "active_nav": "staff",
            "breadcrumbs": [
                {"label": "Dashboard", "url": "dashboard:home"},
                {"label": "Staff", "url": "dashboard:staff_list"},
                {
                    "label": staff.full_name,
                    "href": reverse("dashboard:staff_detail", args=[staff.pk]),
                },
                {"label": "Edit"},
            ],
        },
    )


@capability_required(Capability.STAFF_MANAGE)
@require_POST
def staff_toggle_active(request: HttpRequest, pk) -> HttpResponse:
    staff = get_object_or_404(User, pk=pk, is_staff=True)
    active = request.POST.get("active") == "true"
    try:
        set_staff_active(actor=request.user, target=staff, active=active, request=request)
    except PermissionDenied as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request, "Staff account activated." if active else "Staff account deactivated."
        )
    return redirect("dashboard:staff_detail", pk=staff.pk)


@capability_required(Capability.AUDIT_VIEW)
def audit_log(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    action = request.GET.get("action", "")
    entries = audit_search(query=query, action=action)
    page = Paginator(entries, 50).get_page(request.GET.get("page"))
    context = {
        "entries": page,
        "page_obj": page,
        "query": query,
        "selected_action": action,
        "page_title": "Audit log",
        "active_nav": "audit",
        "breadcrumbs": [{"label": "Dashboard", "url": "dashboard:home"}, {"label": "Audit log"}],
    }
    if request.headers.get("HX-Request"):
        return render(request, "dashboard/audit/_table.html", context)
    return render(request, "dashboard/audit/list.html", context)


@capability_required(Capability.MEDIA_MANAGE)
def upload_scans(request: HttpRequest) -> HttpResponse:
    """Security review of every upload scan: clean, blocked and errored files.

    Reviewers with the media-management capability can release a file that the
    scanner could not clear (see ``upload_scan_release``)."""
    status = request.GET.get("status", "")
    kind = request.GET.get("kind", "")
    records = scan_records(status=status, kind=kind)
    page = Paginator(records, 50).get_page(request.GET.get("page"))
    context = {
        "records": page,
        "page_obj": page,
        "selected_status": status,
        "selected_kind": kind,
        "statuses": FileScanRecord.Status.choices,
        "kinds": (
            FileScanRecord.objects.order_by("kind").values_list("kind", flat=True).distinct()
        ),
        "page_title": "Upload security",
        "active_nav": "upload_scans",
        "breadcrumbs": [
            {"label": "Dashboard", "url": "dashboard:home"},
            {"label": "Upload security"},
        ],
    }
    return render(request, "dashboard/audit/upload_scans.html", context)


@require_POST
@capability_required(Capability.MEDIA_MANAGE)
def upload_scan_release(request: HttpRequest, pk) -> HttpResponse:
    """Authorised release of a quarantined/blocked upload after review."""
    record = get_object_or_404(FileScanRecord, pk=pk)
    try:
        release_scan(record, actor=request.user, request=request, note=request.POST.get("note", ""))
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
    else:
        messages.success(request, "File released. It can now be downloaded.")
    return redirect("dashboard:upload_scans")

"""Staff support dashboard views (``/dashboard/support/``).

Access is capability-gated: ``support.manage`` (support agent) can triage and
reply; ``support.approve`` (support manager) can assign and change priority.
Every sensitive action is recorded via ``record_audit`` in the service layer.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import capability_required
from apps.accounts.roles import Capability

from . import selectors, services
from .forms import SupportAssignForm, SupportStaffReplyForm, SupportStatusForm
from .models import SUPPORT_TRANSITIONS, SupportAttachment, SupportPriority, SupportStatus


def _staff_ticket(reference: str):
    ticket = selectors.ticket_by_reference(reference)
    if ticket is None:
        raise Http404("Ticket not found.")
    return ticket


def _allowed_status_choices(ticket) -> list[tuple[str, str]]:
    return [
        (status, SupportStatus(status).label)
        for status in SUPPORT_TRANSITIONS.get(ticket.status, set())
    ]


@capability_required(Capability.SUPPORT_MANAGE)
def home(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "support/dashboard/home.html",
        {
            "page_title": "Support overview",
            "metrics": selectors.support_metrics(),
            "recent": selectors.staff_tickets()[:10],
            "nav_active": "support",
        },
    )


@capability_required(Capability.SUPPORT_MANAGE)
def ticket_list(request: HttpRequest) -> HttpResponse:
    filters = {
        "status": request.GET.get("status", ""),
        "priority": request.GET.get("priority", ""),
        "category": request.GET.get("category", ""),
        "assignee": request.GET.get("assignee", ""),
        "query": request.GET.get("q", ""),
    }
    queryset = selectors.staff_tickets(**filters)
    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    context = {
        "page_title": "Support tickets",
        "page_obj": page_obj,
        "tickets": page_obj.object_list,
        "filters": filters,
        "statuses": SupportStatus.choices,
        "priorities": SupportPriority.choices,
        "categories": selectors.support_metrics()["categories"],
        "nav_active": "support",
    }
    template = (
        "support/dashboard/_ticket_table.html"
        if request.headers.get("HX-Request")
        else "support/dashboard/ticket_list.html"
    )
    return render(request, template, context)


@capability_required(Capability.SUPPORT_MANAGE)
def ticket_detail(request: HttpRequest, reference: str) -> HttpResponse:
    ticket = _staff_ticket(reference)
    return render(
        request,
        "support/dashboard/ticket_detail.html",
        {
            "page_title": f"Ticket {ticket.reference}",
            "ticket": ticket,
            "ticket_messages": selectors.messages_for(ticket, include_internal=True),
            "reply_form": SupportStaffReplyForm(),
            "assign_form": SupportAssignForm(initial={"assignee": ticket.assigned_to_id}),
            "status_form": SupportStatusForm(allowed=_allowed_status_choices(ticket)),
            "nav_active": "support",
        },
    )


@capability_required(Capability.SUPPORT_MANAGE)
@require_POST
def ticket_reply(request: HttpRequest, reference: str) -> HttpResponse:
    ticket = _staff_ticket(reference)
    form = SupportStaffReplyForm(request.POST)
    if form.is_valid():
        try:
            services.add_staff_message(
                ticket,
                sender=request.user,
                message=form.cleaned_data["message"],
                is_internal=form.cleaned_data.get("is_internal", False),
                files=request.FILES.getlist("attachments"),
                request=request,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Reply added.")
    return redirect("support_dashboard:ticket_detail", reference=ticket.reference)


@capability_required(Capability.SUPPORT_APPROVE)
@require_POST
def ticket_assign(request: HttpRequest, reference: str) -> HttpResponse:
    ticket = _staff_ticket(reference)
    form = SupportAssignForm(request.POST)
    if form.is_valid():
        services.assign_ticket(
            ticket,
            assignee=form.cleaned_data["assignee"],
            actor=request.user,
            request=request,
        )
        messages.success(request, "Ticket assignment updated.")
    return redirect("support_dashboard:ticket_detail", reference=ticket.reference)


@capability_required(Capability.SUPPORT_APPROVE)
@require_POST
def ticket_priority(request: HttpRequest, reference: str) -> HttpResponse:
    ticket = _staff_ticket(reference)
    priority = request.POST.get("priority", "")
    if priority in SupportPriority.values:
        services.change_priority(ticket, priority=priority, actor=request.user, request=request)
        messages.success(request, "Priority updated.")
    return redirect("support_dashboard:ticket_detail", reference=ticket.reference)


@capability_required(Capability.SUPPORT_MANAGE)
@require_POST
def ticket_status(request: HttpRequest, reference: str) -> HttpResponse:
    ticket = _staff_ticket(reference)
    form = SupportStatusForm(request.POST, allowed=_allowed_status_choices(ticket))
    if form.is_valid():
        try:
            services.change_status(
                ticket,
                new_status=form.cleaned_data["status"],
                actor=request.user,
                reason=form.cleaned_data.get("reason", ""),
                request=request,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Status updated.")
    else:
        messages.error(request, "That status change is not allowed.")
    return redirect("support_dashboard:ticket_detail", reference=ticket.reference)


@capability_required(Capability.SUPPORT_MANAGE)
def attachment_download(request: HttpRequest, pk) -> HttpResponse:
    attachment = SupportAttachment.objects.filter(pk=pk).first()
    if attachment is None:
        raise Http404("Attachment not found.")
    response = FileResponse(attachment.file.open("rb"), as_attachment=True)
    if attachment.original_filename:
        response["Content-Disposition"] = f'attachment; filename="{attachment.original_filename}"'
    return response

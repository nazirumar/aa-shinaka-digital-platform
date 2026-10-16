"""Customer support-centre views (``/account/support/``)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.upload_security import enforce_downloadable

from . import selectors, services
from .forms import SupportAttachmentForm, SupportReplyForm, SupportTicketForm
from .models import SupportAttachment, SupportStatus


def _owned_ticket(request, reference):
    ticket = selectors.ticket_for(request.user, reference)
    if ticket is None:
        raise Http404("Ticket not found.")
    return ticket


@login_required
def home(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "support/customer/home.html",
        {
            "page_title": "Support",
            "tickets": selectors.tickets_for(request.user)[:8],
            "open_count": selectors.customer_open_count(request.user),
        },
    )


@login_required
def ticket_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "")
    queryset = selectors.tickets_for(request.user)
    if status:
        queryset = queryset.filter(status=status)
    page_obj = _paginate(request, queryset)
    return render(
        request,
        "support/customer/ticket_list.html",
        {
            "page_title": "Support tickets",
            "page_obj": page_obj,
            "tickets": page_obj.object_list,
            "selected_status": status,
            "statuses": _status_choices(),
        },
    )


def _paginate(request, queryset, size: int = 15):
    return Paginator(queryset, size).get_page(request.GET.get("page"))


def _status_choices():
    return SupportStatus.choices


@login_required
@require_http_methods(["GET", "POST"])
def ticket_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = SupportTicketForm(request.POST, customer=request.user)
        if form.is_valid():
            try:
                ticket = services.create_ticket(
                    customer=request.user,
                    subject=form.cleaned_data["subject"],
                    category=form.cleaned_data["category"],
                    priority=form.cleaned_data["priority"],
                    message=form.cleaned_data["message"],
                    files=request.FILES.getlist("attachments"),
                    related_type=form.cleaned_data.get("related_type", ""),
                    related_id=form.cleaned_data.get("related_id", ""),
                    request=request,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, f"Ticket {ticket.reference} has been created.")
                return redirect("support:ticket_detail", reference=ticket.reference)
    else:
        form = SupportTicketForm(customer=request.user)
    return render(
        request,
        "support/customer/ticket_form.html",
        {"form": form, "page_title": "New support ticket"},
    )


@login_required
def ticket_detail(request: HttpRequest, reference: str) -> HttpResponse:
    ticket = _owned_ticket(request, reference)
    return render(
        request,
        "support/customer/ticket_detail.html",
        {
            "page_title": f"Ticket {ticket.reference}",
            "ticket": ticket,
            "ticket_messages": selectors.messages_for(ticket),
            "reply_form": SupportReplyForm(),
            "attachment_form": SupportAttachmentForm(),
        },
    )


@login_required
@require_POST
def ticket_reply(request: HttpRequest, reference: str) -> HttpResponse:
    ticket = _owned_ticket(request, reference)
    form = SupportReplyForm(request.POST)
    if form.is_valid():
        try:
            services.add_customer_message(
                ticket,
                sender=request.user,
                message=form.cleaned_data["message"],
                files=request.FILES.getlist("attachments"),
                request=request,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Your reply has been sent.")
    else:
        messages.error(request, "Please enter a message.")
    return redirect("support:ticket_detail", reference=ticket.reference)


@login_required
@require_POST
def ticket_reopen(request: HttpRequest, reference: str) -> HttpResponse:
    ticket = _owned_ticket(request, reference)
    try:
        services.reopen_ticket(ticket, actor=request.user, request=request)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Ticket reopened.")
    return redirect("support:ticket_detail", reference=ticket.reference)


@login_required
@require_POST
def ticket_close(request: HttpRequest, reference: str) -> HttpResponse:
    ticket = _owned_ticket(request, reference)
    try:
        services.close_ticket(ticket, actor=request.user, request=request)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Ticket closed.")
    return redirect("support:ticket_detail", reference=ticket.reference)


@login_required
def attachment_download(request: HttpRequest, pk) -> HttpResponse:
    attachment = (
        SupportAttachment.objects.filter(pk=pk, ticket__customer=request.user)
        .select_related("message")
        .first()
    )
    if attachment is None:
        raise Http404("Attachment not found.")
    if attachment.message_id and attachment.message.is_internal:
        # Internal notes and their files are never exposed to customers.
        raise Http404("Attachment not found.")
    enforce_downloadable(
        attachment.file, kind="support_attachment", actor=request.user, request=request
    )
    response = FileResponse(attachment.file.open("rb"), as_attachment=True)
    if attachment.original_filename:
        response["Content-Disposition"] = f'attachment; filename="{attachment.original_filename}"'
    return response

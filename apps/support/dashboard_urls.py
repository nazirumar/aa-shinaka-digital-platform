"""Staff support dashboard URLs (mounted at ``/dashboard/support/``)."""

from django.urls import path

from . import dashboard_views

app_name = "support_dashboard"

urlpatterns = [
    path("", dashboard_views.home, name="home"),
    path("tickets/", dashboard_views.ticket_list, name="ticket_list"),
    path("tickets/<str:reference>/", dashboard_views.ticket_detail, name="ticket_detail"),
    path(
        "tickets/<str:reference>/reply/",
        dashboard_views.ticket_reply,
        name="ticket_reply",
    ),
    path(
        "tickets/<str:reference>/assign/",
        dashboard_views.ticket_assign,
        name="ticket_assign",
    ),
    path(
        "tickets/<str:reference>/status/",
        dashboard_views.ticket_status,
        name="ticket_status",
    ),
    path(
        "tickets/<str:reference>/priority/",
        dashboard_views.ticket_priority,
        name="ticket_priority",
    ),
    path(
        "attachments/<uuid:pk>/download/",
        dashboard_views.attachment_download,
        name="attachment_download",
    ),
]

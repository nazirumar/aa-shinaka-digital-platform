"""Customer support URLs (mounted at ``/account/support/``)."""

from django.urls import path

from . import views

app_name = "support"

urlpatterns = [
    path("", views.home, name="home"),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/new/", views.ticket_create, name="ticket_create"),
    path("tickets/<str:reference>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<str:reference>/reply/", views.ticket_reply, name="ticket_reply"),
    path("tickets/<str:reference>/reopen/", views.ticket_reopen, name="ticket_reopen"),
    path("tickets/<str:reference>/close/", views.ticket_close, name="ticket_close"),
    path(
        "attachments/<uuid:pk>/download/",
        views.attachment_download,
        name="attachment_download",
    ),
]

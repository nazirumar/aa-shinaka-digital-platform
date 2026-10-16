"""Customer notification-centre URLs (mounted at ``/account/notifications/``)."""

from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.center, name="center"),
    path("preferences/", views.preferences, name="preferences"),
    path("badge/", views.unread_badge, name="badge"),
    path("read-all/", views.mark_all_read, name="mark_all_read"),
    path("<uuid:pk>/read/", views.mark_read, name="mark_read"),
    path("<uuid:pk>/open/", views.open_notification, name="open"),
]

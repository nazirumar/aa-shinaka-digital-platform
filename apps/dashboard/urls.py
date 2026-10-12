"""Staff dashboard URLs (``/dashboard/...``)."""

from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard_home, name="home"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/create/", views.staff_create, name="staff_create"),
    path("staff/<uuid:pk>/", views.staff_detail, name="staff_detail"),
    path("staff/<uuid:pk>/edit/", views.staff_edit, name="staff_edit"),
    path("staff/<uuid:pk>/toggle-active/", views.staff_toggle_active, name="staff_toggle_active"),
    path("audit/", views.audit_log, name="audit_log"),
]

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthcheck, name="healthcheck"),
    # Fallback trigger for periodic jobs when Celery beat is not deployed.
    path(
        "internal/scheduled-jobs/",
        views.run_scheduled_jobs,
        name="scheduled_jobs",
    ),
    # One-shot owner-account bootstrap for hosts with no interactive shell.
    path(
        "internal/bootstrap-owner/",
        views.bootstrap_owner,
        name="bootstrap_owner",
    ),
]

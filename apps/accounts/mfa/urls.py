"""MFA URLs."""

from django.urls import path

from . import views

app_name = "mfa"

urlpatterns = [
    # Login second-factor challenge (unauthenticated, parked session).
    path("challenge/", views.challenge, name="challenge"),
    # Enrolment & management (authenticated).
    path("start/", views.start, name="start"),
    path("confirm/", views.confirm, name="confirm"),
    path("verify/", views.verify, name="verify"),
    path("disable/", views.disable, name="disable"),
]

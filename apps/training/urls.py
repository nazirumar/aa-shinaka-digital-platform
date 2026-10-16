"""Public training-academy URLs, mounted at ``/training/``.

Student-portal URLs live in :mod:`apps.training.account_urls` (``/account/training/``)
and the staff dashboard in :mod:`apps.training.dashboard_urls`
(``/dashboard/training/``).
"""

from django.urls import path

from . import views

app_name = "training"

urlpatterns = [
    path("", views.training_home, name="training_home"),
    path("courses/", views.course_list, name="course_list"),
    path("courses/<slug:slug>/", views.course_detail, name="course_detail"),
    path("categories/<slug:slug>/", views.category_detail, name="category_detail"),
    path("sessions/", views.session_list, name="session_list"),
    path("sessions/<uuid:pk>/", views.session_detail, name="session_detail"),
    path("sessions/<uuid:pk>/enrol/", views.enroll, name="enroll"),
    # Public certificate verification (non-guessable code).
    path("verify/", views.certificate_verify, name="certificate_verify"),
    path("verify/<str:code>/", views.certificate_verify, name="certificate_verify_code"),
    # Payment callback re-verifies server-side through the Phase 6 pipeline.
    path("payments/callback/<str:reference>/", views.payment_callback, name="payment_callback"),
]

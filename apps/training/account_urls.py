"""Student training-portal URLs, mounted at ``/account/training/``.

Every view is login-required and scoped to the signed-in student.
"""

from django.urls import path

from . import account_views as views

app_name = "training_account"

urlpatterns = [
    path("", views.student_home, name="home"),
    path("courses/", views.my_courses, name="my_courses"),
    path("sessions/", views.upcoming_sessions, name="upcoming_sessions"),
    path("enrolments/", views.enrollment_list, name="enrollment_list"),
    path("enrolments/<str:reference>/", views.enrollment_detail, name="enrollment_detail"),
    path("enrolments/<str:reference>/pay/", views.enrollment_pay, name="enrollment_pay"),
    path("enrolments/<str:reference>/cancel/", views.enrollment_cancel, name="enrollment_cancel"),
    path(
        "enrolments/<str:reference>/lessons/<uuid:lesson_id>/complete/",
        views.lesson_complete,
        name="lesson_complete",
    ),
    path(
        "enrolments/<str:reference>/assessments/<uuid:assessment_id>/",
        views.assessment_take,
        name="assessment_take",
    ),
    path("resources/<uuid:pk>/download/", views.resource_download, name="resource_download"),
    path("certificates/", views.certificate_list, name="certificate_list"),
    path("certificates/<uuid:pk>/", views.certificate_view, name="certificate_view"),
    path(
        "certificates/<uuid:pk>/download/", views.certificate_download, name="certificate_download"
    ),
    path("payments/", views.payment_history, name="payment_history"),
]

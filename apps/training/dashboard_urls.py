"""Staff training-dashboard URLs, mounted at ``/dashboard/training/``."""

from django.urls import path

from . import dashboard_views as views

app_name = "training_dashboard"

urlpatterns = [
    path("", views.dashboard_home, name="home"),
    # Categories
    path("categories/", views.category_list, name="category_list"),
    path("categories/new/", views.category_create, name="category_create"),
    path("categories/<uuid:pk>/edit/", views.category_edit, name="category_edit"),
    path("categories/<uuid:pk>/toggle/", views.category_toggle, name="category_toggle"),
    # Courses
    path("courses/", views.course_list, name="course_list"),
    path("courses/new/", views.course_create, name="course_create"),
    path("courses/<uuid:pk>/", views.course_detail, name="course_detail"),
    path("courses/<uuid:pk>/edit/", views.course_edit, name="course_edit"),
    path("courses/<uuid:pk>/publish/", views.course_publish, name="course_publish"),
    path("courses/<uuid:pk>/archive/", views.course_archive, name="course_archive"),
    path("courses/<uuid:pk>/modules/new/", views.module_create, name="module_create"),
    path("modules/<uuid:module_pk>/lessons/new/", views.lesson_create, name="lesson_create"),
    path("courses/<uuid:pk>/resources/new/", views.resource_create, name="resource_create"),
    # Instructors
    path("instructors/", views.instructor_list, name="instructor_list"),
    path("instructors/new/", views.instructor_create, name="instructor_create"),
    path("instructors/<uuid:pk>/edit/", views.instructor_edit, name="instructor_edit"),
    path("instructors/<uuid:pk>/toggle/", views.instructor_toggle, name="instructor_toggle"),
    path("assignments/new/", views.assignment_create, name="assignment_create"),
    path(
        "assignments/<uuid:pk>/remove/",
        views.assignment_deactivate,
        name="assignment_deactivate",
    ),
    # Venues
    path("venues/", views.venue_list, name="venue_list"),
    path("venues/new/", views.venue_create, name="venue_create"),
    # Sessions
    path("sessions/", views.session_list, name="session_list"),
    path("sessions/new/", views.session_create, name="session_create"),
    path("sessions/<uuid:pk>/", views.session_detail, name="session_detail"),
    path("sessions/<uuid:pk>/transition/", views.session_transition, name="session_transition"),
    path("sessions/<uuid:pk>/schedule/new/", views.schedule_create, name="schedule_create"),
    path(
        "sessions/<uuid:pk>/attendance/new/",
        views.attendance_register_create,
        name="attendance_register_create",
    ),
    # Enrolments
    path("enrolments/", views.enrollment_list, name="enrollment_list"),
    path("enrolments/<str:reference>/", views.enrollment_detail, name="enrollment_detail"),
    path(
        "enrolments/<str:reference>/action/",
        views.enrollment_action,
        name="enrollment_action",
    ),
    # Attendance
    path("attendance/", views.attendance_session_list, name="attendance_session_list"),
    path("attendance/<uuid:pk>/", views.attendance_detail, name="attendance_detail"),
    path("attendance/<uuid:pk>/mark/", views.attendance_mark, name="attendance_mark"),
    # Assessments
    path("assessments/", views.assessment_list, name="assessment_list"),
    path(
        "courses/<uuid:pk>/assessments/new/",
        views.assessment_create,
        name="assessment_create",
    ),
    path("assessments/<uuid:pk>/", views.assessment_detail, name="assessment_detail"),
    path("assessments/<uuid:pk>/publish/", views.assessment_publish, name="assessment_publish"),
    path(
        "assessments/<uuid:pk>/questions/new/",
        views.question_create,
        name="question_create",
    ),
    path(
        "questions/<uuid:question_pk>/options/new/",
        views.option_create,
        name="option_create",
    ),
    path("submissions/<uuid:pk>/grade/", views.submission_grade, name="submission_grade"),
    # Certificates
    path("certificates/", views.certificate_list, name="certificate_list"),
    path(
        "certificates/issue/<str:reference>/",
        views.certificate_issue,
        name="certificate_issue",
    ),
    path("certificates/<uuid:pk>/revoke/", views.certificate_revoke, name="certificate_revoke"),
    path(
        "certificate-templates/",
        views.certificate_template_list,
        name="certificate_template_list",
    ),
    # Reports
    path("reports/", views.reports, name="reports"),
]

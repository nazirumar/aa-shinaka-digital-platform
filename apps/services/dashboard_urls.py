"""Staff service-dashboard URLs (``/dashboard/services/...``).

Mounted from ``config.urls`` inside the staff dashboard. Every view enforces a
capability server-side.
"""

from django.urls import path

from . import dashboard_views as views

app_name = "services_dashboard"

urlpatterns = [
    path("", views.dashboard_home, name="home"),
    # Requests.
    path("requests/", views.request_list, name="request_list"),
    path("requests/<str:reference>/", views.request_detail, name="request_detail"),
    # Consultancy appointments.
    path("appointments/<uuid:pk>/confirm/", views.appointment_confirm, name="appointment_confirm"),
    path(
        "appointments/<uuid:pk>/complete/", views.appointment_complete, name="appointment_complete"
    ),
    # Farming.
    path("farm/projects/", views.farm_project_list, name="farm_project_list"),
    path("farm/requests/<uuid:pk>/project/", views.farm_project_create, name="farm_project_create"),
    path("farm/projects/<uuid:pk>/", views.farm_project_detail, name="farm_project_detail"),
    # Marketing.
    path("marketing/", views.marketing_list, name="marketing_list"),
    path("marketing/<uuid:pk>/", views.marketing_enquiry_detail, name="marketing_enquiry_detail"),
    # Storage.
    path("storage/facilities/", views.facility_list, name="facility_list"),
    path("storage/facilities/new/", views.facility_create, name="facility_create"),
    path("storage/facilities/<uuid:pk>/", views.facility_detail, name="facility_detail"),
    path("storage/bookings/", views.booking_list, name="booking_list"),
    path("storage/requests/<uuid:pk>/booking/", views.booking_create, name="booking_create"),
    path("storage/bookings/<uuid:pk>/", views.booking_detail, name="booking_detail"),
    # Quotations.
    path("quotations/", views.quotation_list, name="quotation_list"),
    path("quotations/new/<str:reference>/", views.quotation_create, name="quotation_create"),
    path("quotations/<uuid:pk>/", views.quotation_detail, name="quotation_detail"),
]

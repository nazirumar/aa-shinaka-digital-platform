"""Customer service-portal URLs (``/account/services/...``).

Mounted by ``config.urls`` inside the customer account area. All write actions
go through the service layer and are ownership-checked.
"""

from django.urls import path

from . import views

app_name = "services"

urlpatterns = [
    path("", views.service_home, name="service_home"),
    path("requests/", views.request_list, name="request_list"),
    path("requests/<str:reference>/", views.request_detail, name="request_detail"),
    # New requests, one per division.
    path("consultation/new/", views.consultation_create, name="consultation_create"),
    path("farming/new/", views.farming_create, name="farming_create"),
    path("marketing/new/", views.marketing_create, name="marketing_create"),
    path("storage/new/", views.storage_create, name="storage_create"),
    # Quotations.
    path("quotations/", views.quotation_list, name="quotation_list"),
    path("quotations/<uuid:pk>/", views.quotation_detail, name="quotation_detail"),
    path("quotations/<uuid:pk>/pay/", views.quotation_pay, name="quotation_pay"),
    path(
        "payments/callback/<str:reference>/",
        views.service_payment_callback,
        name="service_payment_callback",
    ),
    # Marketing proposals.
    path("proposals/<uuid:pk>/decide/", views.proposal_decide, name="proposal_decide"),
]

"""Customer export-portal URLs (mounted at ``/account/export/``)."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "export"

urlpatterns = [
    path("", views.export_home, name="home"),
    # Enquiries
    path("enquiries/", views.enquiry_list, name="enquiry_list"),
    path("enquiries/new/", views.enquiry_create, name="enquiry_create"),
    path("enquiries/<str:reference>/", views.enquiry_detail, name="enquiry_detail"),
    # Quotations
    path("quotations/", views.quotation_list, name="quotation_list"),
    path("quotations/<uuid:pk>/", views.quotation_detail, name="quotation_detail"),
    path("quotations/<uuid:pk>/accept/", views.quotation_accept, name="quotation_accept"),
    # Orders
    path("orders/", views.order_list, name="order_list"),
    path("orders/<str:reference>/", views.order_detail, name="order_detail"),
    path("orders/<str:reference>/pay/", views.order_pay, name="order_pay"),
    path(
        "orders/<str:reference>/documents/upload/",
        views.document_upload,
        name="document_upload",
    ),
    # Documents
    path("documents/<uuid:pk>/download/", views.document_download, name="document_download"),
    # Shipments
    path("shipments/", views.shipment_list, name="shipment_list"),
    path("shipments/<str:reference>/", views.shipment_detail, name="shipment_detail"),
    # Payments
    path("payments/callback/<str:reference>/", views.payment_callback, name="payment_callback"),
]

"""Staff export-dashboard URLs (mounted at ``/dashboard/export/``)."""

from __future__ import annotations

from django.urls import path

from . import dashboard_views as views

app_name = "export_dashboard"

urlpatterns = [
    path("", views.dashboard_home, name="home"),
    # Destinations
    path("destinations/", views.destination_list, name="destination_list"),
    path("destinations/new/", views.destination_create, name="destination_create"),
    path("destinations/<uuid:pk>/", views.destination_detail, name="destination_detail"),
    path("destinations/<uuid:pk>/approve/", views.destination_approve, name="destination_approve"),
    path(
        "destinations/<uuid:pk>/activate/",
        views.destination_toggle_active,
        name="destination_toggle_active",
    ),
    path(
        "destinations/<uuid:pk>/requirements/new/",
        views.requirement_create,
        name="requirement_create",
    ),
    path(
        "destinations/<uuid:pk>/restrictions/new/",
        views.restriction_create,
        name="restriction_create",
    ),
    path(
        "destinations/<uuid:pk>/documents/new/",
        views.document_requirement_create,
        name="document_requirement_create",
    ),
    # Product configuration
    path("products/", views.product_list, name="product_list"),
    path("products/<uuid:pk>/", views.product_edit, name="product_edit"),
    # Enquiries
    path("enquiries/", views.enquiry_list, name="enquiry_list"),
    path("enquiries/<str:reference>/", views.enquiry_detail, name="enquiry_detail"),
    path("enquiries/<str:reference>/action/", views.enquiry_action, name="enquiry_action"),
    path(
        "enquiries/<str:reference>/quotation/new/",
        views.quotation_create,
        name="quotation_create",
    ),
    # Quotations
    path("quotations/", views.quotation_list, name="quotation_list"),
    path("quotations/<uuid:pk>/", views.quotation_detail, name="quotation_detail"),
    path("quotations/<uuid:pk>/approve/", views.quotation_approve, name="quotation_approve"),
    path("quotations/<uuid:pk>/revise/", views.quotation_revise, name="quotation_revise"),
    # Orders
    path("orders/", views.order_list, name="order_list"),
    path("orders/<str:reference>/", views.order_detail, name="order_detail"),
    path("orders/<str:reference>/transition/", views.order_transition, name="order_transition"),
    # Documents
    path("documents/", views.document_list, name="document_list"),
    path("documents/<uuid:pk>/", views.document_detail, name="document_detail"),
    path("documents/<uuid:pk>/review/", views.document_review, name="document_review"),
    path("orders/<str:reference>/documents/new/", views.document_create, name="document_create"),
    # Compliance
    path("compliance/", views.compliance_list, name="compliance_list"),
    path("compliance/<uuid:pk>/", views.compliance_detail, name="compliance_detail"),
    path(
        "compliance/<uuid:pk>/approve/",
        views.compliance_approve,
        name="compliance_approve",
    ),
    path(
        "compliance/items/<uuid:pk>/",
        views.compliance_item_update,
        name="compliance_item_update",
    ),
    # Shipments
    path("shipments/", views.shipment_list, name="shipment_list"),
    path("shipments/new/", views.shipment_create, name="shipment_create"),
    path("shipments/<str:reference>/", views.shipment_detail, name="shipment_detail"),
    path(
        "shipments/<str:reference>/transition/",
        views.shipment_transition,
        name="shipment_transition",
    ),
    path(
        "shipments/<str:reference>/milestone/",
        views.shipment_milestone,
        name="shipment_milestone",
    ),
    # Logistics providers
    path("providers/", views.provider_list, name="provider_list"),
    path("providers/new/", views.provider_create, name="provider_create"),
    # Reports
    path("reports/", views.reports, name="reports"),
]

"""Orders management URLs (``/dashboard/orders/...``).

Mounted from ``config.urls`` inside the staff dashboard. Views enforce the
ORDERS_MANAGE (or FINANCE_MANAGE) capability server-side.
"""

from django.urls import path

from . import dashboard_views as views

app_name = "orders_dashboard"

urlpatterns = [
    path("", views.OrderDashboardHome.as_view(), name="home"),
    path("orders/", views.OrderListView.as_view(), name="order_list"),
    path("orders/<str:number>/", views.OrderDetailView.as_view(), name="order_detail"),
    path(
        "orders/<str:number>/status/",
        views.OrderStatusUpdateView.as_view(),
        name="order_status",
    ),
    path(
        "orders/<str:number>/cancel/",
        views.OrderCancelView.as_view(),
        name="order_cancel",
    ),
    path(
        "orders/<str:number>/confirm-payment/",
        views.OrderConfirmPaymentView.as_view(),
        name="order_confirm_payment",
    ),
    path(
        "orders/<str:number>/shipments/new/",
        views.ShipmentCreateView.as_view(),
        name="shipment_create",
    ),
    path(
        "shipments/<uuid:pk>/status/",
        views.ShipmentStatusView.as_view(),
        name="shipment_status",
    ),
    # Quotations
    path("quotations/", views.QuotationListView.as_view(), name="quotation_list"),
    path(
        "quotations/<uuid:pk>/",
        views.QuotationDetailView.as_view(),
        name="quotation_detail",
    ),
    path(
        "quotations/<uuid:pk>/review/",
        views.QuotationReviewView.as_view(),
        name="quotation_review",
    ),
    # Shipping configuration
    path("shipping/zones/", views.ShippingZoneListView.as_view(), name="shipping_zone_list"),
    path(
        "shipping/zones/new/",
        views.ShippingZoneCreateView.as_view(),
        name="shipping_zone_create",
    ),
    path(
        "shipping/zones/<uuid:pk>/edit/",
        views.ShippingZoneUpdateView.as_view(),
        name="shipping_zone_edit",
    ),
    path(
        "shipping/methods/",
        views.ShippingMethodListView.as_view(),
        name="shipping_method_list",
    ),
    path(
        "shipping/methods/new/",
        views.ShippingMethodCreateView.as_view(),
        name="shipping_method_create",
    ),
    path(
        "shipping/methods/<uuid:pk>/edit/",
        views.ShippingMethodUpdateView.as_view(),
        name="shipping_method_edit",
    ),
    path("shipping/rates/", views.ShippingRateListView.as_view(), name="shipping_rate_list"),
    path(
        "shipping/rates/new/",
        views.ShippingRateCreateView.as_view(),
        name="shipping_rate_create",
    ),
    path(
        "shipping/rates/<uuid:pk>/edit/",
        views.ShippingRateUpdateView.as_view(),
        name="shipping_rate_edit",
    ),
]

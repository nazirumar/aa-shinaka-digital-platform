"""Staff customer-overview URLs (``/dashboard/customers/``)."""

from django.urls import path

from . import customer_dashboard_views as views

app_name = "customers_dashboard"

urlpatterns = [
    path("", views.customer_list, name="list"),
    path("<uuid:pk>/", views.customer_detail, name="detail"),
]

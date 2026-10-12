"""Customer account portal URLs (``/account/...``)."""

from django.urls import path

from . import account_views

app_name = "account"

urlpatterns = [
    path("", account_views.dashboard, name="dashboard"),
    path("dashboard/", account_views.dashboard, name="dashboard_home"),
    path("profile/", account_views.profile, name="profile"),
    path("addresses/", account_views.address_list, name="addresses"),
    path("addresses/add/", account_views.address_create, name="address_add"),
    path("addresses/<int:pk>/edit/", account_views.address_edit, name="address_edit"),
    path("addresses/<int:pk>/delete/", account_views.address_delete, name="address_delete"),
    path("addresses/<int:pk>/default/", account_views.address_set_default, name="address_default"),
    path("security/", account_views.security, name="security"),
]

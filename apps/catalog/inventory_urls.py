"""Inventory management URLs (``/dashboard/inventory/...``).

Mounted from ``config.urls`` inside the staff dashboard. Every view enforces the
inventory capability server-side (see ``InventoryAccessMixin``).
"""

from django.urls import path

from . import dashboard_views as views

app_name = "inventory_dashboard"

urlpatterns = [
    path("", views.InventoryHomeView.as_view(), name="home"),
    path("warehouses/", views.WarehouseListView.as_view(), name="warehouse_list"),
    path("warehouses/new/", views.WarehouseCreateView.as_view(), name="warehouse_create"),
    path(
        "warehouses/<uuid:pk>/edit/",
        views.WarehouseUpdateView.as_view(),
        name="warehouse_edit",
    ),
    path("stock/", views.StockBalanceListView.as_view(), name="stock_list"),
    path("movements/", views.StockMovementListView.as_view(), name="movement_list"),
    path("reservations/", views.ReservationListView.as_view(), name="reservation_list"),
    path(
        "stock/<uuid:pk>/receive/",
        views.StockReceiveView.as_view(),
        name="stock_receive",
    ),
    path(
        "stock/<uuid:pk>/transfer/",
        views.StockTransferView.as_view(),
        name="stock_transfer",
    ),
    path("low-stock/", views.LowStockListView.as_view(), name="low_stock"),
]

"""Public/customer order URLs (``/cart/``, ``/checkout/``, ``/orders/``).

Mounted at the site root by ``config.urls``. Writes (cart, checkout, order
actions) all go through the service layer.
"""

from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("cart/", views.cart_detail, name="cart"),
    path("cart/add/<uuid:pk>/", views.cart_add, name="cart_add"),
    path("cart/items/<uuid:pk>/update/", views.cart_item_update, name="cart_item_update"),
    path("cart/items/<uuid:pk>/remove/", views.cart_item_remove, name="cart_item_remove"),
    path("cart/clear/", views.cart_clear, name="cart_clear"),
    path("cart/summary/", views.cart_summary, name="cart_summary"),
    path("checkout/", views.checkout, name="checkout"),
    path(
        "checkout/shipping-options/",
        views.checkout_shipping_options,
        name="checkout_shipping_options",
    ),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<str:number>/", views.order_detail, name="order_detail"),
    path("orders/<str:number>/cancel/", views.order_cancel, name="order_cancel"),
    path(
        "orders/<str:number>/payment-review/",
        views.order_payment_review,
        name="order_payment_review",
    ),
    path("quotations/", views.quotation_list, name="quotation_list"),
    path(
        "quotations/new/<uuid:listing_pk>/",
        views.quotation_create,
        name="quotation_create",
    ),
]

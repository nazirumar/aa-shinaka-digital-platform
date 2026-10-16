"""Public/customer order URLs (``/cart/``, ``/checkout/``, ``/orders/``).

Mounted at the site root by ``config.urls``. Writes (cart, checkout, order
actions, payments) all go through the service layer.
"""

from django.urls import path

from . import payment_views, views

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
    # Phase 6 — payments, bank transfers, invoices & receipts
    path("orders/<str:number>/pay/", payment_views.payment_start, name="payment_start"),
    path(
        "orders/<str:number>/payment/callback/",
        payment_views.payment_callback,
        name="payment_callback",
    ),
    path(
        "orders/<str:number>/bank-transfer/",
        payment_views.bank_transfer_submit,
        name="bank_transfer_submit",
    ),
    path("payments/", payment_views.payment_list, name="payment_list"),
    path("payments/<uuid:pk>/", payment_views.payment_detail, name="payment_detail"),
    path("payments/paystack/webhook/", payment_views.paystack_webhook, name="paystack_webhook"),
    path("invoices/", payment_views.invoice_list, name="invoice_list"),
    path("invoices/<str:number>/", payment_views.invoice_detail, name="invoice_detail"),
    path("invoices/<str:number>/pdf/", payment_views.invoice_pdf, name="invoice_pdf"),
    path("receipts/<str:number>/", payment_views.receipt_detail, name="receipt_detail"),
    path("receipts/<str:number>/pdf/", payment_views.receipt_pdf, name="receipt_pdf"),
    path("quotations/", views.quotation_list, name="quotation_list"),
    path(
        "quotations/new/<uuid:listing_pk>/",
        views.quotation_create,
        name="quotation_create",
    ),
]

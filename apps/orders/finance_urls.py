"""Finance dashboard URLs (``/dashboard/finance/...``).

Mounted from ``config.urls`` inside the staff dashboard. Every view enforces the
``FINANCE_MANAGE`` capability server-side.
"""

from django.urls import path

from . import finance_views as views

app_name = "finance_dashboard"

urlpatterns = [
    path("", views.FinanceDashboardHome.as_view(), name="home"),
    # Payments
    path("payments/", views.PaymentListView.as_view(), name="payment_list"),
    path("payments/<uuid:pk>/", views.PaymentDetailView.as_view(), name="payment_detail"),
    path(
        "payments/<uuid:pk>/reconcile/",
        views.PaymentReconcileView.as_view(),
        name="payment_reconcile",
    ),
    path(
        "payments/<uuid:pk>/refund/",
        views.RefundRequestView.as_view(),
        name="refund_request",
    ),
    # Bank transfers
    path("transfers/", views.BankTransferListView.as_view(), name="bank_transfer_list"),
    path(
        "transfers/<uuid:pk>/",
        views.BankTransferDetailView.as_view(),
        name="bank_transfer_detail",
    ),
    path(
        "transfers/<uuid:pk>/review/",
        views.BankTransferReviewView.as_view(),
        name="bank_transfer_review",
    ),
    # Refunds
    path("refunds/", views.RefundListView.as_view(), name="refund_list"),
    path("refunds/<uuid:pk>/", views.RefundDetailView.as_view(), name="refund_detail"),
    path(
        "refunds/<uuid:pk>/approve/",
        views.RefundApproveView.as_view(),
        name="refund_approve",
    ),
    path(
        "refunds/<uuid:pk>/complete/",
        views.RefundCompleteView.as_view(),
        name="refund_complete",
    ),
    # Invoices
    path("invoices/", views.InvoiceListView.as_view(), name="invoice_list"),
    path(
        "invoices/<str:number>/",
        views.InvoiceDetailView.as_view(),
        name="invoice_detail",
    ),
    # Bank accounts
    path("bank-accounts/", views.BankAccountListView.as_view(), name="bank_account_list"),
    path(
        "bank-accounts/new/",
        views.BankAccountCreateView.as_view(),
        name="bank_account_create",
    ),
    path(
        "bank-accounts/<uuid:pk>/edit/",
        views.BankAccountUpdateView.as_view(),
        name="bank_account_edit",
    ),
    path(
        "bank-accounts/<uuid:pk>/toggle/",
        views.BankAccountToggleView.as_view(),
        name="bank_account_toggle",
    ),
]

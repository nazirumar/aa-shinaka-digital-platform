"""Catalogue management URLs (``/dashboard/catalog/...``).

Mounted from ``config.urls`` inside the staff dashboard. Every view enforces a
catalogue or inventory capability server-side.
"""

from django.urls import path

from . import dashboard_views as views

app_name = "catalog_dashboard"

urlpatterns = [
    path("", views.CatalogHomeView.as_view(), name="home"),
    # Categories
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/new/", views.CategoryCreateView.as_view(), name="category_create"),
    path(
        "categories/<uuid:pk>/edit/",
        views.CategoryUpdateView.as_view(),
        name="category_edit",
    ),
    path(
        "categories/<uuid:pk>/delete/",
        views.CategoryDeleteView.as_view(),
        name="category_delete",
    ),
    path(
        "categories/<uuid:pk>/reorder/",
        views.CategoryReorderView.as_view(),
        name="category_reorder",
    ),
    path(
        "categories/<uuid:pk>/toggle/",
        views.CategoryToggleView.as_view(),
        name="category_toggle",
    ),
    # Products
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/new/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<uuid:pk>/edit/", views.ProductUpdateView.as_view(), name="product_edit"),
    path("products/<uuid:pk>/delete/", views.ProductDeleteView.as_view(), name="product_delete"),
    path("products/<uuid:pk>/publish/", views.ProductPublishView.as_view(), name="product_publish"),
    path(
        "products/<uuid:pk>/images/",
        views.ProductImageManageView.as_view(),
        name="product_images",
    ),
    path(
        "products/<uuid:pk>/images/<uuid:image_pk>/delete/",
        views.ProductImageDeleteView.as_view(),
        name="product_image_delete",
    ),
    path(
        "products/<uuid:pk>/images/<uuid:image_pk>/primary/",
        views.ProductImagePrimaryView.as_view(),
        name="product_image_primary",
    ),
    # Listings
    path("listings/", views.ListingListView.as_view(), name="listing_list"),
    path("listings/new/", views.ListingCreateView.as_view(), name="listing_create"),
    path("listings/<uuid:pk>/", views.ListingDetailView.as_view(), name="listing_detail"),
    path("listings/<uuid:pk>/edit/", views.ListingUpdateView.as_view(), name="listing_edit"),
    path("listings/<uuid:pk>/delete/", views.ListingArchiveView.as_view(), name="listing_archive"),
    path("listings/<uuid:pk>/status/", views.ListingStatusView.as_view(), name="listing_status"),
    path("listings/<uuid:pk>/price/", views.ListingPriceView.as_view(), name="listing_price"),
    path("listings/<uuid:pk>/stock/", views.ListingStockView.as_view(), name="listing_stock"),
    path("listings/<uuid:pk>/variants/", views.VariantCreateView.as_view(), name="variant_create"),
    path("listings/<uuid:pk>/tiers/", views.TierCreateView.as_view(), name="tier_create"),
    path("tiers/<uuid:pk>/delete/", views.TierDeleteView.as_view(), name="tier_delete"),
    # Inventory
    path("low-stock/", views.LowStockListView.as_view(), name="low_stock"),
    # Market reference prices
    path("references/", views.ReferenceListView.as_view(), name="reference_list"),
    path("references/new/", views.ReferenceCreateView.as_view(), name="reference_create"),
    path("references/<uuid:pk>/edit/", views.ReferenceUpdateView.as_view(), name="reference_edit"),
]

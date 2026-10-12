"""Django admin registration for the catalogue (developer/superuser convenience).

Staff use the custom dashboard at ``/dashboard/catalog/``; the admin is kept for
superusers and developer operations.
"""

from __future__ import annotations

from django.contrib import admin

from .models import (
    Category,
    ListingPrice,
    MarketReferencePrice,
    PriceHistory,
    Product,
    ProductImage,
    ProductListing,
    ProductVariant,
    StockMovement,
    Tag,
    UnitOfMeasure,
    WholesalePriceTier,
)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


class ListingPriceInline(admin.TabularInline):
    model = ListingPrice
    extra = 0
    fields = (
        "variant",
        "price_type",
        "amount",
        "compare_at",
        "valid_from",
        "valid_to",
        "is_active",
    )


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "depth", "is_active", "is_featured", "sort_order")
    list_filter = ("is_active", "is_featured")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("path", "depth")


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "symbol", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "code")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "status", "is_featured", "unit", "updated_at")
    list_filter = ("status", "is_featured", "category")
    search_fields = ("name", "slug", "variety")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ProductImageInline,)


@admin.register(ProductListing)
class ProductListingAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "state",
        "lga",
        "package_size",
        "package_unit",
        "selling_price",
        "stock_on_hand",
        "status",
    )
    list_filter = ("status", "state", "origin_verification")
    search_fields = ("product__name", "state__name", "lga__name")
    inlines = (ProductVariantInline, ListingPriceInline)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("product", "listing", "alt_text", "sort_order")
    search_fields = ("product__name", "alt_text")


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("listing", "name", "sort_order", "is_active")
    search_fields = ("name", "listing__product__name")


@admin.register(ListingPrice)
class ListingPriceAdmin(admin.ModelAdmin):
    list_display = ("listing", "variant", "price_type", "amount", "currency", "is_active")
    list_filter = ("price_type", "is_active")


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ("listing", "variant", "old_price", "new_price", "changed_by", "created_at")
    readonly_fields = (
        "listing",
        "variant",
        "old_price",
        "new_price",
        "currency",
        "changed_by",
        "note",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WholesalePriceTier)
class WholesalePriceTierAdmin(admin.ModelAdmin):
    list_display = ("listing", "variant", "min_quantity", "price", "currency", "is_active")
    list_filter = ("is_active",)


@admin.register(MarketReferencePrice)
class MarketReferencePriceAdmin(admin.ModelAdmin):
    list_display = ("product", "state", "year", "season", "price_per_unit", "unit")
    list_filter = ("year", "state")
    search_fields = ("product__name",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("listing", "kind", "quantity_delta", "balance_after", "actor", "created_at")
    list_filter = ("kind",)
    readonly_fields = (
        "listing",
        "kind",
        "quantity_delta",
        "balance_after",
        "reference",
        "actor",
        "note",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

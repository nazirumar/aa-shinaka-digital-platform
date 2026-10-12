"""Django admin registration for website content (owner/developer convenience).

The primary editing surface for staff is the custom CMS dashboard; the admin is
kept for superusers and developer operations.
"""

from django.contrib import admin

from .models import (
    FAQ,
    BlogCategory,
    BlogPost,
    BusinessDivision,
    ContactEnquiry,
    HeroBanner,
    MediaAsset,
    NavigationItem,
    Page,
    ServiceCategory,
    ServicePage,
    SiteSetting,
    TeamMember,
    Testimonial,
)


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("title", "alt_text", "uploaded_by", "created_at")
    search_fields = ("title", "alt_text")


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()


@admin.register(NavigationItem)
class NavigationItemAdmin(admin.ModelAdmin):
    list_display = ("label", "placement", "parent", "sort_order", "is_active")
    list_filter = ("placement", "is_active")
    search_fields = ("label", "url_name", "url")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "page_type", "status", "updated_at")
    list_filter = ("page_type", "status")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(HeroBanner)
class HeroBannerAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "sort_order", "is_featured")
    list_filter = ("status", "is_featured")


@admin.register(BusinessDivision)
class BusinessDivisionAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "sort_order")
    list_filter = ("status",)
    search_fields = ("name",)


class ServiceCategoryInline(admin.TabularInline):
    model = ServiceCategory
    extra = 0


@admin.register(ServicePage)
class ServicePageAdmin(admin.ModelAdmin):
    list_display = ("title", "division", "status", "sort_order")
    list_filter = ("status", "division")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ServiceCategoryInline]


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("question", "service_page", "sort_order", "is_published")
    list_filter = ("is_published",)
    search_fields = ("question",)


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ("author_name", "is_approved", "is_featured", "sort_order")
    list_filter = ("is_approved", "is_featured")
    search_fields = ("author_name", "quote")


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "role_title", "sort_order", "is_active")
    list_filter = ("is_active",)


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "status", "published_at")
    list_filter = ("status", "category")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ContactEnquiry)
class ContactEnquiryAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "division", "is_handled", "created_at")
    list_filter = ("is_handled", "division")
    search_fields = ("name", "email", "message")
    readonly_fields = ("ip_address", "user_agent", "created_at", "updated_at")

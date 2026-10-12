"""Root URL configuration.

Each business domain owns its own ``urls.py`` and is mounted under a stable
prefix. Feature apps add their routes here as phases land.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.catalog import views as catalog_views
from apps.cms.sitemaps import SITEMAPS

urlpatterns = [
    path("admin/", admin.site.urls),
    # Internationalisation: language switching (``/i18n/setlang/``).
    path("i18n/", include("django.conf.urls.i18n")),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
    path("", include("apps.core.urls")),
    # Public website content (services, about, contact, news, pages, robots.txt).
    path("", include("apps.cms.urls")),
    # Public commerce: cart, checkout, customer orders, quotation requests.
    path("", include("apps.orders.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("account/", include("apps.accounts.account_urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    # CMS management screens, inside the staff dashboard.
    path("dashboard/cms/", include("apps.cms.dashboard_urls")),
    # Order & shipping management screens, inside the staff dashboard.
    path("dashboard/orders/", include("apps.orders.dashboard_urls")),
    # Public catalogue (shop index, categories, products, search, compare).
    path("shop/", include("apps.catalog.urls")),
    # Catalogue management screens, inside the staff dashboard.
    path("dashboard/catalog/", include("apps.catalog.dashboard_urls")),
    # Inventory management screens (warehouses, balances, movements, reservations).
    path("dashboard/inventory/", include("apps.catalog.inventory_urls")),
    # Legacy catalogue aliases kept stable for shared links (UI_UX_SPEC §5.2).
    path("states/", catalog_views.state_list, name="state_list"),
    path("states/<slug:slug>/", catalog_views.state_detail, name="state_detail"),
    path("states/<slug:state>/<slug:lga>/", catalog_views.lga_detail, name="lga_detail"),
    path("products/<slug:slug>/", catalog_views.product_detail, name="product_detail"),
    path("shop/<slug:slug>/", catalog_views.category_detail, name="category_detail_legacy"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

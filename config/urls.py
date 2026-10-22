"""Root URL configuration.

Each business domain owns its own ``urls.py`` and is mounted under a stable
prefix. Feature apps add their routes here as phases land.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import index as sitemap_index
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.catalog import views as catalog_views
from apps.cms.sitemaps import SITEMAPS

urlpatterns = [
    path("admin/", admin.site.urls),
    # Internationalisation: language switching (``/i18n/setlang/``).
    path("i18n/", include("django.conf.urls.i18n")),
    # Flat urlset kept exactly as before, so existing consumers and tests that
    # expect individual page URLs here keep working.
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
    # A proper sitemap index alongside it, enumerating each section. Search
    # engines accept either; the index scales past the 50k-URL ceiling and lets
    # each section be submitted and diagnosed independently.
    path("sitemap-index.xml", sitemap_index, {"sitemaps": SITEMAPS}, name="sitemap_index"),
    path(
        "sitemap-<section>.xml",
        sitemap,
        {"sitemaps": SITEMAPS},
        # Django's `sitemap_index` view reverses this exact name to build the
        # child <loc> entries, so it cannot be renamed.
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("", include("apps.core.urls")),
    # Public website content (services, about, contact, news, pages, robots.txt).
    path("", include("apps.cms.urls")),
    # Public commerce: cart, checkout, customer orders, quotation requests.
    path("", include("apps.orders.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("account/", include("apps.accounts.account_urls")),
    path("accounts/mfa/", include("apps.accounts.mfa.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    # Analytics, business intelligence and controlled reporting (Phase 11).
    path("dashboard/", include("apps.analytics.urls")),
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
    # Finance dashboard (payments, bank transfers, refunds, invoices, accounts).
    path("dashboard/finance/", include("apps.orders.finance_urls")),
    # Unified customer notification centre (Phase 10).
    path("account/notifications/", include("apps.notifications.urls")),
    # Customer support centre (tickets, replies, attachments) (Phase 10).
    path("account/support/", include("apps.support.urls")),
    # Staff support dashboard (queue, assignment, status machine) (Phase 10).
    path("dashboard/support/", include("apps.support.dashboard_urls")),
    # Staff customer overview (read-only, capability-gated) (Phase 10).
    path("dashboard/customers/", include("apps.accounts.customer_dashboard_urls")),
    # Customer service portal (service requests, quotations, service payments).
    path("account/services/", include("apps.services.urls")),
    # Staff service dashboard (consultancy, farming, marketing, storage).
    path("dashboard/services/", include("apps.services.dashboard_urls")),
    # Customer export portal (enquiries, quotations, export orders, shipments).
    path("account/export/", include("apps.export.urls")),
    # Staff export dashboard (destinations, compliance, documents, shipments).
    path("dashboard/export/", include("apps.export.dashboard_urls")),
    # Public training academy (courses, sessions, certificate verification).
    path("training/", include("apps.training.urls")),
    # Student training portal (enrolments, progress, assessments, certificates).
    path("account/training/", include("apps.training.account_urls")),
    # Staff training dashboard (courses, sessions, attendance, certificates).
    path("dashboard/training/", include("apps.training.dashboard_urls")),
    # Legacy catalogue aliases kept stable for shared links (UI_UX_SPEC §5.2).
    path("states/", catalog_views.state_list, name="state_list"),
    path("states/<slug:slug>/", catalog_views.state_detail, name="state_detail"),
    path("states/<slug:state>/<slug:lga>/", catalog_views.lga_detail, name="lga_detail"),
    path("products/<slug:slug>/", catalog_views.product_detail, name="product_detail"),
    path("shop/<slug:slug>/", catalog_views.category_detail, name="category_detail_legacy"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

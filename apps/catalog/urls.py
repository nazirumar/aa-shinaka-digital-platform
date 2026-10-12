"""Public catalogue URLs (``/shop/...``).

Mounted at ``shop/`` by ``config.urls``; the legacy ``/states/`` and
``/products/<slug>/`` aliases in ``config.urls`` point at the same views so old
links keep working (see ``docs/UI_UX_SPEC.md`` §5.2). Reads only — writes go
through ``services``.
"""

from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.shop_index, name="shop_index"),
    path("categories/", views.category_list, name="category_list"),
    path("category/<slug:slug>/", views.category_detail, name="category_detail"),
    path("product/<slug:slug>/", views.product_detail, name="product_detail"),
    path("states/", views.state_list, name="state_list"),
    path("state/<slug:slug>/", views.state_detail, name="state_detail"),
    path("state/<slug:state>/<slug:lga>/", views.lga_detail, name="lga_detail"),
    path("search/", views.search, name="search"),
    path("compare/", views.compare, name="compare"),
    path("lga-options/", views.lga_options, name="lga_options"),
]

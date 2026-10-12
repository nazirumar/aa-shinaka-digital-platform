"""CMS management URLs (``/dashboard/cms/...``).

Mounted from ``config.urls`` under the staff dashboard prefix. Every view
enforces a CMS capability server-side.
"""

from django.urls import path

from . import dashboard_views as views

app_name = "cms_dashboard"

urlpatterns = [
    path("", views.CMSHomeView.as_view(), name="home"),
    path("settings/", views.SiteSettingView.as_view(), name="settings"),
    # Hero banners
    path("banners/", views.BannerListView.as_view(), name="banner_list"),
    path("banners/new/", views.BannerCreateView.as_view(), name="banner_create"),
    path("banners/<int:pk>/edit/", views.BannerUpdateView.as_view(), name="banner_edit"),
    path("banners/<int:pk>/delete/", views.BannerDeleteView.as_view(), name="banner_delete"),
    path("banners/<int:pk>/publish/", views.BannerPublishView.as_view(), name="banner_publish"),
    # Business divisions
    path("divisions/", views.DivisionListView.as_view(), name="division_list"),
    path("divisions/new/", views.DivisionCreateView.as_view(), name="division_create"),
    path("divisions/<int:pk>/edit/", views.DivisionUpdateView.as_view(), name="division_edit"),
    path("divisions/<int:pk>/delete/", views.DivisionDeleteView.as_view(), name="division_delete"),
    path(
        "divisions/<int:pk>/publish/",
        views.DivisionPublishView.as_view(),
        name="division_publish",
    ),
    # Service pages
    path("services/", views.ServiceListView.as_view(), name="service_list"),
    path("services/new/", views.ServiceCreateView.as_view(), name="service_create"),
    path("services/<int:pk>/edit/", views.ServiceUpdateView.as_view(), name="service_edit"),
    path("services/<int:pk>/delete/", views.ServiceDeleteView.as_view(), name="service_delete"),
    path("services/<int:pk>/publish/", views.ServicePublishView.as_view(), name="service_publish"),
    # Blog
    path("blog/categories/", views.BlogCategoryListView.as_view(), name="blog_category_list"),
    path(
        "blog/categories/new/",
        views.BlogCategoryCreateView.as_view(),
        name="blog_category_create",
    ),
    path(
        "blog/categories/<int:pk>/edit/",
        views.BlogCategoryUpdateView.as_view(),
        name="blog_category_edit",
    ),
    path(
        "blog/categories/<int:pk>/delete/",
        views.BlogCategoryDeleteView.as_view(),
        name="blog_category_delete",
    ),
    path("blog/posts/", views.BlogPostListView.as_view(), name="post_list"),
    path("blog/posts/new/", views.BlogPostCreateView.as_view(), name="post_create"),
    path("blog/posts/<int:pk>/edit/", views.BlogPostUpdateView.as_view(), name="post_edit"),
    path("blog/posts/<int:pk>/delete/", views.BlogPostDeleteView.as_view(), name="post_delete"),
    path("blog/posts/<int:pk>/publish/", views.PostPublishView.as_view(), name="post_publish"),
    # FAQs
    path("faqs/", views.FAQListView.as_view(), name="faq_list"),
    path("faqs/new/", views.FAQCreateView.as_view(), name="faq_create"),
    path("faqs/<int:pk>/edit/", views.FAQUpdateView.as_view(), name="faq_edit"),
    path("faqs/<int:pk>/delete/", views.FAQDeleteView.as_view(), name="faq_delete"),
    # Testimonials
    path("testimonials/", views.TestimonialListView.as_view(), name="testimonial_list"),
    path("testimonials/new/", views.TestimonialCreateView.as_view(), name="testimonial_create"),
    path(
        "testimonials/<int:pk>/edit/",
        views.TestimonialUpdateView.as_view(),
        name="testimonial_edit",
    ),
    path(
        "testimonials/<int:pk>/delete/",
        views.TestimonialDeleteView.as_view(),
        name="testimonial_delete",
    ),
    path(
        "testimonials/<int:pk>/decision/",
        views.TestimonialDecisionView.as_view(),
        name="testimonial_decision",
    ),
    # Team
    path("team/", views.TeamListView.as_view(), name="team_list"),
    path("team/new/", views.TeamCreateView.as_view(), name="team_create"),
    path("team/<int:pk>/edit/", views.TeamUpdateView.as_view(), name="team_edit"),
    path("team/<int:pk>/delete/", views.TeamDeleteView.as_view(), name="team_delete"),
    # Pages
    path("pages/", views.PageListView.as_view(), name="page_list"),
    path("pages/new/", views.PageCreateView.as_view(), name="page_create"),
    path("pages/<int:pk>/edit/", views.PageUpdateView.as_view(), name="page_edit"),
    path("pages/<int:pk>/delete/", views.PageDeleteView.as_view(), name="page_delete"),
    path("pages/<int:pk>/publish/", views.PagePublishView.as_view(), name="page_publish"),
    # Media
    path("media/", views.MediaListView.as_view(), name="media_list"),
    path("media/new/", views.MediaCreateView.as_view(), name="media_create"),
    path("media/<uuid:pk>/edit/", views.MediaUpdateView.as_view(), name="media_edit"),
    path("media/<uuid:pk>/delete/", views.MediaDeleteView.as_view(), name="media_delete"),
    # Navigation
    path("navigation/", views.NavigationListView.as_view(), name="nav_list"),
    path("navigation/new/", views.NavigationCreateView.as_view(), name="nav_create"),
    path("navigation/<int:pk>/edit/", views.NavigationUpdateView.as_view(), name="nav_edit"),
    path("navigation/<int:pk>/delete/", views.NavigationDeleteView.as_view(), name="nav_delete"),
    # Enquiries
    path("enquiries/", views.EnquiryListView.as_view(), name="enquiry_list"),
    path("enquiries/<int:pk>/", views.EnquiryDetailView.as_view(), name="enquiry_detail"),
    path("enquiries/<int:pk>/handle/", views.EnquiryHandleView.as_view(), name="enquiry_handle"),
]

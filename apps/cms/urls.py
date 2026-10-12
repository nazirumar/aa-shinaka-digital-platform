"""Public website URLs.

Mounted at the site root by ``config.urls`` alongside ``apps.core.urls``.
"""

from django.urls import path

from . import views

app_name = "cms"

urlpatterns = [
    path("services/", views.service_list, name="service_list"),
    path("services/<slug:slug>/", views.service_detail, name="service_detail"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("news/", views.blog_list, name="blog_list"),
    path("news/<slug:slug>/", views.blog_detail, name="blog_detail"),
    path("faqs/", views.faq_list, name="faq_list"),
    path("pages/<slug:slug>/", views.page_detail, name="page_detail"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
]

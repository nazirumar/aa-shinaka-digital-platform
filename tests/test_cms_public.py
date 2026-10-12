"""Phase 3 tests: public website (homepage, services, pages, blog, contact, SEO)."""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import translation

from apps.cms.models import BlogPost, PublishStatus, ServicePage

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_service(
    *, title="Export Services", status=PublishStatus.PUBLISHED, **kwargs
) -> ServicePage:
    return ServicePage.objects.create(
        title=title,
        status=status,
        published_at=None,
        intro=kwargs.pop("intro", "We export Nigerian agricultural produce."),
        **kwargs,
    )


def make_post(*, title="Harvest update", status=PublishStatus.PUBLISHED, **kwargs) -> BlogPost:
    return BlogPost.objects.create(
        title=title,
        status=status,
        published_at=None,
        excerpt=kwargs.pop("excerpt", "A short field report."),
        body=kwargs.pop("body", "<p>Full article body.</p>"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Homepage
# ---------------------------------------------------------------------------


def test_homepage_renders_brand_and_all_divisions(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    assert b"AA Shinaka" in response.content
    for label in (
        b"Agricultural Consultancy",
        b"Farming Services",
        b"Agricultural Marketing",
        b"Storage and Warehousing",
        b"Agricultural Export",
        b"Agricultural Product Sales",
        b"Training and Academy",
    ):
        assert label in response.content
    # Oil and gas is explicitly out of scope.
    assert b"Oil and Gas" not in response.content


def test_homepage_has_responsive_viewport_and_skip_link(client):
    response = client.get(reverse("core:home"))
    content = response.content

    assert b'name="viewport"' in content
    # Responsive breakpoint classes must be present for the mobile/desktop layout.
    assert b"lg:hidden" in content
    assert b"lg:flex" in content
    # Accessibility: skip-to-content link.
    assert b'href="#main"' in content


def test_homepage_shows_product_empty_states_when_catalogue_absent(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    # Catalogue ships in a later phase, so previews must degrade gracefully.
    assert b"catalogue is live" in response.content or b"on the way" in response.content


def test_fallback_navigation_links_are_present(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    for url in (
        reverse("cms:service_list"),
        reverse("cms:about"),
        reverse("cms:blog_list"),
        reverse("cms:faq_list"),
        reverse("cms:contact"),
    ):
        assert url.encode() in response.content


# ---------------------------------------------------------------------------
# Service pages
# ---------------------------------------------------------------------------


def test_service_list_shows_only_published(client):
    published = make_service(title="Consultancy")
    make_service(title="Secret Draft", status=PublishStatus.DRAFT)

    response = client.get(reverse("cms:service_list"))

    assert response.status_code == 200
    assert published.title.encode() in response.content
    assert b"Secret Draft" not in response.content


def test_service_detail_renders_benefits_and_faqs(client):
    service = make_service(
        title="Storage and Warehousing",
        intro="Clean, secure storage for your harvest.",
        benefits=["Reduced post-harvest loss", "Temperature-aware handling"],
        steps=["Book capacity", "Deliver produce", "Collect on schedule"],
        meta_title="Storage services",
        meta_description="Secure agricultural storage.",
    )

    response = client.get(service.get_absolute_url())

    assert response.status_code == 200
    assert b"Storage and Warehousing" in response.content
    assert b"Reduced post-harvest loss" in response.content
    assert b"Book capacity" in response.content


def test_draft_service_is_not_reachable_publicly(client):
    draft = make_service(title="Hidden", status=PublishStatus.DRAFT)

    response = client.get(draft.get_absolute_url())

    assert response.status_code == 404


def test_unknown_service_slug_returns_404(client):
    response = client.get(reverse("cms:service_detail", kwargs={"slug": "does-not-exist"}))

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------


def test_blog_list_and_detail_render_published_posts(client):
    post = make_post(title="Onion price trends", body="<p>Prices rose this quarter.</p>")

    list_response = client.get(reverse("cms:blog_list"))
    detail_response = client.get(post.get_absolute_url())

    assert list_response.status_code == 200
    assert b"Onion price trends" in list_response.content
    assert detail_response.status_code == 200
    assert b"Prices rose this quarter." in detail_response.content


def test_draft_blog_post_hidden_and_404(client):
    draft = make_post(title="Unfinished", status=PublishStatus.DRAFT)

    assert b"Unfinished" not in client.get(reverse("cms:blog_list")).content
    assert client.get(draft.get_absolute_url()).status_code == 404


def test_blog_list_htmx_returns_partial(client):
    make_post(title="Partial post")

    response = client.get(reverse("cms:blog_list"), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    # The partial has no full document wrapper.
    assert b"<html" not in response.content
    assert b"Partial post" in response.content


# ---------------------------------------------------------------------------
# FAQs, About
# ---------------------------------------------------------------------------


def test_faq_list_renders(client):
    response = client.get(reverse("cms:faq_list"))

    assert response.status_code == 200
    assert b"Frequently asked questions" in response.content


def test_about_page_renders(client):
    response = client.get(reverse("cms:about"))

    assert response.status_code == 200
    assert b"About AA Shinaka" in response.content


# ---------------------------------------------------------------------------
# Contact form
# ---------------------------------------------------------------------------


def test_contact_form_stores_valid_enquiry(client):
    from apps.cms.models import ContactEnquiry

    response = client.post(
        reverse("cms:contact"),
        {
            "name": "Musa Ibrahim",
            "email": "Musa@Example.com",
            "phone": "08030000000",
            "subject": "Bulk onions",
            "division": "marketing",
            "message": "Please share wholesale pricing for red onions.",
            "website": "",
        },
    )

    assert response.status_code == 302
    enquiry = ContactEnquiry.objects.get()
    assert enquiry.email == "musa@example.com"  # normalised to lower case
    assert enquiry.division == "marketing"
    assert enquiry.is_handled is False


def test_contact_honeypot_rejects_bots(client):
    from apps.cms.models import ContactEnquiry

    response = client.post(
        reverse("cms:contact"),
        {
            "name": "Spam Bot",
            "email": "bot@example.com",
            "message": "Buy cheap stuff",
            "website": "http://spam.example.com",
        },
    )

    assert response.status_code == 200  # re-rendered with errors, not stored
    assert ContactEnquiry.objects.count() == 0


def test_contact_form_requires_name_email_and_message(client):
    response = client.post(reverse("cms:contact"), {"name": "", "email": "", "message": ""})

    assert response.status_code == 200
    assert response.context["form"].errors
    assert {"name", "email", "message"} <= set(response.context["form"].errors)


def test_contact_success_flag_renders_confirmation(client):
    response = client.get(reverse("cms:contact"), {"sent": "1"})

    assert response.status_code == 200
    assert response.context["sent"] is True


# ---------------------------------------------------------------------------
# SEO
# ---------------------------------------------------------------------------


def test_service_detail_has_seo_metadata(client):
    service = make_service(
        title="Farming Services",
        meta_title="Professional farming services",
        meta_description="Mechanised land preparation and agronomy support.",
    )

    response = client.get(service.get_absolute_url())
    content = response.content

    assert b"<title>" in content
    assert b"Professional farming services" in content
    assert b'name="description"' in content
    assert b"Mechanised land preparation" in content
    assert b'rel="canonical"' in content
    assert b'property="og:title"' in content


def test_sitemap_lists_published_and_excludes_drafts(client):
    published = make_service(title="Visible Service")
    draft = make_service(title="Draft Service", status=PublishStatus.DRAFT)

    response = client.get(reverse("sitemap"))

    assert response.status_code == 200
    assert b"application/xml" in response["Content-Type"].encode()
    assert published.get_absolute_url().encode() in response.content
    assert draft.get_absolute_url().encode() not in response.content


def test_robots_txt_disallows_private_areas(client):
    response = client.get(reverse("cms:robots_txt"))

    assert response.status_code == 200
    body = response.content
    assert b"Disallow: /dashboard/" in body
    assert b"Sitemap:" in body


# ---------------------------------------------------------------------------
# i18n readiness (Hausa catalogue)
# ---------------------------------------------------------------------------


def test_hausa_catalogue_translates_core_labels():
    with translation.override("ha"):
        assert translation.gettext("Services") == "Ayyuka"
        assert translation.gettext("Home") == "Gida"
        assert translation.gettext("Contact") == "Tuntuɓe mu"


def test_set_language_endpoint_switches_to_hausa(client):
    response = client.post(
        reverse("set_language"),
        {"language": "ha", "next": "/"},
    )

    assert response.status_code == 302
    assert "django_language" in response.cookies or "django_language" in client.cookies

    home = client.get(reverse("core:home"))
    assert b"Ayyuka" in home.content


def test_untranslated_strings_fall_back_to_english(client):
    with translation.override("ha"):
        # Not present in the Hausa catalogue, so it stays English.
        assert translation.gettext("A string absent from the Hausa catalogue") == (
            "A string absent from the Hausa catalogue"
        )

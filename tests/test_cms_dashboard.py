"""Phase 3 tests: CMS dashboard permissions, publishing and enquiry handling."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import User, UserRole
from apps.accounts.roles import sync_user_groups
from apps.cms.models import BlogCategory, ContactEnquiry, PublishStatus, ServicePage
from apps.cms.models import Testimonial as TestimonialModel

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def content_editor(db) -> User:
    user = User.objects.create_user(
        email="editor@example.com",
        password="test-pass-12345",
        first_name="Efe",
        last_name="Ojo",
        role=UserRole.CONTENT_EDITOR,
        is_staff=True,
    )
    sync_user_groups(user)
    return user


@pytest.fixture
def draft_service(db) -> ServicePage:
    return ServicePage.objects.create(
        title="Draft storage service",
        status=PublishStatus.DRAFT,
        published_at=None,
        intro="Not yet visible.",
    )


@pytest.fixture
def pending_testimonial(db) -> TestimonialModel:
    return TestimonialModel.objects.create(
        author_name="Hauwa Sani",
        quote="AA Shinaka transformed how we sell our grain.",
        is_approved=False,
    )


def _login(client, user) -> None:
    assert client.login(email=user.email, password="test-pass-12345")


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_content_editor_can_reach_cms_dashboard(client, content_editor):
    _login(client, content_editor)

    response = client.get(reverse("cms_dashboard:home"))

    assert response.status_code == 200
    assert response.context["counts"]["services_draft"] == 0


def test_customer_cannot_reach_cms_dashboard(client, customer):
    _login(client, customer)

    response = client.get(reverse("cms_dashboard:home"))

    assert response.status_code == 403


def test_anonymous_user_redirected_to_login(client):
    response = client.get(reverse("cms_dashboard:home"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_sales_officer_without_content_capability_is_forbidden(client, staff_user):
    # SALES_OFFICER has contact.manage but not content.manage.
    _login(client, staff_user)

    assert client.get(reverse("cms_dashboard:home")).status_code == 403
    assert client.get(reverse("cms_dashboard:service_list")).status_code == 403


def test_sales_officer_can_manage_enquiries_but_not_content(client, staff_user):
    _login(client, staff_user)

    assert client.get(reverse("cms_dashboard:enquiry_list")).status_code == 200
    assert client.get(reverse("cms_dashboard:service_edit", args=[1])).status_code == 403


def test_content_editor_cannot_access_site_settings(client, content_editor):
    # CONTENT_EDITOR lacks site.config.
    _login(client, content_editor)

    assert client.get(reverse("cms_dashboard:settings")).status_code == 403


def test_owner_can_access_site_settings(client, owner):
    _login(client, owner)

    assert client.get(reverse("cms_dashboard:settings")).status_code == 200


def test_owner_can_reach_cms_dashboard(client, owner):
    _login(client, owner)

    response = client.get(reverse("cms_dashboard:home"))

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def test_publish_toggle_makes_draft_public(client, content_editor, draft_service):
    _login(client, content_editor)

    assert client.get(draft_service.get_absolute_url()).status_code == 404

    response = client.post(
        reverse("cms_dashboard:service_publish", args=[draft_service.pk]),
        {"status": "published"},
    )

    assert response.status_code == 302
    draft_service.refresh_from_db()
    assert draft_service.status == PublishStatus.PUBLISHED
    assert draft_service.published_at is not None
    assert client.get(draft_service.get_absolute_url()).status_code == 200


def test_unpublish_hides_content_again(client, content_editor):
    service = ServicePage.objects.create(
        title="Temporary", status=PublishStatus.PUBLISHED, published_at=None
    )
    _login(client, content_editor)

    assert client.get(service.get_absolute_url()).status_code == 200

    client.post(
        reverse("cms_dashboard:service_publish", args=[service.pk]),
        {"status": "draft"},
    )

    service.refresh_from_db()
    assert service.status == PublishStatus.DRAFT
    assert client.get(service.get_absolute_url()).status_code == 404


def test_invalid_status_value_does_not_error(client, content_editor, draft_service):
    _login(client, content_editor)

    response = client.post(
        reverse("cms_dashboard:service_publish", args=[draft_service.pk]),
        {"status": "definitely-not-a-status"},
    )

    assert response.status_code == 302
    draft_service.refresh_from_db()
    assert draft_service.status == PublishStatus.PUBLISHED


def test_sales_officer_cannot_publish(client, staff_user, draft_service):
    _login(client, staff_user)

    response = client.post(
        reverse("cms_dashboard:service_publish", args=[draft_service.pk]),
        {"status": "published"},
    )

    assert response.status_code == 403
    draft_service.refresh_from_db()
    assert draft_service.status == PublishStatus.DRAFT


# ---------------------------------------------------------------------------
# Testimonials
# ---------------------------------------------------------------------------


def test_approve_testimonial_flow(client, content_editor, pending_testimonial):
    _login(client, content_editor)

    response = client.post(
        reverse("cms_dashboard:testimonial_decision", args=[pending_testimonial.pk]),
        {"action": "approve"},
    )

    assert response.status_code == 302
    pending_testimonial.refresh_from_db()
    assert pending_testimonial.is_approved is True
    assert pending_testimonial.approved_by == content_editor


def test_pending_testimonial_hidden_from_homepage(client, pending_testimonial):
    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    assert b"AA Shinaka transformed how we sell our grain." not in response.content


def test_approved_testimonial_appears_on_homepage(client, content_editor, pending_testimonial):
    _login(client, content_editor)
    client.post(
        reverse("cms_dashboard:testimonial_decision", args=[pending_testimonial.pk]),
        {"action": "approve"},
    )
    client.logout()

    response = client.get(reverse("core:home"))

    assert b"AA Shinaka transformed how we sell our grain." in response.content


# ---------------------------------------------------------------------------
# Content creation through the dashboard
# ---------------------------------------------------------------------------


def test_content_editor_can_create_blog_category(client, content_editor):
    _login(client, content_editor)

    response = client.post(
        reverse("cms_dashboard:blog_category_create"),
        {"name": "Market reports", "description": "Weekly prices."},
    )

    assert response.status_code == 302
    assert BlogCategory.objects.filter(name="Market reports").exists()


def test_content_editor_can_create_service_page_with_category(client, content_editor):
    _login(client, content_editor)

    data = {
        "division": "",
        "title": "Irrigation advisory",
        "eyebrow": "",
        "intro": "Plan and install efficient irrigation.",
        "body": "",
        "hero_image": "",
        "icon": "",
        "benefits": "Save water\nImprove yields",
        "steps": "Assess farm\nDesign system",
        "cta_label": "Send an enquiry",
        "cta_url": "",
        "status": "draft",
        "published_at": "",
        "is_featured": "",
        "sort_order": "0",
        "meta_title": "",
        "meta_description": "",
        "canonical_url": "",
        "og_image": "",
        "noindex": "",
        "categories-TOTAL_FORMS": "1",
        "categories-INITIAL_FORMS": "0",
        "categories-MIN_NUM_FORMS": "0",
        "categories-MAX_NUM_FORMS": "1000",
        "categories-0-name": "Drip systems",
        "categories-0-description": "",
        "categories-0-icon": "",
        "categories-0-sort_order": "0",
    }

    response = client.post(reverse("cms_dashboard:service_create"), data)

    assert response.status_code == 302
    service = ServicePage.objects.get(title="Irrigation advisory")
    assert service.benefits == ["Save water", "Improve yields"]
    assert list(service.categories.values_list("name", flat=True)) == ["Drip systems"]


# ---------------------------------------------------------------------------
# Enquiries
# ---------------------------------------------------------------------------


def test_enquiry_handling_marks_handled(client, staff_user):
    enquiry = ContactEnquiry.objects.create(
        name="Grace", email="grace@example.com", message="Storage enquiry."
    )
    _login(client, staff_user)

    assert client.get(reverse("cms_dashboard:enquiry_list")).status_code == 200

    response = client.post(reverse("cms_dashboard:enquiry_handle", args=[enquiry.pk]))

    assert response.status_code == 302
    enquiry.refresh_from_db()
    assert enquiry.is_handled is True
    assert enquiry.handled_by == staff_user


def test_customer_cannot_view_enquiries(client, customer):
    _login(client, customer)

    assert client.get(reverse("cms_dashboard:enquiry_list")).status_code == 403

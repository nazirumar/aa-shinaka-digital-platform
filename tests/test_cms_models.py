"""Phase 3 tests: CMS models, publication rules, slugs and image validation."""

from __future__ import annotations

from datetime import timedelta
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.cms.forms import MediaAssetForm
from apps.cms.models import MediaAsset, PublishStatus, ServicePage, SiteSetting
from apps.cms.services import set_publish_status

pytestmark = pytest.mark.django_db


def _png_bytes() -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Slug behaviour
# ---------------------------------------------------------------------------


def test_slug_is_generated_from_title():
    service = ServicePage.objects.create(
        title="Storage and Warehousing", status=PublishStatus.DRAFT
    )

    assert service.slug == "storage-and-warehousing"


def test_slug_collisions_are_suffixed():
    first = ServicePage.objects.create(title="Export Services", status=PublishStatus.DRAFT)
    second = ServicePage.objects.create(title="Export Services", status=PublishStatus.DRAFT)

    assert first.slug == "export-services"
    assert second.slug == "export-services-2"


def test_explicit_slug_is_respected():
    service = ServicePage.objects.create(
        title="Marketing", slug="agri-marketing", status=PublishStatus.DRAFT
    )

    assert service.slug == "agri-marketing"


# ---------------------------------------------------------------------------
# Publication rules
# ---------------------------------------------------------------------------


def test_published_queryset_excludes_drafts_and_future_dates():
    past = ServicePage.objects.create(
        title="Published in past",
        status=PublishStatus.PUBLISHED,
        published_at=timezone.now() - timedelta(days=1),
    )
    future = ServicePage.objects.create(
        title="Scheduled later",
        status=PublishStatus.PUBLISHED,
        published_at=timezone.now() + timedelta(days=1),
    )
    draft = ServicePage.objects.create(title="Still a draft", status=PublishStatus.DRAFT)

    visible = set(ServicePage.objects.published().values_list("pk", flat=True))

    assert past.pk in visible
    assert future.pk not in visible
    assert draft.pk not in visible


def test_published_at_none_with_published_status_is_visible():
    service = ServicePage.objects.create(
        title="Immediate", status=PublishStatus.PUBLISHED, published_at=None
    )

    assert ServicePage.objects.published().filter(pk=service.pk).exists()


def test_set_publish_status_stamps_published_at(owner):
    service = ServicePage.objects.create(title="Draft", status=PublishStatus.DRAFT)

    set_publish_status(service, status=PublishStatus.PUBLISHED, actor=owner)

    service.refresh_from_db()
    assert service.status == PublishStatus.PUBLISHED
    assert service.published_at is not None


def test_set_publish_status_rejects_unknown_status(owner):
    service = ServicePage.objects.create(title="Draft", status=PublishStatus.DRAFT)

    with pytest.raises(ValueError):
        set_publish_status(service, status="nonsense", actor=owner)


def test_archived_content_is_not_published():
    archived = ServicePage.objects.create(
        title="Old page", status=PublishStatus.PUBLISHED, published_at=None
    )
    archived.status = PublishStatus.ARCHIVED
    archived.save(update_fields=["status"])

    assert not ServicePage.objects.published().filter(pk=archived.pk).exists()


# ---------------------------------------------------------------------------
# Image validation
# ---------------------------------------------------------------------------


def test_media_form_rejects_disallowed_extension():
    form = MediaAssetForm(
        files={"file": SimpleUploadedFile("malware.exe", b"definitely not an image")},
        data={"title": "Bad", "alt_text": "Bad file"},
    )

    assert not form.is_valid()
    assert "file" in form.errors


def test_media_form_rejects_non_image_content():
    form = MediaAssetForm(
        files={
            "file": SimpleUploadedFile("photo.png", b"not really a png", content_type="image/png")
        },
        data={"title": "Fake", "alt_text": "Not an image"},
    )

    assert not form.is_valid()
    assert "file" in form.errors


def test_media_form_accepts_valid_png():
    form = MediaAssetForm(
        files={"file": SimpleUploadedFile("onions.png", _png_bytes(), content_type="image/png")},
        data={"title": "Onions", "alt_text": "Red onions in a woven basket"},
    )

    assert form.is_valid(), form.errors


def test_media_asset_model_validators_reject_bad_file():
    asset = MediaAsset(
        file=SimpleUploadedFile("notes.txt", b"hello"),
        title="Notes",
        alt_text="A text file",
    )

    with pytest.raises(ValidationError):
        asset.full_clean()


# ---------------------------------------------------------------------------
# Site settings singleton
# ---------------------------------------------------------------------------


def test_site_settings_is_a_singleton():
    first = SiteSetting.load()
    second = SiteSetting.load()

    assert first.pk == second.pk == 1
    assert SiteSetting.objects.count() == 1


def test_site_settings_whatsapp_url_normalises_number():
    site = SiteSetting.load()
    site.whatsapp_number = "+234 803 000 0000"
    site.save()

    assert site.whatsapp_url.startswith("https://wa.me/2348030000000")

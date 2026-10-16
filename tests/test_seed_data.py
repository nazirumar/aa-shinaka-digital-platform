"""Tests for the safe baseline + representative development data command."""

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.accounts.models import User, UserRole
from apps.accounts.roles import role_group_name
from apps.cms.models import BlogCategory, BlogPost, Page, PublishStatus, SiteSetting
from apps.locations.models import LGA, Country, State
from apps.services.models import ConsultancyService
from apps.training.models import Course, TrainingCategory

pytestmark = pytest.mark.django_db

SEED_EMAILS = [
    "owner@aashinaka.example",
    "admin@aashinaka.example",
    "sales@aashinaka.example",
    "inventory@aashinaka.example",
    "consultant@aashinaka.example",
    "training@aashinaka.example",
    "export@aashinaka.example",
    "finance@aashinaka.example",
    "content@aashinaka.example",
    "customer1@aashinaka.example",
    "customer2@aashinaka.example",
    "customer3@aashinaka.example",
]


def test_seed_data_is_idempotent(settings):
    settings.DEBUG = True
    call_command("seed_data", "--no-images")
    post = BlogPost.objects.get(slug="seed-example-harvest-records")
    post.status = PublishStatus.PUBLISHED
    post.body = "<p>Reviewed by staff.</p>"
    post.save(update_fields=["status", "body"])

    call_command("seed_data", "--no-images")

    assert Country.objects.filter(code="NG", name="Nigeria").exists()
    assert SiteSetting.objects.filter(pk=1).count() == 1
    assert Group.objects.filter(
        name__in=[role_group_name(role) for role in UserRole.values]
    ).count() == len(UserRole.values)
    assert BlogCategory.objects.filter(slug="seed-example-articles").count() == 1
    assert BlogPost.objects.filter(slug__startswith="seed-example-").count() == 3
    post.refresh_from_db()
    assert post.status == PublishStatus.PUBLISHED
    assert post.body == "<p>Reviewed by staff.</p>"
    assert BlogPost.objects.filter(noindex=True, status=PublishStatus.DRAFT).count() == 2
    customer = User.objects.get(email="seed.customer@example.invalid")
    assert not customer.is_active
    assert not customer.has_usable_password()
    page = Page.objects.get(slug="seed-example-page")
    assert page.status == PublishStatus.DRAFT
    assert page.noindex
    assert not ConsultancyService.objects.get(slug="seed-example-consultancy-service").is_active
    assert TrainingCategory.objects.filter(slug="seed-example-courses").exists()
    course = Course.objects.get(slug="seed-example-agricultural-business-fundamentals")
    assert course.status == "draft"
    assert not course.is_featured


def test_seed_data_creates_locations_and_users(settings):
    settings.DEBUG = True
    call_command("seed_data", "--no-images")

    assert State.objects.count() >= 37
    assert LGA.objects.count() > 0
    for email in SEED_EMAILS:
        assert User.objects.filter(email=email).exists(), f"missing user {email}"
    owner = User.objects.get(email="owner@aashinaka.example")
    assert owner.is_superuser
    customer1 = User.objects.get(email="customer1@aashinaka.example")
    assert customer1.addresses.filter(is_default=True).exists()


def test_seed_data_creates_catalogue(settings):
    settings.DEBUG = True
    call_command("seed_data", "--no-images")

    from apps.catalog.models import (
        Category,
        ListingStatus,
        Product,
        ProductListing,
        PublishStatus,
        Warehouse,
    )

    assert Category.all_objects.count() > 0
    assert Product.all_objects.count() >= 15
    published = Product.all_objects.filter(status=PublishStatus.PUBLISHED).count()
    assert published >= 10
    active_listings = ProductListing.objects.filter(status=ListingStatus.ACTIVE).count()
    assert active_listings >= 10
    assert Warehouse.objects.count() == 4


def test_seed_data_creates_content_and_services(settings):
    settings.DEBUG = True
    call_command("seed_data", "--no-images")

    from apps.cms.models import (
        FAQ,
        BusinessDivision,
        HeroBanner,
        NavigationItem,
        ServicePage,
        TeamMember,
        Testimonial,
    )

    assert SiteSetting.load().site_name == "AA Shinaka"
    assert NavigationItem.objects.count() >= 10
    assert Page.objects.filter(slug="about").exists()
    assert Page.objects.filter(slug="contact").exists()
    assert HeroBanner.objects.count() >= 3
    assert BusinessDivision.objects.count() == 6
    assert ServicePage.objects.count() == 5
    assert FAQ.objects.count() >= 8
    assert Testimonial.objects.count() >= 3
    assert TeamMember.objects.count() >= 3

    from apps.services.models import (
        FarmingService,
        MarketingService,
        ProduceType,
        StorageFacility,
    )

    assert ConsultancyService.objects.count() >= 4
    assert FarmingService.objects.count() >= 3
    assert MarketingService.objects.count() >= 2
    assert ProduceType.objects.count() >= 5
    assert StorageFacility.objects.count() >= 1

    from apps.training.models import (
        CertificateTemplate,
        TrainingSession,
        TrainingVenue,
    )

    assert TrainingCategory.objects.count() >= 6
    assert Course.objects.count() >= 5
    assert TrainingVenue.objects.count() >= 2
    assert TrainingSession.objects.count() >= 3
    assert CertificateTemplate.objects.exists()

    from apps.export.models import (
        ExportDestination,
        ExportDocumentType,
        ExportProductProfile,
        LogisticsProvider,
    )

    assert ExportDocumentType.objects.count() >= 5
    assert ExportDestination.objects.count() >= 4
    assert ExportProductProfile.objects.count() >= 3
    assert LogisticsProvider.objects.count() >= 2

    from apps.orders.models import ShippingMethod, ShippingRate, ShippingZone

    assert ShippingZone.objects.count() >= 6
    assert ShippingMethod.objects.count() == 3
    assert ShippingRate.objects.count() >= 10


def test_seed_data_dry_run_does_not_write(capsys, settings):
    settings.DEBUG = True
    Group.objects.filter(name__in=[role_group_name(role) for role in UserRole.values]).delete()
    Country.objects.filter(code="NG").delete()
    SiteSetting.objects.all().delete()
    User.objects.filter(email="seed.customer@example.invalid").delete()
    Page.objects.filter(slug="seed-example-page").delete()
    BlogPost.objects.filter(slug__startswith="seed-example-").delete()
    BlogCategory.objects.filter(slug="seed-example-articles").delete()
    ConsultancyService.objects.filter(slug="seed-example-consultancy-service").delete()
    Course.objects.filter(slug="seed-example-agricultural-business-fundamentals").delete()
    TrainingCategory.objects.filter(slug="seed-example-courses").delete()

    call_command("seed_data", "--dry-run", "--no-images")

    assert not Country.objects.filter(code="NG").exists()
    assert not SiteSetting.objects.exists()
    assert not Group.objects.filter(
        name__in=[role_group_name(role) for role in UserRole.values]
    ).exists()
    assert not BlogCategory.objects.filter(slug="seed-example-articles").exists()
    assert not BlogPost.objects.filter(slug__startswith="seed-example-").exists()
    assert not User.objects.filter(email="seed.customer@example.invalid").exists()
    assert not Page.objects.filter(slug="seed-example-page").exists()
    assert not ConsultancyService.objects.filter(slug="seed-example-consultancy-service").exists()
    assert not TrainingCategory.objects.filter(slug="seed-example-courses").exists()
    assert not Course.objects.filter(
        slug="seed-example-agricultural-business-fundamentals"
    ).exists()
    assert "Dry run: no changes written." in capsys.readouterr().out


@override_settings(DEBUG=False)
def test_seed_data_refuses_to_run_outside_development():
    with pytest.raises(CommandError, match="development-only"):
        call_command("seed_data")

"""Website content models for the public site and the staff CMS.

This app owns the editable, public-facing marketing content: the homepage
banners, the business service pages, blog posts, FAQs, testimonials, editable
pages, site configuration, navigation and uploaded media. It deliberately does
**not** define catalogue/product models — those belong to ``apps.catalog`` and
arrive in a later phase; the homepage reads them defensively (see
``selectors.featured_products``) so no conflicting catalogue model is created.

Design notes
------------
* ``SEOModel`` adds per-record SEO metadata (title, description, canonical,
  Open Graph image, ``noindex``).
* ``PublishableModel`` adds the draft / published / archived workflow with a
  publication timestamp and display ordering.
* A custom ``ContentQuerySet`` exposes ``.published()`` so public selectors never
  leak drafts, while the CMS dashboard uses the default queryset (everything).
* Money is never stored here; there is no price or stock data in this app.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import TimeStampedModel

# ---------------------------------------------------------------------------
# Shared choices / validators
# ---------------------------------------------------------------------------

ALLOWED_IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "gif"]
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


def validate_image_size(value) -> None:
    """Reject uploads larger than ``MAX_IMAGE_BYTES`` before they reach storage."""
    if value.size > MAX_IMAGE_BYTES:
        raise ValidationError("Images must be 5 MB or smaller.")


class PublishStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class Placement(models.TextChoices):
    HEADER = "header", "Header"
    FOOTER = "footer", "Footer"


class PageType(models.TextChoices):
    ABOUT = "about", "About"
    CONTACT = "contact", "Contact"
    TERMS = "terms", "Terms of Service"
    PRIVACY = "privacy", "Privacy Policy"
    CUSTOM = "custom", "Custom page"


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


class ContentQuerySet(models.QuerySet):
    """QuerySet with a ``published()`` filter that honours the schedule."""

    def published(self) -> ContentQuerySet:
        now = timezone.now()
        return self.filter(status=PublishStatus.PUBLISHED).filter(
            models.Q(published_at__isnull=True) | models.Q(published_at__lte=now)
        )

    def featured(self) -> ContentQuerySet:
        return self.filter(is_featured=True)


class SluggedModel(models.Model):
    """Abstract base that fills ``slug`` from a source field when left blank."""

    slug_source_field: ClassVar[str] = "title"

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self._ensure_slug()
        return super().save(*args, **kwargs)

    def _ensure_slug(self) -> None:
        source = getattr(self, self.slug_source_field, "") or ""
        if not self.slug and source:
            base = slugify(source)[:200] or "item"
            candidate = base
            model = type(self)
            suffix = 2
            while model.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{suffix}"
                suffix += 1
            self.slug = candidate


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------


class MediaAsset(TimeStampedModel):
    """An uploaded, reusable image with accessible alt text."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.ImageField(
        upload_to="cms/%Y/%m/",
        validators=[
            FileExtensionValidator(ALLOWED_IMAGE_EXTENSIONS),
            validate_image_size,
        ],
    )
    title = models.CharField(max_length=200, blank=True)
    alt_text = models.CharField(
        max_length=255,
        blank=True,
        help_text="Describe the image for screen readers and search engines.",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="media_assets",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.title or (self.file.name.rsplit("/", 1)[-1] if self.file else "Media")


# ---------------------------------------------------------------------------
# Abstract content bases
# ---------------------------------------------------------------------------


class SEOModel(TimeStampedModel):
    """Adds search / social metadata to a content record."""

    meta_title = models.CharField(
        max_length=70,
        blank=True,
        help_text="Overrides the page title in search results (≈60 characters).",
    )
    meta_description = models.CharField(
        max_length=320,
        blank=True,
        help_text="Summary shown in search results (≈155 characters).",
    )
    canonical_url = models.URLField(
        blank=True, help_text="Optional canonical override; leave blank to use the page URL."
    )
    og_image = models.ForeignKey(
        MediaAsset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Image used when the page is shared on social media.",
    )
    noindex = models.BooleanField(
        default=False, help_text="Ask search engines not to index this content."
    )

    class Meta:
        abstract = True


class PublishableModel(SluggedModel, SEOModel):
    """Draft / published / archived workflow plus display ordering."""

    slug = models.SlugField(max_length=200, unique=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PublishStatus.choices,
        default=PublishStatus.DRAFT,
        db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    is_featured = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0, db_index=True)

    objects = ContentQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ("sort_order", "-published_at", "-created_at")

    @property
    def is_live(self) -> bool:
        if self.status != PublishStatus.PUBLISHED:
            return False
        return self.published_at is None or self.published_at <= timezone.now()

    def publish(self, when=None) -> None:
        self.status = PublishStatus.PUBLISHED
        self.published_at = when or timezone.now()


# ---------------------------------------------------------------------------
# Site configuration & navigation
# ---------------------------------------------------------------------------


class SiteSetting(TimeStampedModel):
    """Singleton holding company identity, contact details and footer config.

    Contact details are intentionally blank by default: the platform must never
    invent phone numbers, addresses or social accounts. Staff fill them in via
    the CMS with verified information.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    site_name = models.CharField(max_length=120, default="AA Shinaka")
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)

    announcement_text = models.CharField(max_length=300, blank=True)
    announcement_url = models.URLField(blank=True)
    announcement_active = models.BooleanField(default=False)

    phone = models.CharField(max_length=40, blank=True)
    phone_secondary = models.CharField(max_length=40, blank=True)
    whatsapp_number = models.CharField(
        max_length=40,
        blank=True,
        help_text="International format, digits only, e.g. 2348012345678.",
    )
    email = models.EmailField(blank=True)

    address_line = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.ForeignKey(
        "locations.State", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    country = models.CharField(max_length=80, default="Nigeria")
    map_embed_url = models.URLField(blank=True)

    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)

    logo = models.ForeignKey(
        MediaAsset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Upload the official AA Shinaka logo. Never substitute a placeholder.",
    )
    favicon = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    default_meta_title = models.CharField(max_length=70, blank=True)
    default_meta_description = models.CharField(max_length=320, blank=True)

    # Editable "Why choose us" value propositions: [{"title": ..., "body": ...}].
    value_props = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def __str__(self) -> str:
        return self.site_name

    @classmethod
    def load(cls) -> SiteSetting:
        """Return the singleton row, creating it on first use."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def address_display(self) -> str:
        parts = [self.address_line, self.city, self.state.name if self.state else "", self.country]
        return ", ".join(part for part in parts if part)

    @property
    def whatsapp_url(self) -> str:
        if not self.whatsapp_number:
            return ""
        digits = "".join(ch for ch in self.whatsapp_number if ch.isdigit())
        return f"https://wa.me/{digits}" if digits else ""

    @property
    def social_links(self) -> list[dict[str, str]]:
        pairs = [
            ("Facebook", self.facebook_url),
            ("Instagram", self.instagram_url),
            ("X", self.twitter_url),
            ("LinkedIn", self.linkedin_url),
            ("YouTube", self.youtube_url),
        ]
        return [{"label": label, "url": url} for label, url in pairs if url]


class NavigationItem(TimeStampedModel):
    """A header or footer navigation link, optionally nested under a parent."""

    label = models.CharField(max_length=80)
    url_name = models.CharField(
        max_length=120, blank=True, help_text="Django URL name, e.g. cms:service_list."
    )
    url = models.CharField(max_length=300, blank=True, help_text="External or literal URL.")
    page = models.ForeignKey(
        "cms.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="nav_items"
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    placement = models.CharField(max_length=10, choices=Placement.choices, default=Placement.HEADER)
    sort_order = models.IntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True)
    opens_new_tab = models.BooleanField(default=False)

    class Meta:
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return self.label

    def resolve_url(self) -> str:
        """Best-effort URL resolution: page → named route → literal URL → ``#``."""
        if self.page_id and self.page:
            return self.page.get_absolute_url()
        if self.url_name:
            try:
                return reverse(self.url_name)
            except NoReverseMatch:
                return "#"
        return self.url or "#"


# ---------------------------------------------------------------------------
# Pages & homepage banners
# ---------------------------------------------------------------------------


class Page(PublishableModel):
    """A general CMS page (About, Terms, Privacy, or a custom landing page)."""

    page_type = models.CharField(max_length=20, choices=PageType.choices, default=PageType.CUSTOM)
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=300, blank=True)
    body = models.TextField(
        blank=True,
        help_text="Page body. Basic HTML authored by staff is allowed and rendered as-is.",
    )
    hero_image = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Page"
        verbose_name_plural = "Pages"
        ordering = ("sort_order", "-published_at", "-created_at")

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("cms:page_detail", kwargs={"slug": self.slug})


class HeroBanner(PublishableModel):
    """A homepage hero slide. The first published banner is the primary hero."""

    title = models.CharField(max_length=200)
    eyebrow = models.CharField(max_length=120, blank=True)
    subtitle = models.TextField(blank=True)
    cta_label = models.CharField(max_length=60, blank=True)
    cta_url = models.CharField(max_length=300, blank=True)
    secondary_cta_label = models.CharField(max_length=60, blank=True)
    secondary_cta_url = models.CharField(max_length=300, blank=True)
    image = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Hero banner"
        ordering = ("sort_order", "-published_at", "-created_at")

    def __str__(self) -> str:
        return self.title


# ---------------------------------------------------------------------------
# Business divisions & service pages
# ---------------------------------------------------------------------------


class BusinessDivision(PublishableModel):
    """A company division shown in the homepage service grid."""

    name = models.CharField(max_length=160)
    short_description = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=60, blank=True, help_text="Short label or glyph, e.g. a single emoji."
    )
    image = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Business division"
        ordering = ("sort_order", "-published_at", "-created_at")

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        service = self.service_pages.published().first()
        if service is not None:
            return service.get_absolute_url()
        return reverse("cms:service_list")


class ServicePage(PublishableModel):
    """A dedicated public page for one service offering."""

    division = models.ForeignKey(
        BusinessDivision,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="service_pages",
    )
    title = models.CharField(max_length=200)
    eyebrow = models.CharField(max_length=120, blank=True)
    intro = models.TextField(blank=True, help_text="Short introduction shown under the heading.")
    body = models.TextField(blank=True, help_text="Longer description (basic HTML allowed).")
    hero_image = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    icon = models.CharField(max_length=60, blank=True)
    benefits = models.JSONField(default=list, blank=True, help_text="List of benefit statements.")
    steps = models.JSONField(default=list, blank=True, help_text="Ordered 'how it works' steps.")
    cta_label = models.CharField(max_length=60, blank=True, default="Send an enquiry")
    cta_url = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "Service page"
        ordering = ("sort_order", "-published_at", "-created_at")

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("cms:service_detail", kwargs={"slug": self.slug})

    @property
    def enquiry_url(self) -> str:
        return self.cta_url or reverse("cms:contact")


class ServiceCategory(TimeStampedModel):
    """A category offered within a service page."""

    service_page = models.ForeignKey(
        ServicePage, on_delete=models.CASCADE, related_name="categories"
    )
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=300, blank=True)
    icon = models.CharField(max_length=60, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name_plural = "Service categories"

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# FAQs, testimonials, blog
# ---------------------------------------------------------------------------


class FAQ(TimeStampedModel):
    """A frequently asked question, optionally scoped to a service page."""

    question = models.CharField(max_length=300)
    answer = models.TextField()
    service_page = models.ForeignKey(
        ServicePage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="faqs",
        help_text="Leave blank for a general (site-wide) FAQ.",
    )
    sort_order = models.IntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self) -> str:
        return self.question


class Testimonial(TimeStampedModel):
    """A customer testimonial. Only approved testimonials are shown publicly."""

    author_name = models.CharField(max_length=160)
    author_role = models.CharField(max_length=160, blank=True)
    company = models.CharField(max_length=160, blank=True)
    quote = models.TextField()
    image = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Optional rating from 1 to 5."
    )
    is_approved = models.BooleanField(default=False, db_index=True)
    is_featured = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0, db_index=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_testimonials",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("sort_order", "-created_at")

    def __str__(self) -> str:
        return f"{self.author_name} — {self.quote[:40]}"


class TeamMember(TimeStampedModel):
    """A person shown in the About page team section.

    No achievements, licences or credentials are invented: staff enter only
    verified information.
    """

    name = models.CharField(max_length=160)
    role_title = models.CharField(max_length=160, blank=True)
    bio = models.TextField(blank=True)
    photo = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self) -> str:
        return self.name


class BlogCategory(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "Blog categories"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:140] or "category"
            candidate = base
            suffix = 2
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{suffix}"
                suffix += 1
            self.slug = candidate
        return super().save(*args, **kwargs)


class BlogPost(PublishableModel):
    """A news / blog article."""

    title = models.CharField(max_length=220)
    category = models.ForeignKey(
        BlogCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="posts"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blog_posts",
    )
    excerpt = models.CharField(max_length=300, blank=True)
    body = models.TextField(blank=True, help_text="Article body (basic HTML allowed).")
    featured_image = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reading_minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Blog post"
        ordering = ("sort_order", "-published_at", "-created_at")

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("cms:blog_detail", kwargs={"slug": self.slug})


# ---------------------------------------------------------------------------
# Contact enquiries
# ---------------------------------------------------------------------------


class ContactEnquiry(TimeStampedModel):
    """A submitted contact / enquiry form, stored securely and handled by staff.

    ``ip_address`` and ``user_agent`` are recorded for spam triage; they are
    never exposed on public pages.
    """

    name = models.CharField(max_length=160)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    division = models.CharField(max_length=40, blank=True)
    message = models.TextField()
    is_handled = models.BooleanField(default=False, db_index=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="handled_enquiries",
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "Contact enquiries"

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    def mark_handled(self, actor, when=None) -> None:
        self.is_handled = True
        self.handled_by = actor if getattr(actor, "is_authenticated", False) else None
        self.handled_at = when or timezone.now()

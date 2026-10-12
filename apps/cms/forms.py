"""Forms for the public contact page and the staff CMS.

Content models store some editorial lists as ``JSONField`` (benefits, steps,
value propositions). ``LineListField`` and ``KeyValueListField`` present those as
plain multi-line textareas so staff can edit them without touching JSON.
"""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.forms import TailwindFormMixin
from apps.core.constants import BusinessDivision as BusinessDivisionChoice

from .models import (
    FAQ,
    BlogCategory,
    BlogPost,
    BusinessDivision,
    HeroBanner,
    MediaAsset,
    NavigationItem,
    Page,
    ServiceCategory,
    ServicePage,
    SiteSetting,
    TeamMember,
    Testimonial,
)

# ---------------------------------------------------------------------------
# Custom editable-list fields
# ---------------------------------------------------------------------------


class LineListField(forms.Field):
    """A list of short strings, edited one item per line."""

    widget = forms.Textarea

    def prepare_value(self, value):
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
        return value or ""

    def clean(self, value):
        value = super().clean(value) or ""
        return [line.strip() for line in value.splitlines() if line.strip()]


class KeyValueListField(forms.Field):
    """A list of ``{"title", "body"}`` entries edited as ``Title | Body`` lines."""

    widget = forms.Textarea

    def prepare_value(self, value):
        if isinstance(value, list):
            lines = []
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{item.get('title', '')} | {item.get('body', '')}".rstrip(" |"))
            return "\n".join(lines)
        return value or ""

    def clean(self, value):
        value = super().clean(value) or ""
        items = []
        for line in value.splitlines():
            line = line.strip()
            if not line:
                continue
            title, _, body = line.partition("|")
            items.append({"title": title.strip(), "body": body.strip()})
        return items


class CMSForm(TailwindFormMixin, forms.ModelForm):
    """Base ModelForm applying the shared Tailwind widget styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


# ---------------------------------------------------------------------------
# Public contact form
# ---------------------------------------------------------------------------


class ContactForm(TailwindFormMixin, forms.Form):
    """Public enquiry form with a honeypot anti-spam field."""

    name = forms.CharField(max_length=160, label="Your name")
    email = forms.EmailField(label="Email address")
    phone = forms.CharField(max_length=40, required=False, label="Phone (optional)")
    subject = forms.CharField(max_length=200, required=False, label="Subject (optional)")
    division = forms.ChoiceField(
        required=False,
        label="Which service?",
        choices=[("", "General enquiry"), *BusinessDivisionChoice.choices],
    )
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), label="Message")

    # Bots fill hidden fields; humans never see it.
    website = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
        label="Website",
    )

    def clean_website(self) -> str:
        if self.cleaned_data.get("website"):
            raise ValidationError("Your submission could not be processed.")
        return ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()
        # The honeypot must be hidden from real users but visible to bots.
        self.fields["website"].widget.attrs["class"] = "hidden"
        self.fields["website"].widget.attrs["aria-hidden"] = "true"


# ---------------------------------------------------------------------------
# CMS forms
# ---------------------------------------------------------------------------


class MediaAssetForm(CMSForm):
    class Meta:
        model = MediaAsset
        fields = ("file", "title", "alt_text")


class SiteSettingForm(CMSForm):
    value_props = KeyValueListField(
        required=False,
        label="Why choose us",
        help_text="One per line as ‘Title | Short description’.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    class Meta:
        model = SiteSetting
        fields = (
            "site_name",
            "tagline",
            "description",
            "announcement_text",
            "announcement_url",
            "announcement_active",
            "phone",
            "phone_secondary",
            "whatsapp_number",
            "email",
            "address_line",
            "city",
            "state",
            "country",
            "map_embed_url",
            "facebook_url",
            "instagram_url",
            "twitter_url",
            "linkedin_url",
            "youtube_url",
            "logo",
            "favicon",
            "default_meta_title",
            "default_meta_description",
            "value_props",
        )


class HeroBannerForm(CMSForm):
    class Meta:
        model = HeroBanner
        fields = (
            "title",
            "eyebrow",
            "subtitle",
            "cta_label",
            "cta_url",
            "secondary_cta_label",
            "secondary_cta_url",
            "image",
            "status",
            "published_at",
            "is_featured",
            "sort_order",
        )
        widgets = {
            "subtitle": forms.Textarea(attrs={"rows": 3}),
            "published_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["published_at"].input_formats = ["%Y-%m-%dT%H:%M"]


class BusinessDivisionForm(CMSForm):
    class Meta:
        model = BusinessDivision
        fields = (
            "name",
            "short_description",
            "description",
            "icon",
            "image",
            "is_featured",
            "sort_order",
            "status",
            "published_at",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "published_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["published_at"].input_formats = ["%Y-%m-%dT%H:%M"]


class ServicePageForm(CMSForm):
    benefits = LineListField(
        required=False,
        label="Benefits",
        help_text="One benefit per line.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    steps = LineListField(
        required=False,
        label="How it works",
        help_text="One step per line, in order.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    class Meta:
        model = ServicePage
        fields = (
            "division",
            "title",
            "eyebrow",
            "intro",
            "body",
            "hero_image",
            "icon",
            "benefits",
            "steps",
            "cta_label",
            "cta_url",
            "status",
            "published_at",
            "is_featured",
            "sort_order",
            "meta_title",
            "meta_description",
            "canonical_url",
            "og_image",
            "noindex",
        )
        widgets = {
            "intro": forms.Textarea(attrs={"rows": 3}),
            "body": forms.Textarea(attrs={"rows": 8}),
            "published_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["published_at"].input_formats = ["%Y-%m-%dT%H:%M"]


class ServiceCategoryForm(CMSForm):
    class Meta:
        model = ServiceCategory
        fields = ("name", "description", "icon", "sort_order")


class BlogCategoryForm(CMSForm):
    class Meta:
        model = BlogCategory
        fields = ("name", "description")


class BlogPostForm(CMSForm):
    class Meta:
        model = BlogPost
        fields = (
            "title",
            "category",
            "excerpt",
            "body",
            "featured_image",
            "reading_minutes",
            "status",
            "published_at",
            "is_featured",
            "sort_order",
            "meta_title",
            "meta_description",
            "canonical_url",
            "og_image",
            "noindex",
        )
        widgets = {
            "excerpt": forms.Textarea(attrs={"rows": 3}),
            "body": forms.Textarea(attrs={"rows": 12}),
            "published_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["published_at"].input_formats = ["%Y-%m-%dT%H:%M"]


class FAQForm(CMSForm):
    class Meta:
        model = FAQ
        fields = ("question", "answer", "service_page", "sort_order", "is_published")
        widgets = {"answer": forms.Textarea(attrs={"rows": 5})}


class TestimonialForm(CMSForm):
    class Meta:
        model = Testimonial
        fields = (
            "author_name",
            "author_role",
            "company",
            "quote",
            "image",
            "rating",
            "is_featured",
            "sort_order",
        )
        widgets = {"quote": forms.Textarea(attrs={"rows": 4})}

    def clean_rating(self):
        rating = self.cleaned_data.get("rating")
        if rating is not None and not 1 <= rating <= 5:
            raise ValidationError("Rating must be between 1 and 5.")
        return rating


class TeamMemberForm(CMSForm):
    class Meta:
        model = TeamMember
        fields = ("name", "role_title", "bio", "photo", "sort_order", "is_active")
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}


class PageForm(CMSForm):
    class Meta:
        model = Page
        fields = (
            "page_type",
            "title",
            "summary",
            "body",
            "hero_image",
            "status",
            "published_at",
            "is_featured",
            "sort_order",
            "meta_title",
            "meta_description",
            "canonical_url",
            "og_image",
            "noindex",
        )
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 2}),
            "body": forms.Textarea(attrs={"rows": 12}),
            "published_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["published_at"].input_formats = ["%Y-%m-%dT%H:%M"]


class NavigationItemForm(CMSForm):
    class Meta:
        model = NavigationItem
        fields = (
            "label",
            "placement",
            "parent",
            "page",
            "url_name",
            "url",
            "sort_order",
            "is_active",
            "opens_new_tab",
        )

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get("page") or cleaned.get("url_name") or cleaned.get("url")):
            raise ValidationError("Provide a target: choose a page, or enter a URL name or a URL.")
        return cleaned

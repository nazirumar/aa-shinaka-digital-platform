"""CMS management views inside the staff dashboard (``/dashboard/cms/...``).

Built on Django's class-based generic views with a capability-checking mixin.
Authorisation is always enforced server-side; templates only hide navigation.
Reads come from ``selectors``; publish/approve/handle actions go through
``services`` so every change is audited.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.forms import inlineformset_factory
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView, View

from apps.accounts.permissions import has_capability
from apps.accounts.roles import Capability

from . import selectors, services
from .forms import (
    BlogCategoryForm,
    BlogPostForm,
    BusinessDivisionForm,
    FAQForm,
    HeroBannerForm,
    MediaAssetForm,
    NavigationItemForm,
    PageForm,
    ServiceCategoryForm,
    ServicePageForm,
    SiteSettingForm,
    TeamMemberForm,
    TestimonialForm,
)
from .models import (
    FAQ,
    BlogCategory,
    BlogPost,
    BusinessDivision,
    ContactEnquiry,
    HeroBanner,
    MediaAsset,
    NavigationItem,
    Page,
    PublishStatus,
    ServiceCategory,
    ServicePage,
    SiteSetting,
    TeamMember,
    Testimonial,
)


class CMSAccessMixin:
    """Require authentication plus a CMS capability for every CMS view."""

    capability = Capability.CONTENT_MANAGE
    active_nav = "cms"
    breadcrumbs: list[dict] = []

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not has_capability(request.user, self.capability):
            raise PermissionDenied("You do not have permission to manage website content.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("active_nav", self.active_nav)
        base = [
            {"label": "Dashboard", "url": "dashboard:home"},
            {"label": "Website", "url": "cms_dashboard:home"},
        ]
        context.setdefault("breadcrumbs", base + list(self.breadcrumbs))
        return context


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class CMSHomeView(CMSAccessMixin, TemplateView):
    template_name = "dashboard/cms/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Website content",
                "counts": selectors.cms_counts(),
                "enquiries": selectors.all_enquiries()[:5],
                "pending_testimonials": Testimonial.objects.filter(is_approved=False)[:5],
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Website"},
                ],
            }
        )
        return context


# ---------------------------------------------------------------------------
# Generic list / form / delete bases
# ---------------------------------------------------------------------------


class CMSListView(CMSAccessMixin, ListView):
    template_name = "dashboard/cms/object_list.html"
    paginate_by = 25
    context_object_name = "objects"
    columns: list[tuple[str, str]] = []
    title = ""
    create_url_name = ""
    edit_url_name = ""
    delete_url_name = ""
    detail_url_name = ""
    publish_url_name = ""
    empty_message = "No records yet."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": self.title,
                "title": self.title,
                "columns": self.columns,
                "empty_message": self.empty_message,
                "create_url": reverse(self.create_url_name) if self.create_url_name else "",
                "edit_url_name": self.edit_url_name,
                "delete_url_name": self.delete_url_name,
                "detail_url_name": self.detail_url_name,
                "publish_url_name": self.publish_url_name,
            }
        )
        return context


class CMSFormMixin(CMSAccessMixin):
    template_name = "dashboard/cms/object_form.html"
    title = ""
    success_url_name = ""
    slug = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": self.title,
                "title": self.title,
                "cancel_url": reverse(self.success_url_name),
            }
        )
        return context

    def get_success_url(self):
        return reverse(self.success_url_name)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.title.rstrip('s')} saved.")
        return response


class CMSDeleteView(CMSAccessMixin, DeleteView):
    template_name = "dashboard/cms/object_confirm_delete.html"
    success_url_name = ""
    title = "Delete"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"title": self.title, "cancel_url": reverse(self.success_url_name)})
        return context

    def get_success_url(self):
        return reverse(self.success_url_name)

    def form_valid(self, form):
        messages.success(self.request, "Deleted.")
        return super().form_valid(form)


class PublishToggleView(CMSAccessMixin, View):
    """Publish/unpublish/archive a publishable object, then return to its list."""

    capability = Capability.CONTENT_PUBLISH
    model = None
    success_url_name = ""

    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        obj = get_object_or_404(self.model, pk=pk)
        status = request.POST.get("status", PublishStatus.PUBLISHED)
        if status not in PublishStatus.values:
            # Never trust client input; fall back to a safe published state.
            status = PublishStatus.PUBLISHED
        services.set_publish_status(obj, status=status, actor=request.user, request=request)
        messages.success(request, f"Status changed to “{status}”.")
        return redirect(reverse(self.success_url_name))


def _publish_view(model, success_url_name, name):
    return type(
        name,
        (PublishToggleView,),
        {"model": model, "success_url_name": success_url_name},
    )


# ---------------------------------------------------------------------------
# Hero banners
# ---------------------------------------------------------------------------


class BannerListView(CMSListView):
    model = HeroBanner
    title = "Hero banners"
    columns = [("Title", "title"), ("Status", "status"), ("Order", "sort_order")]
    create_url_name = "cms_dashboard:banner_create"
    edit_url_name = "cms_dashboard:banner_edit"
    delete_url_name = "cms_dashboard:banner_delete"
    publish_url_name = "cms_dashboard:banner_publish"

    def get_queryset(self):
        return selectors.all_hero_banners()


class BannerCreateView(CMSFormMixin, CreateView):
    model = HeroBanner
    form_class = HeroBannerForm
    title = "New hero banner"
    success_url_name = "cms_dashboard:banner_list"


class BannerUpdateView(CMSFormMixin, UpdateView):
    model = HeroBanner
    form_class = HeroBannerForm
    title = "Edit hero banner"
    success_url_name = "cms_dashboard:banner_list"


class BannerDeleteView(CMSDeleteView):
    model = HeroBanner
    success_url_name = "cms_dashboard:banner_list"


# ---------------------------------------------------------------------------
# Business divisions
# ---------------------------------------------------------------------------


class DivisionListView(CMSListView):
    model = BusinessDivision
    title = "Business divisions"
    columns = [("Name", "name"), ("Status", "status"), ("Order", "sort_order")]
    create_url_name = "cms_dashboard:division_create"
    edit_url_name = "cms_dashboard:division_edit"
    delete_url_name = "cms_dashboard:division_delete"
    publish_url_name = "cms_dashboard:division_publish"

    def get_queryset(self):
        return selectors.all_divisions()


class DivisionCreateView(CMSFormMixin, CreateView):
    model = BusinessDivision
    form_class = BusinessDivisionForm
    title = "New division"
    success_url_name = "cms_dashboard:division_list"


class DivisionUpdateView(CMSFormMixin, UpdateView):
    model = BusinessDivision
    form_class = BusinessDivisionForm
    title = "Edit division"
    success_url_name = "cms_dashboard:division_list"


class DivisionDeleteView(CMSDeleteView):
    model = BusinessDivision
    success_url_name = "cms_dashboard:division_list"


# ---------------------------------------------------------------------------
# Service pages (+ inline categories)
# ---------------------------------------------------------------------------


ServiceCategoryFormSet = inlineformset_factory(
    ServicePage, ServiceCategory, form=ServiceCategoryForm, extra=1, can_delete=True
)


class ServiceListView(CMSListView):
    model = ServicePage
    title = "Service pages"
    columns = [("Title", "title"), ("Division", "division"), ("Status", "status")]
    create_url_name = "cms_dashboard:service_create"
    edit_url_name = "cms_dashboard:service_edit"
    delete_url_name = "cms_dashboard:service_delete"
    publish_url_name = "cms_dashboard:service_publish"

    def get_queryset(self):
        return selectors.all_service_pages()


class _ServiceFormMixin(CMSFormMixin):
    model = ServicePage
    form_class = ServicePageForm
    template_name = "dashboard/cms/service_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.method == "POST":
            context["formset"] = ServiceCategoryFormSet(self.request.POST, instance=self.object)
        else:
            context["formset"] = ServiceCategoryFormSet(instance=self.object)
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        formset = context["formset"]
        if not formset.is_valid():
            return self.form_invalid(form)
        self.object = form.save()
        formset.instance = self.object
        formset.save()
        messages.success(self.request, "Service page saved.")
        return redirect(self.get_success_url())


class ServiceCreateView(_ServiceFormMixin, CreateView):
    title = "New service page"
    success_url_name = "cms_dashboard:service_list"


class ServiceUpdateView(_ServiceFormMixin, UpdateView):
    title = "Edit service page"
    success_url_name = "cms_dashboard:service_list"


class ServiceDeleteView(CMSDeleteView):
    model = ServicePage
    success_url_name = "cms_dashboard:service_list"


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------


class BlogCategoryListView(CMSListView):
    model = BlogCategory
    title = "Blog categories"
    columns = [("Name", "name"), ("Slug", "slug")]
    create_url_name = "cms_dashboard:blog_category_create"
    edit_url_name = "cms_dashboard:blog_category_edit"
    delete_url_name = "cms_dashboard:blog_category_delete"

    def get_queryset(self):
        return selectors.blog_categories()


class BlogCategoryCreateView(CMSFormMixin, CreateView):
    model = BlogCategory
    form_class = BlogCategoryForm
    title = "New blog category"
    success_url_name = "cms_dashboard:blog_category_list"


class BlogCategoryUpdateView(CMSFormMixin, UpdateView):
    model = BlogCategory
    form_class = BlogCategoryForm
    title = "Edit blog category"
    success_url_name = "cms_dashboard:blog_category_list"


class BlogCategoryDeleteView(CMSDeleteView):
    model = BlogCategory
    success_url_name = "cms_dashboard:blog_category_list"


class BlogPostListView(CMSListView):
    model = BlogPost
    title = "Blog posts"
    columns = [("Title", "title"), ("Category", "category"), ("Status", "status")]
    create_url_name = "cms_dashboard:post_create"
    edit_url_name = "cms_dashboard:post_edit"
    delete_url_name = "cms_dashboard:post_delete"
    publish_url_name = "cms_dashboard:post_publish"

    def get_queryset(self):
        return selectors.all_blog_posts()


class _BlogPostFormMixin(CMSFormMixin):
    model = BlogPost
    form_class = BlogPostForm

    def form_valid(self, form):
        if form.instance.pk is None:
            form.instance.author = self.request.user
        return super().form_valid(form)


class BlogPostCreateView(_BlogPostFormMixin, CreateView):
    title = "New blog post"
    success_url_name = "cms_dashboard:post_list"


class BlogPostUpdateView(_BlogPostFormMixin, UpdateView):
    title = "Edit blog post"
    success_url_name = "cms_dashboard:post_list"


class BlogPostDeleteView(CMSDeleteView):
    model = BlogPost
    success_url_name = "cms_dashboard:post_list"


# ---------------------------------------------------------------------------
# FAQs
# ---------------------------------------------------------------------------


class FAQListView(CMSListView):
    model = FAQ
    title = "FAQs"
    columns = [("Question", "question"), ("Service", "service_page"), ("Published", "is_published")]
    create_url_name = "cms_dashboard:faq_create"
    edit_url_name = "cms_dashboard:faq_edit"
    delete_url_name = "cms_dashboard:faq_delete"

    def get_queryset(self):
        return selectors.all_faqs()


class FAQCreateView(CMSFormMixin, CreateView):
    model = FAQ
    form_class = FAQForm
    title = "New FAQ"
    success_url_name = "cms_dashboard:faq_list"


class FAQUpdateView(CMSFormMixin, UpdateView):
    model = FAQ
    form_class = FAQForm
    title = "Edit FAQ"
    success_url_name = "cms_dashboard:faq_list"


class FAQDeleteView(CMSDeleteView):
    model = FAQ
    success_url_name = "cms_dashboard:faq_list"


# ---------------------------------------------------------------------------
# Testimonials
# ---------------------------------------------------------------------------


class TestimonialListView(CMSListView):
    model = Testimonial
    title = "Testimonials"
    columns = [("Author", "author_name"), ("Approved", "is_approved"), ("Featured", "is_featured")]
    create_url_name = "cms_dashboard:testimonial_create"
    edit_url_name = "cms_dashboard:testimonial_edit"
    delete_url_name = "cms_dashboard:testimonial_delete"

    def get_queryset(self):
        return selectors.all_testimonials()


class TestimonialCreateView(CMSFormMixin, CreateView):
    model = Testimonial
    form_class = TestimonialForm
    title = "New testimonial"
    success_url_name = "cms_dashboard:testimonial_list"


class TestimonialUpdateView(CMSFormMixin, UpdateView):
    model = Testimonial
    form_class = TestimonialForm
    title = "Edit testimonial"
    success_url_name = "cms_dashboard:testimonial_list"


class TestimonialDeleteView(CMSDeleteView):
    model = Testimonial
    success_url_name = "cms_dashboard:testimonial_list"


class TestimonialDecisionView(CMSAccessMixin, View):
    """Approve or unapprove a testimonial via HTMX-friendly POST."""

    capability = Capability.TESTIMONIALS_APPROVE

    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        testimonial = get_object_or_404(Testimonial, pk=pk)
        action = request.POST.get("action", "approve")
        if action == "approve":
            services.approve_testimonial(testimonial, actor=request.user, request=request)
            messages.success(request, "Testimonial approved.")
        else:
            services.unapprove_testimonial(testimonial, actor=request.user, request=request)
            messages.success(request, "Testimonial unapproved.")
        return redirect(reverse("cms_dashboard:testimonial_list"))


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------


class TeamListView(CMSListView):
    model = TeamMember
    title = "Team members"
    columns = [("Name", "name"), ("Role", "role_title"), ("Active", "is_active")]
    create_url_name = "cms_dashboard:team_create"
    edit_url_name = "cms_dashboard:team_edit"
    delete_url_name = "cms_dashboard:team_delete"

    def get_queryset(self):
        return selectors.all_team_members()


class TeamCreateView(CMSFormMixin, CreateView):
    model = TeamMember
    form_class = TeamMemberForm
    title = "New team member"
    success_url_name = "cms_dashboard:team_list"


class TeamUpdateView(CMSFormMixin, UpdateView):
    model = TeamMember
    form_class = TeamMemberForm
    title = "Edit team member"
    success_url_name = "cms_dashboard:team_list"


class TeamDeleteView(CMSDeleteView):
    model = TeamMember
    success_url_name = "cms_dashboard:team_list"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


class PageListView(CMSListView):
    model = Page
    title = "Pages"
    columns = [("Title", "title"), ("Type", "page_type"), ("Status", "status")]
    create_url_name = "cms_dashboard:page_create"
    edit_url_name = "cms_dashboard:page_edit"
    delete_url_name = "cms_dashboard:page_delete"
    publish_url_name = "cms_dashboard:page_publish"

    def get_queryset(self):
        return selectors.all_pages()


class PageCreateView(CMSFormMixin, CreateView):
    model = Page
    form_class = PageForm
    title = "New page"
    success_url_name = "cms_dashboard:page_list"


class PageUpdateView(CMSFormMixin, UpdateView):
    model = Page
    form_class = PageForm
    title = "Edit page"
    success_url_name = "cms_dashboard:page_list"


class PageDeleteView(CMSDeleteView):
    model = Page
    success_url_name = "cms_dashboard:page_list"


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------


class MediaListView(CMSListView):
    model = MediaAsset
    title = "Media library"
    columns = [("Title", "title"), ("Alt text", "alt_text"), ("Uploaded", "created_at")]
    create_url_name = "cms_dashboard:media_create"
    edit_url_name = "cms_dashboard:media_edit"
    delete_url_name = "cms_dashboard:media_delete"
    capability = Capability.MEDIA_MANAGE

    def get_queryset(self):
        return selectors.media_assets()


class _MediaFormMixin(CMSFormMixin):
    model = MediaAsset
    form_class = MediaAssetForm
    capability = Capability.MEDIA_MANAGE

    def form_valid(self, form):
        if form.instance.pk is None:
            form.instance.uploaded_by = self.request.user
        return super().form_valid(form)


class MediaCreateView(_MediaFormMixin, CreateView):
    title = "Upload media"
    success_url_name = "cms_dashboard:media_list"


class MediaUpdateView(_MediaFormMixin, UpdateView):
    title = "Edit media"
    success_url_name = "cms_dashboard:media_list"


class MediaDeleteView(CMSDeleteView):
    model = MediaAsset
    capability = Capability.MEDIA_MANAGE
    success_url_name = "cms_dashboard:media_list"


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


class NavigationListView(CMSListView):
    model = NavigationItem
    title = "Navigation"
    columns = [
        ("Label", "label"),
        ("Placement", "placement"),
        ("Active", "is_active"),
        ("Order", "sort_order"),
    ]
    create_url_name = "cms_dashboard:nav_create"
    edit_url_name = "cms_dashboard:nav_edit"
    delete_url_name = "cms_dashboard:nav_delete"
    capability = Capability.NAV_MANAGE

    def get_queryset(self):
        return selectors.all_navigation_items()


class _NavFormMixin(CMSFormMixin):
    model = NavigationItem
    form_class = NavigationItemForm
    capability = Capability.NAV_MANAGE


class NavigationCreateView(_NavFormMixin, CreateView):
    title = "New navigation item"
    success_url_name = "cms_dashboard:nav_list"


class NavigationUpdateView(_NavFormMixin, UpdateView):
    title = "Edit navigation item"
    success_url_name = "cms_dashboard:nav_list"


class NavigationDeleteView(CMSDeleteView):
    model = NavigationItem
    capability = Capability.NAV_MANAGE
    success_url_name = "cms_dashboard:nav_list"


# ---------------------------------------------------------------------------
# Site settings
# ---------------------------------------------------------------------------


class SiteSettingView(CMSAccessMixin, UpdateView):
    capability = Capability.SITE_CONFIG
    model = SiteSetting
    form_class = SiteSettingForm
    template_name = "dashboard/cms/object_form.html"
    success_url_name = "cms_dashboard:settings"

    def get_object(self, queryset=None):
        return SiteSetting.load()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Site settings",
                "title": "Site settings & contact details",
                "cancel_url": reverse("cms_dashboard:home"),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Website", "url": "cms_dashboard:home"},
                    {"label": "Settings"},
                ],
            }
        )
        return context

    def get_success_url(self):
        return reverse(self.success_url_name)

    def form_valid(self, form):
        messages.success(self.request, "Site settings saved.")
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Enquiries
# ---------------------------------------------------------------------------


class EnquiryListView(CMSAccessMixin, ListView):
    capability = Capability.CONTACT_MANAGE
    template_name = "dashboard/cms/enquiry_list.html"
    context_object_name = "enquiries"
    paginate_by = 25

    def get_queryset(self):
        queryset = selectors.all_enquiries()
        if self.request.GET.get("status") == "open":
            queryset = queryset.filter(is_handled=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Enquiries",
                "title": "Contact enquiries",
                "selected_status": self.request.GET.get("status", ""),
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Website", "url": "cms_dashboard:home"},
                    {"label": "Enquiries"},
                ],
            }
        )
        return context


class EnquiryDetailView(CMSAccessMixin, TemplateView):
    capability = Capability.CONTACT_MANAGE
    template_name = "dashboard/cms/enquiry_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        enquiry = get_object_or_404(ContactEnquiry, pk=kwargs["pk"])
        context.update(
            {
                "page_title": "Enquiry",
                "enquiry": enquiry,
                "breadcrumbs": [
                    {"label": "Dashboard", "url": "dashboard:home"},
                    {"label": "Website", "url": "cms_dashboard:home"},
                    {"label": "Enquiries", "url": "cms_dashboard:enquiry_list"},
                    {"label": str(enquiry.pk)},
                ],
            }
        )
        return context


class EnquiryHandleView(CMSAccessMixin, View):
    capability = Capability.CONTACT_MANAGE

    def post(self, request: HttpRequest, pk, *args, **kwargs) -> HttpResponse:
        enquiry = get_object_or_404(ContactEnquiry, pk=pk)
        services.mark_enquiry_handled(enquiry, actor=request.user, request=request)
        messages.success(request, "Enquiry marked as handled.")
        return redirect(reverse("cms_dashboard:enquiry_list"))


# Publish-toggle views (one per publishable model).
BannerPublishView = _publish_view(HeroBanner, "cms_dashboard:banner_list", "BannerPublishView")
DivisionPublishView = _publish_view(
    BusinessDivision, "cms_dashboard:division_list", "DivisionPublishView"
)
ServicePublishView = _publish_view(ServicePage, "cms_dashboard:service_list", "ServicePublishView")
PostPublishView = _publish_view(BlogPost, "cms_dashboard:post_list", "PostPublishView")
PagePublishView = _publish_view(Page, "cms_dashboard:page_list", "PagePublishView")

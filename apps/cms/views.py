"""Public website views.

Thin views: reads come from ``selectors``, writes from ``services`` (the contact
enquiry). Content is published-only; drafts and archives never appear here.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.core.ratelimit import rate_limit

from . import selectors
from .forms import ContactForm
from .services import submit_contact_enquiry


def _seo(
    *,
    title: str = "",
    description: str = "",
    canonical: str = "",
    og_image=None,
    noindex: bool = False,
) -> dict:
    return {
        "page_title": title,
        "seo_title": title,
        "seo_description": description,
        "seo_canonical": canonical,
        "seo_og_image": og_image,
        "seo_noindex": noindex,
    }


def _content_seo(obj, *, fallback_title: str = "") -> dict:
    """Build SEO context from a content object with ``SEOModel`` fields."""
    title = (getattr(obj, "meta_title", "") or getattr(obj, "title", "") or fallback_title).strip()
    return _seo(
        title=title,
        description=getattr(obj, "meta_description", "")
        or getattr(obj, "summary", "")
        or getattr(obj, "excerpt", "")
        or getattr(obj, "intro", ""),
        canonical=getattr(obj, "canonical_url", ""),
        og_image=getattr(obj, "og_image", None) or getattr(obj, "hero_image", None),
        noindex=getattr(obj, "noindex", False),
    )


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def service_list(request: HttpRequest) -> HttpResponse:
    context = {
        **_seo(
            title="Our services",
            description=(
                "Agricultural consultancy, farming services, marketing, storage and "
                "export services delivered by AA Shinaka."
            ),
        ),
        "services": selectors.service_pages(),
        "breadcrumbs": [{"label": "Home", "url": "core:home"}, {"label": "Services"}],
    }
    return render(request, "cms/service_list.html", context)


def service_detail(request: HttpRequest, slug: str) -> HttpResponse:
    service = selectors.service_page(slug)
    if service is None:
        return render(request, "cms/not_found.html", status=404)
    context = {
        **_content_seo(service),
        "service": service,
        "categories": service.categories.all(),
        "faqs": service.faqs.filter(is_published=True),
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "Services", "url": "cms:service_list"},
            {"label": service.title},
        ],
    }
    return render(request, "cms/service_detail.html", context)


# ---------------------------------------------------------------------------
# Editable pages (About / Terms / Privacy / custom)
# ---------------------------------------------------------------------------


def page_detail(request: HttpRequest, slug: str) -> HttpResponse:
    page = selectors.page(slug)
    if page is None:
        return render(request, "cms/not_found.html", status=404)
    context = {
        **_content_seo(page),
        "page": page,
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": page.title},
        ],
    }
    return render(request, "cms/page_detail.html", context)


def about(request: HttpRequest) -> HttpResponse:
    page = selectors.page_of_type("about")
    site = selectors.site_settings()
    context = {
        **_seo(
            title=(page.meta_title if page else "") or "About AA Shinaka",
            description=(
                (page.meta_description if page else "")
                or site.description
                or "Learn about AA Shinaka's agricultural divisions, mission and team."
            ),
        ),
        "page": page,
        "divisions": selectors.business_divisions(),
        "testimonials": selectors.featured_testimonials(limit=6),
        "team": selectors.team_members(),
        "breadcrumbs": [{"label": "Home", "url": "core:home"}, {"label": "About"}],
    }
    return render(request, "cms/about.html", context)


# ---------------------------------------------------------------------------
# Contact
# ---------------------------------------------------------------------------


@rate_limit(
    scope="contact",
    limit=settings.FORM_RATE_LIMIT_ATTEMPTS,
    window=settings.FORM_RATE_LIMIT_WINDOW,
)
def contact(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            submit_contact_enquiry(
                name=form.cleaned_data["name"],
                email=form.cleaned_data["email"],
                phone=form.cleaned_data.get("phone", ""),
                subject=form.cleaned_data.get("subject", ""),
                division=form.cleaned_data.get("division", ""),
                message=form.cleaned_data["message"],
                request=request,
            )
            messages.success(
                request,
                "Thank you — your enquiry has been received. Our team will respond shortly.",
            )
            return redirect(f"{reverse('cms:contact')}?sent=1")
    else:
        form = ContactForm()

    site = selectors.site_settings()
    context = {
        **_seo(
            title="Contact us",
            description=(
                "Contact AA Shinaka for consultancy, farming, marketing, storage, export or "
                "training enquiries."
            ),
        ),
        "form": form,
        "sent": request.GET.get("sent") == "1",
        "whatsapp_url": site.whatsapp_url,
        "breadcrumbs": [{"label": "Home", "url": "core:home"}, {"label": "Contact"}],
    }
    return render(request, "cms/contact.html", context)


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------


def blog_list(request: HttpRequest) -> HttpResponse:
    category = request.GET.get("category", "")
    posts = selectors.published_blog_posts(category=category)
    page_obj = Paginator(posts, 6).get_page(request.GET.get("page"))
    context = {
        **_seo(
            title="News & insights",
            description="Agricultural news, guidance and insights from AA Shinaka.",
        ),
        "posts": page_obj,
        "page_obj": page_obj,
        "categories": selectors.blog_categories(),
        "selected_category": category,
        "breadcrumbs": [{"label": "Home", "url": "core:home"}, {"label": "News"}],
    }
    if request.headers.get("HX-Request"):
        return render(request, "cms/_post_list.html", context)
    return render(request, "cms/blog_list.html", context)


def blog_detail(request: HttpRequest, slug: str) -> HttpResponse:
    post = selectors.blog_post(slug)
    if post is None:
        return render(request, "cms/not_found.html", status=404)
    context = {
        **_content_seo(post),
        "post": post,
        "related": [p for p in selectors.latest_blog_posts(limit=4) if p.pk != post.pk][:3],
        "breadcrumbs": [
            {"label": "Home", "url": "core:home"},
            {"label": "News", "url": "cms:blog_list"},
            {"label": post.title},
        ],
    }
    return render(request, "cms/blog_detail.html", context)


# ---------------------------------------------------------------------------
# FAQs / robots
# ---------------------------------------------------------------------------


def faq_list(request: HttpRequest) -> HttpResponse:
    context = {
        **_seo(
            title="Frequently asked questions",
            description="Answers to common questions about AA Shinaka.",
        ),
        "faqs": selectors.general_faqs(),
        "breadcrumbs": [{"label": "Home", "url": "core:home"}, {"label": "FAQs"}],
    }
    return render(request, "cms/faq_list.html", context)


def robots_txt(request: HttpRequest) -> HttpResponse:
    sitemap_url = request.build_absolute_uri(reverse("sitemap"))
    lines = [
        "User-agent: *",
        "Disallow: /dashboard/",
        "Disallow: /admin/",
        "Disallow: /account/",
        "Disallow: /accounts/",
        "Disallow: /i18n/",
        "",
        f"Sitemap: {sitemap_url}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")

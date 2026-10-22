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
from apps.seo import canonical_from_request, content_seo, seo_context

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
    og_type: str = "website",
) -> dict:
    """SEO context for this app. Signature kept for existing call sites."""
    return seo_context(
        title=title,
        description=description,
        canonical=canonical,
        og_image=og_image,
        noindex=noindex,
        og_type=og_type,
    )


def _content_seo(obj, *, fallback_title: str = "", canonical: str = "", og_type: str = "") -> dict:
    """Build SEO context from a content object with ``SEOModel`` fields."""
    kwargs = {}
    if og_type:
        kwargs["og_type"] = og_type
    return content_seo(obj, fallback_title=fallback_title, canonical=canonical, **kwargs)


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
        # Pagination and category filters must not fork the canonical: without
        # this, /news/?page=2 declared itself canonical and every page competed
        # with the others instead of consolidating.
        **_seo(
            title="News & insights",
            description="Agricultural news, guidance and insights from AA Shinaka.",
            canonical=canonical_from_request(request),
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
        # Blog articles are articles, not generic websites.
        **_content_seo(post, og_type="article"),
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
    sitemap_index_url = request.build_absolute_uri(reverse("sitemap_index"))
    lines = [
        "User-agent: *",
        # Staff and internal areas.
        "Disallow: /dashboard/",
        "Disallow: /admin/",
        "Disallow: /internal/",
        "Disallow: /healthz/",
        # Customer identity, commerce and portal.
        "Disallow: /account/",
        "Disallow: /accounts/",
        "Disallow: /cart/",
        "Disallow: /checkout/",
        "Disallow: /orders/",
        "Disallow: /payments/",
        "Disallow: /invoices/",
        "Disallow: /receipts/",
        "Disallow: /quotations/",
        # Language switching triggers a POST and is not content.
        "Disallow: /i18n/",
        # Catalogue utility endpoints: filtered/sorted views, comparison and the
        # dependent LGA lookup are all `noindex` pages that add crawl waste.
        "Disallow: /shop/search",
        "Disallow: /shop/compare",
        "Disallow: /lga-options",
        # Certificate verification is a lookup tool, not content.
        "Disallow: /training/verify",
        "Allow: /",
        "",
        # Both are advertised: the flat urlset stays for compatibility, the
        # index is what crawlers should prefer as the site grows.
        f"Sitemap: {sitemap_url}",
        f"Sitemap: {sitemap_index_url}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")

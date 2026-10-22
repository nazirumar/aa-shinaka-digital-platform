# Search Visibility (SEO / AEO / GEO) — Phase 1: Technical SEO Audit

**Status: AUDIT ONLY. No application code was changed.**
This phase inspects the repository and the public templates, reproduces the
defects, and proposes a plan. Nothing was deployed, no production secret was
touched, no DNS record was changed and no live payment was enabled.

- Repository: `aa-shinaka-digital-platform`
- Baseline: `master` @ `12a5e54`
- Production domain: `https://aashinaka.com`
- Stack audited: Django 5.2 LTS MVT monolith, PostgreSQL, Redis, Celery,
  Django Templates (+ HTMX / Alpine), WhiteNoise.

Every finding below was reproduced locally against `config.settings.test` with a
seeded database, using the real views, URLconf and templates. Where a claim
depends on the live Render service it is marked as **unverified** rather than
asserted.

---

## 1. Executive summary

A working **Phase 3 SEO foundation already exists** and should be extended, not
replaced. Specifically, the platform already has dynamic titles and
descriptions, a canonical link tag, a dynamic `robots.txt`, a Django XML
sitemap, Open Graph / Twitter tags, per-record SEO fields on CMS content and
catalogue products, and a shared `{% block meta %}` / `{% block head_extra %}`
extension point in `templates/base.html`.

The audit found **three high-severity defects, five medium and a long tail of
lower-severity gaps**. The most consequential are:

1. **The sitemap omits the two largest public content areas.** Verified local
   output: exactly **15 URLs**, comprising the homepage, six marketing pages,
   five service pages and three CMS pages. There are **zero catalogue URLs and
   zero training URLs** — no products, categories, states, LGAs, courses or
   course categories, even though all of those are public, indexable and
   already linkable via stable `get_absolute_url()`.
2. **Canonical URLs include the query string.** Every paginated and filtered
   page self-canonicalises to its own parameterised URL. Verified:
   `GET /news/?page=2` emits
   `<link rel="canonical" href=".../news/?page=2">`. The same defect affects
   `/shop/category/<slug>/`, `/shop/state/...`, `/shop/search/` and
   `/shop/compare/`. Instead of consolidating faceted duplicates, the platform
   currently declares each duplicate to be the canonical page.
3. **No structured data (JSON-LD) anywhere.** There is not a single
   `application/ld+json` block in the repository or in any rendered page —
   no `Organization`, `Product`, `BreadcrumbList`, `Article`, `Course` or
   `FAQPage`. This is the single largest gap for rich results and for the
   entity clarity that answer engines (AEO) and generative engines (GEO) rely
   on.

Two further points deserve the owner's attention because they are cheap to fix
and currently expose non-public or duplicate URLs to crawlers:

- `/cart/`, `/accounts/login/`, `/accounts/register/` and `/training/verify/`
  return **200 with no `noindex`** (verified). `/cart/` in particular is a
  session-specific duplicate of no search value.
- **No Search Console or Bing verification tag exists**, and no analytics or
  tracking of any kind is installed. Search performance reporting (Phase 4/6)
  therefore has no data source yet.

Finally, a structural observation that shapes Phase 2: SEO logic is currently
**duplicated across three apps** with three divergent private `_seo()` helpers
(`apps/cms/views.py`, `apps/catalog/views.py`, `apps/training/views.py`) and two
incompatible field-naming conventions (`meta_title`/`meta_description` in the
CMS vs `seo_title`/`seo_description` in the catalogue). Any expansion should
consolidate this behind one shared SEO module rather than adding a fourth
variant.

### 1.1 Scope reminder (what this is not)

Per the brief, none of the following is claimed or will be claimed in later
phases:

- This work does **not** guarantee Google rankings or any specific position.
- It does **not** guarantee citation by ChatGPT, Claude, Gemini, Perplexity or
  any other AI platform. Where no supported analytics integration exists, the
  system will show an explicit *unavailable* state rather than invented
  numbers.
- No private page, account, checkout or customer data will be added to a
  sitemap.

---

## 2. What already exists (do not rebuild)

| Capability | Location | State |
|---|---|---|
| Sitemap framework registered | `config/settings/base.py:47` (`django.contrib.sitemaps`) | Working |
| Sitemap route | `config/urls.py:20` → `/sitemap.xml` | Working |
| Sitemap classes (static/services/pages/blog) | `apps/cms/sitemaps.py` (68 lines) | Working, incomplete |
| Dynamic `robots.txt` | `apps/cms/views.py:242-254`, route `apps/cms/urls.py:21` | Working, incomplete |
| Canonical link tag | `templates/base.html:10` | Present, buggy (query string) |
| Meta description | `templates/base.html:9` | Working |
| Open Graph + Twitter cards | `templates/base.html:13-22` | Partial |
| `noindex` per record | `templates/base.html:11`; `SEOModel.noindex` | Working |
| CMS per-record SEO fields | `apps/cms/models.py:154-183` (`SEOModel`: `meta_title`, `meta_description`, `canonical_url`, `og_image`, `noindex`) | Complete |
| Global site metadata (singleton) | `apps/cms/models.py:222-315` (`SiteSetting`: `site_name`, `tagline`, `description`, `default_meta_title`, `default_meta_description`, social URLs, `logo`, `favicon`) | Complete |
| Catalogue per-product SEO fields | `apps/catalog/models.py:388-389`, `447-454` (`seo_title`, `seo_description`, `Product.seo()`) | Present, no canonical/og/noindex |
| Category SEO fields | `apps/catalog/models.py:137-138` (`seo_title`, `seo_description`) | Present |
| CMS dashboard forms expose SEO fields | `apps/cms/forms.py:262-266`, `307-311`, `375-379`; `apps/catalog/forms.py:60-61`, `96-97` | Working |
| Breadcrumb partial (visual only) | `templates/components/breadcrumbs.html` | Present, **no JSON-LD** |
| Image `alt` handling | `templates/components/lazy_image.html` (falls back to `image.alt_text` → `image.title`) | Working |
| Template extension points | `templates/base.html:8` (`{% block meta %}`), `:31` (`{% block head_extra %}` — **currently overridden by zero templates**) | Available |
| Existing SEO tests | `tests/test_cms_public.py:380-421` (title/description/canonical presence, sitemap drafts excluded, robots disallows) | Partial |

`django.contrib.sites` is **not** installed and `SITE_ID` is **not** set, so
sitemap URLs are built from `RequestSite` (`request.get_host()` +
`request.scheme`). This is correct behind nginx because
`SECURE_PROXY_SSL_HEADER` and `USE_X_FORWARDED_HOST` are set in
`config/settings/prod.py:117-118`, but it means the sitemap is host-derived
rather than pinned to the production domain.

---

## 3. Findings

Severity: **High** = indexing/duplication impact or missing core feature.
**Medium** = quality/maintainability or partial implementation.
**Low** = polish.

### H1 — Sitemap omits all catalogue and training content *(High)*

`apps/cms/sitemaps.py:63-68` registers four sitemaps: `static`, `services`,
`pages`, `blog`. There is no entry for the catalogue (`/shop/...`) or the
training academy (`/training/...`).

**Reproduced output** (`GET /sitemap.xml`, 15 URLs):

```
/                                     /news/
/services/                            /faqs/
/about/                               /services/consultancy-advisory/
/contact/                             ... (5 service pages)
/pages/terms-of-service/              /pages/privacy-policy/
/pages/contact/                       /pages/about/
```

`/shop/`, every category, every product, every state and LGA page, the training
home, course list, every course and every course category are **absent**. For an
agricultural marketplace, the product and category URLs are the highest-value
indexable assets on the site.

*Impact:* products, categories and courses cannot be discovered via the sitemap.

### H2 — Canonical URLs include the query string *(High)*

`templates/base.html:10` (and the mirror at `:18` for `og:url`) use
`{{ seo_canonical|default:request.build_absolute_uri }}`. `build_absolute_uri`
returns the **full** URI including the query string. `seo_canonical` is empty on
every list/index/filtered page.

**Reproduced:**

| Request | Emitted canonical |
|---|---|
| `/news/` | `http://testserver/news/` |
| `/news/?page=2` | `http://testserver/news/?page=2` |
| `/news/?category=none` | `http://testserver/news/?category=none` |

The same applies to `/shop/category/<slug>/?state=…&lga=…&page=N`,
`/shop/state/<slug>/?page=N`, `/shop/search/?q=…&sort=…` and
`/shop/compare/?slugs=…`. The last two already set `noindex` (correct), but they
still emit a canonical, and every paginated variant of the first two is
indexable and self-canonical.

Affected views: `apps/cms/views.py:188-205`;
`apps/catalog/views.py:102-149, 225-282, 309-353`.

*Impact:* faceted and paginated duplicates are declared canonical rather than
consolidated — the opposite of the intended behaviour.

### H3 — No structured data / JSON-LD anywhere *(High)*

Repository-wide search for `application/ld+json` / `schema.org` returns zero
matches. `docs/UI_UX_SPEC.md:400,407` explicitly defers structured data to a
later phase — that phase is now.

Missing: `Organization` (name, logo, address, telephone, social profiles — all
already available on `SiteSetting`), `WebSite` + `SearchAction`, `Product`
(with `Offers`/`AggregateOffer` from `ProductListing`), `BreadcrumbList`,
`Article` (blog), `Course` (training), `FAQPage` (the `FAQ` model already
exists).

*Impact:* no rich results eligibility; reduced entity clarity for answer and
generative engines.

### H4 — No Search Console / Bing verification, no analytics *(High — trivial effort)*

No `google-site-verification`, `msvalidate.01`, GTM, GA4, Plausible, Umami or
Matomo anywhere. `{% block head_extra %}` (`templates/base.html:31`) is the
ready-made injection point and is currently overridden by **zero** templates.

*Impact:* Phase 4's "search performance reporting" and Phase 6 have no data
source; search visibility cannot be measured at all.

### H5 — Legacy duplicate URLs return 200 instead of redirecting *(High)*

`config/urls.py:66-71` mounts legacy aliases that serve the **same views** as the
canonical `/shop/...` routes, with identical self-referential canonicals and no
301:

| Legacy URL | Canonical equivalent | Verified status |
|---|---|---|
| `/states/` | `/shop/states/` | 200 / 200 |
| `/states/<slug>/` | `/shop/state/<slug>/` | 200 |
| `/states/<s>/<l>/` | `/shop/state/<s>/<l>/` | 200 |
| `/products/<slug>/` | `/shop/product/<slug>/` | 200 |
| `/shop/<slug>/` | `/shop/category/<slug>/` | 200 |

*Impact:* the same content is reachable at two URLs, each canonicalising to
itself. (The legacy paths were kept "stable for shared links" per
`docs/UI_UX_SPEC.md` §5.2, so the fix is a 301 to the canonical target, not
deletion.)

### M1 — `noindex` missing on account, cart and utility pages *(Medium)*

Verified: `/cart/` (200), `/training/verify/` (200), `/accounts/login/` (200)
and `/accounts/register/` (200) all render **without** a `robots` meta tag.
`/checkout/` redirects (302) for anonymous users. `templates/dashboard/base.html`
is a separate base template with **no** robots, canonical, description or OG
tags at all. `templates/400.html`, `403.html` and `errors/429.html` also lack
`noindex` (only `404.html:4` sets it).

*Impact:* `/cart/` is session-specific and indexable; authentication pages are
indexable; the staff dashboard relies solely on `robots.txt` disallow, which is
advisory and not enforced.

### M2 — `og:image` is a relative URL and is never set for products or blog posts *(Medium)*

`templates/base.html:19` emits `{{ seo_og_image.file.url }}`, which is relative
(`/media/...`); Open Graph requires an absolute URL. Additionally,
`apps/cms/views.py:51` falls back to `hero_image`, but `BlogPost` has
`featured_image`, not `hero_image` — so **blog posts never get an `og:image`**
despite having one. `apps/catalog/views.py:24-33` has no `seo_og_image` key at
all, so **no product or category page gets an `og:image`**.

*Impact:* every social share of a product, category or article renders without
an image.

### M3 — `og:type` is hardcoded `website` *(Medium)*

`templates/base.html:14`. Blog posts should be `article` (with `article:*`
tags); product pages should be `product`. Currently every page — including a
single product and a single article — advertises `og:type=website`.

### M4 — `<title>` always appends the site name, defeating the override *(Medium)*

`templates/base.html:6` unconditionally appends `· {{ site.site_name }}`. The
CMS `meta_title` field is `max_length=70` with help text *"Overrides the page
title in search results (≈60 characters)"* (`apps/cms/models.py:157-161`) — but a
70-character override becomes a ~85-character `<title>`, which search engines
truncate. Separately, any child template using `{% block title %}` (all error
and auth pages) bypasses `seo_title` entirely.

### M5 — Three divergent `_seo()` helpers and two field-naming conventions *(Medium)*

| App | Helper | Keys provided |
|---|---|---|
| `apps/cms/views.py:23-38` | `_seo()` / `_content_seo()` | title, description, canonical, og_image, noindex |
| `apps/catalog/views.py:24-33` | `_seo()` | title, description, noindex — **no og_image**, `canonical` accepted but never passed |
| `apps/training/views.py:29-30` | `_seo()` | title, description **only** — no canonical, no noindex, no og_image |

Naming: CMS uses `meta_title`/`meta_description`; catalogue uses
`seo_title`/`seo_description`. Any expansion must consolidate these behind one
shared module (e.g. `apps/seo/`) and one adapter, rather than adding a fourth
variant. `apps/training` in particular currently emits an unparameterised
self-canonical on every page.

### M6 — `robots.txt` disallow list is incomplete *(Medium)*

`apps/cms/views.py:244-253` disallows `/dashboard/`, `/admin/`, `/account/`,
`/accounts/`, `/i18n/`. Not disallowed: `/orders/`, `/payments/`, `/invoices/`,
`/receipts/`, `/quotations/`, `/cart/`, `/checkout/`, `/training/verify/`,
`/internal/`, `/healthz/`, `/shop/search`, `/shop/compare` and `/media/`
(which nginx default-denies but robots does not describe).

### M7 — No sitemap index; single 50k-URL ceiling *(Medium)*

`config/urls.py:20` serves a flat urlset. Django's `sitemaps.views.index` is not
used. Not urgent at current volume, but adding catalogue and training content
calls for a `<sitemapindex>` with per-section children and correct `lastmod`.

### M8 — Product has no canonical/og_image/noindex; listings have no slug *(Medium)*

`Product` (`apps/catalog/models.py:357-454`) has `seo_title`/`seo_description`
but no equivalent of the CMS `SEOModel` (`canonical_url`, `og_image`,
`noindex`). `ProductListing` (the origin-specific price/stock record) has no
slug, so per-state/per-LGA offers are not independently addressable. Extending
models is permitted by the brief **only where necessary** — this should be
minimal and additive.

### L1 — Thin state/LGA pages; `BlogCategory` has a slug but no SEO fields *(Low)*

`/shop/state/<slug>/` and `/shop/state/<s>/<l>/` use auto-generated titles and
one-line descriptions (`apps/catalog/views.py:233-237, 266-268`), are not in the
sitemap, and have no SEO fields (`apps/locations/models.py:75,103`).
`BlogCategory` has `slug` but no `meta_title`/`meta_description`.

### L2 — Error pages inherit the site-wide description; 404 loses OG/canonical *(Low)*

`templates/404.html:4` overrides the entire `{% block meta %}`, so description,
canonical and all OG/Twitter tags disappear. `400.html`, `403.html`,
`errors/429.html` inherit the homepage's default description.

### L3 — Missing secondary social/locale tags *(Low)*

No `og:image:alt`, `og:locale`, `og:image:width/height`, `twitter:site`,
`twitter:image` or `article:*`. No `hreflang` despite `en`/`ha` i18n
(`config/settings/base.py:276-279`) — out of scope unless multilingual SEO is
wanted; flagged for a decision.

### L4 — No CMS SEO dashboard surface *(Low)*

`apps/cms/dashboard_urls.py` has no sitemap preview, metadata overview or SEO
health screen. This is Phase 4's subject.

### L5 — Test coverage gaps *(Low)*

`tests/test_cms_public.py:380-421` asserts tag *presence* only. There is no test
for the canonical **value**, `og:image`, `og:url`, `noindex` rendering, the
catalogue sitemap (does not exist), sitemap exclusion of drafts for pages/blog
(only services), the fuller robots list, or JSON-LD.

---

## 4. Public vs non-public URL inventory (for sitemap and robots safety)

**Eligible for the sitemap (public, indexable):**
`/`, `/services/`, `/services/<slug>/`, `/about/`, `/contact/`, `/news/`,
`/news/<slug>/`, `/faqs/`, `/pages/<slug>/`, `/training/`, `/training/courses/`,
`/training/courses/<slug>/`, `/training/categories/<slug>/`,
`/training/sessions/`, `/training/sessions/<uuid:pk>/`, `/shop/`,
`/shop/categories/`, `/shop/category/<slug>/`, `/shop/product/<slug>/`,
`/shop/states/`, `/shop/state/<slug>/`, `/shop/state/<state>/<lga>/`.

**Must never enter a sitemap** (all verified as installed prefixes):
`/admin/`, `/i18n/`, `/healthz/`, `/internal/`, `/dashboard/**`, `/account/**`,
`/accounts/**` (incl. `/accounts/mfa/`), `/cart/`, `/checkout/`,
`/orders/**`, `/payments/**`, `/invoices/**`, `/receipts/**`, `/quotations/**`,
`/shop/search`, `/shop/compare`, `/shop/lga-options`,
`/training/verify/**`, `/training/payments/callback/**`.

---

## 5. Live-site verification status

An attempt to fetch `https://aa-shinaka-digital-platform.onrender.com/robots.txt`
and `/sitemap.xml` during this audit **failed with DNS resolution errors and one
timeout**, so the live rendering could not be re-confirmed in this session. The
homepage was confirmed serving `200` with a hashed stylesheet earlier in the
same workstream. All defect reproductions above were performed against the local
application and are authoritative for the code as committed at `12a5e54`.

**Not verified:** live `robots.txt`/`sitemap.xml` response bodies, live response
headers (`X-Robots-Tag`), real crawl behaviour, Lighthouse/Core Web Vitals and
any Google-side indexing state. These require a reachable host and are carried
forward.

---

## 6. Proposed implementation plan (Phases 2–7)

Each phase ends with `ruff check` → `ruff format --check` → `pytest` →
`manage.py check` (+ `makemigrations --check` when models change), a focused
report, and a commit. **No phase deploys, and no phase enables live Paystack.**

### Phase 2 — SEO foundations
- Add a shared `apps/seo/` module: one `seo_context()` builder and one adapter
  that reads both `meta_*` (CMS) and `seo_*` (catalogue) fields, replacing the
  three divergent `_seo()` helpers (**fixes M5**).
- Strip query strings from canonicals; add explicit `canonical` for paginated
  and faceted pages (`?page=N` → base URL; filters → base category/state URL)
  (**fixes H2**).
- Add `noindex, follow` to account/cart/auth/utility pages and to the dashboard
  base; complete the error pages' `noindex` (**fixes M1**).
- Make `og:image` absolute and add `og:type` variants, `og:image:alt`,
  `og:locale`, `twitter:image`; fix the blog `featured_image` fallback
  (**fixes M2, M3, L3**).
- Make `meta_title` a true override and guard `<title>` length (**fixes M4**).
- 301 the legacy catalogue aliases to their canonical `/shop/...` targets
  (**fixes H5**) — preserving inbound links.
- Extend `robots.txt` with the full disallow list and an explicit sitemap
  reference (**fixes M6**).
- Add the `Organization`, `WebSite` + `SearchAction` and `BreadcrumbList`
  JSON-LD blocks using real `SiteSetting` data (**starts H3**).
- Add catalogue + training sitemaps and a `<sitemapindex>` (**fixes H1, M7**).

### Phase 3 — Product and service optimisation
- Add only the minimal additive catalogue fields needed (`canonical_url`,
  `og_image`, `noindex`) mirroring `SEOModel`; add a slug to `ProductListing`
  only if per-origin pages are wanted (**addresses M8**) — **decision needed**.
- Enrich state/LGA and category metadata using real catalogue data; enforce
  `ProductImage.alt_text` on publish (**addresses L1**).
- `Product` + `Offer` JSON-LD with accurate availability from
  `ProductListing.available_stock` / `in_stock`, and `Course` JSON-LD.
- Wholesale/export inquiry content blocks where they already exist in the
  model set. Preserve all existing products, URLs and order relationships.

### Phase 4 — Search Visibility dashboard
- Permission-protected screens (existing staff capability model): SEO overview,
  page metadata manager, product SEO health, sitemap status, redirect report,
  content recommendations.
- **Disconnected states are shown explicitly** until Search Console is
  connected; no invented metrics.

### Phase 5 — Answer-friendly content
- Extend the CMS with FAQs (model exists), buying guides, storage/handling,
  wholesale and export explanations, and original articles.
- Emit `FAQPage`, `Article` and `HowTo`-style JSON-LD where the content
  genuinely matches. All copy is factual, editorially reviewed and owner-signed.

### Phase 6 — Analytics integration
- Google Search Console via OAuth or a narrowly scoped service account, storing
  credentials in the environment (never in Git), reporting clicks, impressions,
  CTR, position and indexing status — **only when configured**.
- **No** OpenAI/Anthropic/Google/Perplexity "AI analytics" will be claimed; no
  supported integration exists, so those panels will state that plainly.

### Phase 7 — Testing and production readiness
- Automated tests for metadata rendering, canonical values, sitemap accuracy
  and exclusion, `robots.txt`, JSON-LD validity, dashboard permissions, public
  route regressions, catalogue/checkout regressions, and SEO dashboard access.
- Migration plan, rollback instructions and release notes.

---

## 7. Owner decisions required before Phase 2

1. **Catalogue model changes.** Phase 3 proposes adding `canonical_url`,
   `og_image` and `noindex` to `Product` (and a slug to `ProductListing`) to
   match the CMS. Confirm this additive change is acceptable, or restrict
   Phase 3 to non-schema work.
2. **State/LGA pages.** Include thin state/LGA pages in the sitemap, or
   consolidate them and keep them out until they carry real content?
3. **`hreflang`.** Is multilingual SEO (English/Hausa) in scope? If not, it
   will be documented as deliberately deferred.
4. **Feedback loop.** Each phase will be reported and committed separately, and
   will pause for approval before the next begins. Confirm that cadence.

---

## 8. Constraints honoured by this phase

- No application code changed; the repository is unchanged apart from this
  document.
- No deployment, no DNS change, no live Paystack credential, no production
  secret touched.
- No business logic, DB model, authentication, payment or deployment
  configuration altered.
- No ranking or AI-citation guarantee is made anywhere.

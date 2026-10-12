# UI/UX Specification
## AA Shinaka Digital Business Platform

| | |
|---|---|
| Document ID | AASDP-UX-001 |
| Version | 0.4 (Phase 1–4) |
| Status | For owner/design review |

> **Design intent.** A **premium agricultural business interface**: trustworthy,
> clean, professional, mobile-first (most Nigerian traffic is mobile), with
> generous whitespace, a restrained green brand palette, and real agricultural
> photography. Content that is not yet supplied by the owner appears as an
> explicit empty state — never as invented facts, prices or achievements.

---

## 1. Design principles

1. **Trust first.** Clear provenance (state/LGA), clear pricing, clear status.
2. **Mobile-first.** Design at 360 px, scale up. Tap targets ≥ 44 px.
3. **Progressive enhancement.** Core browsing, forms and checkout work without
   JavaScript; HTMX/Alpine add polish.
4. **Consistency.** One component vocabulary; no bespoke one-off widgets.
5. **Accessible.** WCAG 2.1 AA: contrast, focus, labels, semantics, keyboard.
6. **Honest.** No fake numbers, reviews or achievements; empty states instead.

---

## 2. Brand & foundations

| Token | Value (to be finalised by owner) |
|---|---|
| Primary (brand) | Deep agricultural green ramp `--color-brand-50…950` (see `static/src/app.css`) |
| Neutral | `stone` scale |
| Accent | Amber (status/warning), red (error) — semantic only |
| Font | `Inter` (system fallback), headings semibold |
| Radius | `rounded-md` (controls), `rounded-xl` (cards) |
| Elevation | `shadow-sm` default, `shadow-md` on hover |
| Spacing | Tailwind 4 px scale |

Components are defined in Tailwind utility classes; shared snippets live in
`templates/components/`.

---

## 3. Responsive breakpoints & layout

| Breakpoint | Width | Layout |
|---|---|---|
| base | < 640 | single column, hamburger nav, stacked cards |
| `sm` | ≥ 640 | 2-column grids |
| `lg` | ≥ 1024 | 3–4 column product grids, sidebar filters |
| `xl` | ≥ 1280 | max-width 1280 container, wider dashboards |

Container: `mx-auto max-w-7xl px-4`. Vertical rhythm via `py-14`/`py-16`
sections.

---

## 4. Global chrome

- **Header (`components/navbar.html`)** — logo/wordmark, primary nav
  (Home, Products, Services, Academy, Export), auth actions or account menu,
  mobile drawer. Sticky, blurred, border-bottom.
- **Footer (`components/footer.html`)** — brand blurb, division links,
  company/legal links, contact block (owner-supplied details), copyright.
- **Messages** — colour-coded banners for success/error/warning/info.
- **Skip link** to `#main` for keyboard users.
- **Breadcrumbs** on all catalogue and request pages.

---

## 5. Public pages

Legend: **[P1]** exists in Phase 1 · **[Pn]** planned.

### 5.1 Home `/` **[P3 delivered — CMS-driven]**

Required sections (owner-mandated):

1. **Hero** — value proposition, two CTAs (Shop products / Book a service).
2. **Product category cards** — grid of data-driven categories with imagery.
3. **Shop by state** — state selector / grid linking to state pages.
4. **Origin-specific product listings** — featured listings showing state + LGA.
5. **Consultancy** — what we offer + CTA.
6. **Farming services** — services summary + CTA.
7. **Marketing** — market-linkage summary + CTA.
8. **Storage & warehousing** — facilities summary + CTA.
9. **Export** — destinations/international focus + enquiry CTA.
10. **Training / Academy** — featured courses + CTA.
11. **Trust strip** — standards, provenance, contact (owner-supplied claims only).

**Phase 3 delivered** the full premium homepage (`templates/home.html`): the
sections above plus hero banners, business divisions, service previews,
testimonials (staff-approved), FAQs, blog teaser, stats/value props, newsletter/
contact CTA and footer — all rendered from `apps.cms` via `site_context` and
`cms_tags`. Sections 2–4 (categories, shop-by-state, featured products) now
render **live catalogue data** via the `cms` selectors and `catalog_tags`; when
the catalogue is empty they fall back to the same empty states with CTAs — no
duplicated models, no placeholder prices or stock. Section 10 renders course
cards from CMS content only (no invented fees). Sections are data-driven;
nothing is hardcoded in the template.

### 5.2 Catalogue

> **Phase 4 delivered.** The public catalogue is live under `/shop/`, with the
> legacy `/states/…`, `/products/<slug>/` and `/shop/<slug>/` aliases resolving
> to the same views. Product/category/state pages are data-driven; prices,
> stock, packaging and categories are rows, never template constants.

| Page | Path | Purpose |
|---|---|---|
| Shop index | `/shop/` | featured listings, top categories, shop-by-state |
| Category index | `/shop/categories/` | top-level categories + search |
| Category detail | `/shop/category/<slug>/` | subcategory grid + product grid, filters (origin, price band, availability) |
| Shop by state | `/shop/states/` | all active states (from location data) |
| State page | `/shop/state/<slug>/` | LGA filter + listings originating in that state |
| LGA page | `/shop/state/<state>/<lga>/` | listings for that LGA |
| Search results | `/shop/search/` | query + facets (price band, in-stock, sort) |
| Compare | `/shop/compare/` | side-by-side comparison of published products only |
| Product detail | `/shop/product/<slug>/` | gallery, description, **origin listings table** (state, LGA, package, price, availability), compare/add-to-cart CTA |

Product detail must make origin, package size and price unambiguous; each row
is an independent listing. Draft/archived products and inactive categories are
never listed (404 on direct access), and only listings with available stock are
shown by default (FR-LOC-6).

Staff manage the catalogue under `/dashboard/catalog/` (categories, products,
images, listings, prices, variants, wholesale tiers, market references, stock)
and see low-stock items under `/dashboard/inventory/`.

### 5.3 Division landing pages

**Phase 3 (delivered):** the public division pages are CMS-driven and live at
`/services/` (index) and `/services/<slug>/` (detail) for consultancy, farming,
marketing, storage and export — each with hero, intro, benefits/steps, service
categories, FAQs and a CTA that links to `/contact/`. Request/enquiry **forms**
for these divisions arrive with the service pipelines (Phase 7); until then the
CTA routes to the stored contact form.

`/consultancy/`, `/farming-services/`, `/marketing/`, `/storage/`, `/export/`,
`/training/` (Phase 7/8 paths) — each: hero, offering summary, process/how-it-works, FAQ,
request/enquiry CTA form.

### 5.4 Request & enquiry forms

| Form | Fields (indicative) |
|---|---|
| Consultancy | topic, crop, mode (phone/onsite/online), state/LGA, notes, preferred date |
| Farming service | service type, farm location, acreage, schedule, notes |
| Marketing | produce, volume + unit, target market, notes |
| Storage | produce, quantity + unit, duration, facility preference, notes |
| Export enquiry | product, volume + unit, destination country, incoterms, target date, notes |
| Training enrollment | cohort selection, trainee details, notes |

All forms: inline validation, required-field indicators, helpful errors,
loading/disabled submit state, confirmation screen with reference number.

### 5.5 Cart & checkout

- Cart: line items with origin/package, quantity stepper, availability warnings,
  subtotal, proceed CTA.
- Checkout: address selection/entry, contact, notes, order summary, payment step
  (placeholder until Paystack phase).
- Confirmation: order number, summary, next steps.

### 5.6 Static & legal

About, Contact, FAQs, Terms, Privacy, Returns/Refunds policy. Content supplied
by the owner; placeholders until then.

**Phase 3 (delivered):** About (`/about/`), Contact (`/contact/` — stored,
honeypot-protected enquiry with WhatsApp, address/map and social links from
`SiteSetting`), FAQs (`/faqs/`), Blog (`/news/`) and CMS pages (`/pages/<slug>/`
for terms/privacy/custom) all render from `apps.cms`. Copy is owner-supplied
through the CMS dashboard; templates never hardcode claims.

### 5.7 Auth

Sign in, sign up, password reset (request/done/confirm/complete), email
verification. Simple centred card, accessible inputs.

---

## 6. Customer portal

> **Phase 2 delivered:** the portal home, profile, addresses and security pages
> live under `/account/`. Orders, requests and training pages arrive with their
> domain phases (4, 6 and 7).

| Page | Path | Purpose |
|---|---|---|
| Portal home | `/account/` | summary cards: recent orders, open requests, notifications |
| Orders | `/account/orders/` | order list with status filters |
| Order detail | `/account/orders/<number>/` | items, timeline, payment status, actions |
| Requests | `/account/requests/` | all service requests by division and status |
| Request detail | `/account/requests/<ref>/` | details + status history |
| Enrollments | `/account/training/` | enrolled courses/cohorts |
| Profile | `/account/profile/` | name, phone, state/LGA, marketing consent |
| Addresses | `/account/addresses/` | CRUD, set default |
| Security | `/account/security/` | change password, sessions |

Navigation: portal sidebar/tabs, responsive; active-state indicator; empty
states with CTAs.

---

## 7. Staff dashboard

> **Phase 2 delivered:** dashboard home, staff management (`/dashboard/staff/`)
> and the audit log (`/dashboard/audit/`). Catalogue/inventory/orders/etc.
> arrive with their domain phases. Role audiences use the ten canonical roles
> (see `docs/SRS.md` §3.2).

| Area | Path | Audience |
|---|---|---|
| Dashboard home | `/dashboard/` | all staff — role-aware KPIs + queues |
| Catalogue | `/dashboard/catalog/…` | Sales Officer / Inventory Officer / Content Editor / Administrator / Owner |
| Categories | `/dashboard/catalog/categories/` | nested tree management |
| Products | `/dashboard/catalog/products/` | CRUD, images, publish |
| Listings | `/dashboard/catalog/listings/` | origin, package, price, stock |
| Inventory | `/dashboard/inventory/` | Inventory Officer — movements, adjustments, low stock |
| Orders | `/dashboard/orders/` | Sales/Inventory/Finance — fulfilment queue, status transitions |
| Payments | `/dashboard/payments/` | Finance Officer — payments + refunds |
| Requests | `/dashboard/requests/<division>/` | per-division queues |
| Storage | `/dashboard/storage/` | Inventory Officer — facilities, intake/release records |
| Export | `/dashboard/export/` | Export Officer — enquiry pipeline + quotations |
| Training | `/dashboard/training/` | Training Manager — courses, cohorts, enrollments |
| Staff | `/dashboard/staff/` | Administrator/Owner — staff creation, roles, activation |
| Reports | `/dashboard/reports/` | Chart.js dashboards + filters |
| Audit | `/dashboard/audit/` | searchable audit log (Administrator/Owner; view for Finance) |

Dashboard chrome: fixed sidebar (collapsible on mobile), topbar with user menu,
breadcrumbs. Tables are dense, sortable, paginated, with filter chips and bulk
actions where relevant.

---

## 8. Component library (shared)

- `navbar`, `footer`, `breadcrumbs`, `messages`
- `button` (primary/secondary/ghost/danger, sizes, loading state)
- `input`, `select`, `textarea`, `checkbox`, `radio`, `field_error`, `help_text`
- `card`, `stat_card`, `empty_state`, `badge` (status colours), `avatar`
- `product_card` (image, name, origin, price-from, availability)
- `listing_row` (origin, package, price, stock, add-to-cart)
- `category_card`, `state_card`
- `table`, `pagination`, `filter_bar`, `modal`, `tabs`, `toast`
- `form_layout` wrapper for consistent spacing/labels
- Chart wrappers (`line_chart`, `bar_chart`, `doughnut_chart`) for Chart.js

Every component documents its context variables and accessibility contract.

---

## 9. Forms & validation UX

- Labels above inputs, always visible (no placeholder-as-label).
- Required fields marked; optional fields labelled “(optional)”.
- Errors inline, adjacent to the field, with `aria-describedby`; summary at the
  top for long forms.
- Disable submit + show spinner during HTMX requests; re-enable on error.
- Preserve user input on validation failure.
- Server-side validation is authoritative; client hints are advisory.

---

## 10. Interaction patterns (HTMX & Alpine)

- **HTMX** — live search, filter updates, pagination, add-to-cart, request-form
  submission, dashboard queue refresh, status transitions. Returns partials.
- **Alpine** — mobile nav, dropdowns, tabs, quantity steppers, image gallery,
  modal open/close, password visibility toggle.
- Loading indicators via `hx-indicator`; out-of-band updates for cart count.
- Ensure non-JS fallback: plain links/forms reach the same routes.

---

## 11. States & feedback

| State | Treatment |
|---|---|
| Empty | Illustration/icon + explanation + primary CTA |
| Loading | Skeleton for lists; spinner in buttons/HTMX targets |
| Error | Inline field errors; page-level alert for failures; retry where safe |
| Success | Toast/banner + updated content |
| Permission denied | 403 page with explanation and safe navigation |
| Not found | 404 page with search/links |
| Empty results (filters) | “No products match” + reset filters |

---

## 12. Accessibility checklist

- Semantic landmarks (`header`, `nav`, `main`, `footer`) and heading order.
- Colour contrast ≥ 4.5:1 for text; focus rings never removed.
- All images have `alt`; decorative images `alt=""`.
- Forms: label ↔ input association, error announcement via ARIA.
- Keyboard-operable menus, modals (focus trap), and steppers.
- Status conveyed by text/icon, not colour alone.
- Respect `prefers-reduced-motion` for non-essential animation.

---

## 13. SEO & metadata

- Unique `<title>` and meta description per page; Open Graph tags on product and
  division pages.
- Canonical URLs; clean slugs; `sitemap.xml` and `robots.txt` (later phase).
- Structured data (`Product`, `Course`, `Organization`) in later phase.

**Phase 3 (delivered):** `templates/base.html` emits unique title/description
(from the CMS SEO fields with safe fallbacks), canonical link, Open Graph/Twitter
tags and `noindex` support; `/sitemap.xml` lists only published content and
`/robots.txt` points to it. Semantic landmarks, image `alt`, `loading="lazy"`
below the fold, `fetchpriority="high"` on the hero and paginated lists are
implemented. Structured data stays a later phase.

---

## 14. Performance UX

- Lazy-load images below the fold; responsive image sizes.
- Paginate all lists; avoid layout shift with fixed media aspect ratios.
- HTMX partials keep navigations snappy without full reloads.
- Chart.js charts render from server-provided data, not client-side aggregation.

---

## 15. Content requirements from the owner

The following are **placeholders** until supplied by the owner (never invented):

- Legal/company name, registration details, addresses, phone/WhatsApp, email.
- Verified achievements, certifications, partners, export destinations served.
- Product imagery, category imagery, and per-listing provenance copy.
- Division descriptions, FAQs and policies (terms, privacy, refunds, delivery).

---

## 16. Language & i18n readiness (Phase 3)

- English is the default language (`LANGUAGE_CODE=en`); Hausa is registered as
  `ha` with `LocaleMiddleware` and `i18n_patterns`-free URL handling, so a
  language switch can be added without re-routing.
- Templates use `{% translate %}`/`{% trans %}` for chrome and shared strings;
  **no translated strings are hardcoded** in templates or Python.
- The catalogue `locale/ha/LC_MESSAGES/django.po` (compiled by
  `manage.py compile_messages`, no GNU gettext required) ships an initial set of
  curated messages.
- **Full bilingual support is not claimed**: CMS body content, blog posts and
  owner copy remain English-only until an authoring workflow for Hausa content
  is approved. Language switching UI is intentionally deferred.

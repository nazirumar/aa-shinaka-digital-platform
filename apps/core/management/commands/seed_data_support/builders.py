"""Domain seeders for the ``seed_data`` management command.

Each public ``seed_*`` function is **idempotent**: it creates a record
only when it is missing and never overwrites content a human has
edited. Money and quantities arrive as strings from :mod:`.content`
and are converted to ``Decimal`` here, so no float ever enters the
pipeline.

Catalogue writes (products, listings, images, prices, wholesale tiers,
stock, market references and warehouses) go through the
``apps.catalog`` service layer so the price/stock invariants and the
audit log are always honoured. Shipping configuration goes through the
``apps.orders`` service layer. Everything else (CMS, services config,
training config, export config) is reference data with no invariants,
so it is written with the ORM directly.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.accounts.models import Address, User, UserRole
from apps.accounts.roles import sync_role_groups, sync_user_groups
from apps.catalog import services as catalog_services
from apps.catalog.models import (
    Category,
    ListingStatus,
    Product,
    ProductListing,
    PublishStatus,
    StockMovementKind,
    Warehouse,
)
from apps.cms.models import (
    FAQ,
    BusinessDivision,
    HeroBanner,
    MediaAsset,
    NavigationItem,
    Page,
    PageType,
    ServiceCategory,
    ServicePage,
    SiteSetting,
    TeamMember,
    Testimonial,
)
from apps.cms.models import (
    PublishStatus as CmsPublishStatus,
)
from apps.export.models import (
    ApprovalStatus,
    ExportDestination,
    ExportDestinationRequirement,
    ExportDocumentRequirement,
    ExportDocumentType,
    ExportProductProfile,
    ExportTradeRestriction,
    LogisticsProvider,
)
from apps.locations.models import LGA, Country, State
from apps.orders import services as order_services
from apps.orders.models import Cart, CartStatus, ShippingMethod, ShippingRate, ShippingZone
from apps.services.models import (
    ConsultancyService,
    FarmingService,
    MarketingService,
    ProduceType,
    StorageFacility,
    StorageUnit,
)
from apps.training.models import (
    CertificateTemplate,
    Course,
    CourseLesson,
    CourseModule,
    CourseStatus,
    DeliveryMode,
    InstructorAssignment,
    InstructorProfile,
    TrainingCategory,
    TrainingSession,
    TrainingVenue,
)

from . import content

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
LOCATIONS_CSV = DATA_DIR / "nigeria_locations_seed.csv"


def D(value) -> Decimal:
    """Coerce a string/number to ``Decimal`` (never a float)."""
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _count_location_rows(csv_path: Path) -> tuple[int, int]:
    """Return ``(unique_states, lga_rows)`` for the bundled CSV."""
    import csv

    states: set[str] = set()
    lgas = 0
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            state = (row.get("state_name") or "").strip()
            lga = (row.get("lga_name") or "").strip()
            if state:
                states.add(state)
            if lga:
                lgas += 1
    return len(states), lgas


class SeedContext:
    """Shared state for one seed run (caches, flags and counters)."""

    def __init__(self, *, command, library, with_demo_records, force_images, verbosity):
        self.command = command
        self.stdout = command.stdout
        self.style = command.style
        self.library = library
        self.with_demo_records = with_demo_records
        self.force_images = force_images
        self.verbosity = verbosity
        self.counts: Counter = Counter()
        self.notes: list[str] = []
        # identity caches
        self._states: dict[str, State] = {}
        self._lgas: dict[tuple[str, str], LGA] = {}
        self._media: dict[str, MediaAsset] = {}
        self._users: dict[str, User] = {}
        self._units: dict[str, object] = {}
        self._warehouses: dict[str, Warehouse] = {}
        self._categories: dict[str, Category] = {}
        self._products: dict[str, Product] = {}
        self._service_pages: dict[str, ServicePage] = {}
        self._courses: dict[str, Course] = {}
        self._venues: dict[str, TrainingVenue] = {}
        self._destinations: dict[str, ExportDestination] = {}
        self._doc_types: dict[str, ExportDocumentType] = {}
        self._admin: User | None = None

    # -- output ---------------------------------------------------------
    def log(self, message: str, *, verbosity: int = 1) -> None:
        if self.verbosity >= verbosity:
            self.stdout.write(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def bumped(self, key: str, amount: int = 1) -> None:
        self.counts[key] += amount

    # -- identity resolvers ---------------------------------------------
    def admin_user(self) -> User | None:
        return self._admin

    def state(self, code: str, *, required: bool = True) -> State | None:
        code = (code or "").strip().upper()
        if code in self._states:
            return self._states[code]
        state = State.objects.filter(code__iexact=code).first()
        if state is None and required:
            raise CommandError(
                f"State '{code}' is missing. Run without --skip-locations (or run "
                "import_nigeria_locations) so the seeder can reference it."
            )
        self._states[code] = state
        return state

    def lga(self, state_code: str, name: str, *, required: bool = True) -> LGA | None:
        state = self.state(state_code, required=required)
        if state is None:
            return None
        key = (state.code, (name or "").strip().lower())
        if key in self._lgas:
            return self._lgas[key]
        lga = LGA.objects.filter(state=state, name__iexact=name).first()
        if lga is None:
            # Fall back to the first LGA of the state so a listing always has a
            # valid origin even when the bundled dataset lacks the exact LGA.
            lga = LGA.objects.filter(state=state).order_by("name").first()
            if lga is not None:
                self.note(
                    f"LGA '{name}' not in the location dataset; using "
                    f"'{lga.name}' ({state.code}) as the origin."
                )
        if lga is None and required:
            raise CommandError(f"No LGA found for state '{state_code}'.")
        self._lgas[key] = lga
        return lga

    def user(self, email: str) -> User | None:
        if email in self._users:
            return self._users[email]
        user = User.objects.filter(email__iexact=email).first()
        self._users[email] = user
        return user

    def unit(self, code: str):
        code = (code or "").strip()
        if code in self._units:
            return self._units[code]
        unit = catalog_services.ensure_unit(code)
        self._units[code] = unit
        return unit

    def warehouse(self, code: str) -> Warehouse | None:
        code = (code or "").strip()
        if code in self._warehouses:
            return self._warehouses[code]
        warehouse = Warehouse.objects.filter(code__iexact=code).first()
        self._warehouses[code] = warehouse
        return warehouse

    def category(self, name: str, parent: Category | None = None) -> Category | None:
        key = f"{parent.name if parent else ''}/{name}"
        if key in self._categories:
            return self._categories[key]
        queryset = Category.all_objects.filter(name__iexact=name)
        if parent is None:
            category = queryset.filter(parent__isnull=True).first()
        else:
            category = queryset.filter(parent=parent).first()
        self._categories[key] = category
        return category

    def product(self, name: str) -> Product | None:
        if name in self._products:
            return self._products[name]
        product = Product.all_objects.filter(name__iexact=name).first()
        self._products[name] = product
        return product

    def service_page(self, slug: str) -> ServicePage | None:
        if slug in self._service_pages:
            return self._service_pages[slug]
        page = ServicePage.objects.filter(slug__iexact=slug).first()
        self._service_pages[slug] = page
        return page

    def course(self, title: str) -> Course | None:
        if title in self._courses:
            return self._courses[title]
        course = Course.objects.filter(title__iexact=title).first()
        self._courses[title] = course
        return course

    def venue(self, name: str) -> TrainingVenue | None:
        if name in self._venues:
            return self._venues[name]
        venue = TrainingVenue.objects.filter(name__iexact=name).first()
        self._venues[name] = venue
        return venue

    def destination(self, country_code: str) -> ExportDestination | None:
        code = (country_code or "").strip().upper()
        if code in self._destinations:
            return self._destinations[code]
        destination = ExportDestination.objects.filter(country_code__iexact=code).first()
        self._destinations[code] = destination
        return destination

    def doc_type(self, code: str) -> ExportDocumentType | None:
        code = (code or "").strip()
        if code in self._doc_types:
            return self._doc_types[code]
        doc_type = ExportDocumentType.objects.filter(code__iexact=code).first()
        self._doc_types[code] = doc_type
        return doc_type

    # -- media --------------------------------------------------------
    def media(
        self,
        key: str,
        *,
        title: str,
        alt: str = "",
        filename: str | None = None,
    ) -> MediaAsset:
        """Return a reusable :class:`MediaAsset` for ``key``.

        The asset is created once (keyed on its title) and reused on
        every subsequent run; ``--force-images`` re-downloads and
        replaces the stored file in place.
        """
        if key in self._media:
            return self._media[key]
        asset = MediaAsset.objects.filter(title=title).first()
        if asset is None:
            name = filename or f"{key}.jpg"
            asset = MediaAsset.objects.create(
                file=self.library.image(key, filename=name),
                title=title,
                alt_text=alt,
                uploaded_by=self._admin,
            )
            self.bumped("media_asset")
        elif self.force_images:
            name = filename or f"{key}.jpg"
            asset.file.save(name, self.library.image(key, filename=name), save=True)
        self._media[key] = asset
        return asset


# ---------------------------------------------------------------------------
# Locations, roles & users
# ---------------------------------------------------------------------------


def seed_units(ctx: SeedContext) -> None:
    """Ensure the canonical units of measure exist (idempotent)."""
    from apps.catalog.models import UnitOfMeasure

    created = 0
    for name, code, symbol, sort_order in content.UNITS:
        _, was_created = UnitOfMeasure.objects.get_or_create(
            code=code, defaults={"name": name, "symbol": symbol, "sort_order": sort_order}
        )
        created += int(was_created)
    ctx.bumped("unit", created)
    if created:
        ctx.log(f"  · {created} units of measure created", verbosity=1)


def seed_locations(ctx: SeedContext, *, skip: bool = False) -> None:
    """Import the bundled Nigeria states + LGAs when the database is empty."""
    if skip:
        ctx.log("  · skipping location import (--skip-locations)", verbosity=1)
        return
    if not LOCATIONS_CSV.exists():
        raise CommandError(f"Bundled locations dataset not found: {LOCATIONS_CSV}")
    states, lgas = _count_location_rows(LOCATIONS_CSV)
    call_command(
        "import_nigeria_locations",
        source=str(LOCATIONS_CSV),
        expected_states=states,
        expected_lgas=lgas,
        verbosity=0,
    )
    ctx.bumped("state", State.objects.count())
    ctx.bumped("lga", LGA.objects.count())
    ctx.log(
        f"  · locations: {State.objects.count()} states, {LGA.objects.count()} LGAs",
        verbosity=1,
    )


def seed_roles_and_users(ctx: SeedContext) -> None:
    """Create the ten role groups and the seed staff + customer accounts."""
    groups = sync_role_groups()
    ctx.bumped("role_group", len(groups))

    for spec in content.USERS:
        email = spec["email"].lower()
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            extra = {
                "first_name": spec.get("first_name", ""),
                "last_name": spec.get("last_name", ""),
                "phone": spec.get("phone", ""),
                "role": spec["role"],
                "is_staff": bool(spec.get("is_staff", False)),
                "is_superuser": bool(spec.get("is_superuser", False)),
                "is_active": True,
                "is_email_verified": True,
            }
            state = ctx.state(spec["state"], required=False) if spec.get("state") else None
            if state is not None:
                extra["state"] = state
            if spec.get("is_superuser"):
                user = User.objects.create_superuser(
                    email=email, password=content.DEFAULT_DEMO_PASSWORD, **extra
                )
            else:
                user = User.objects.create_user(
                    email=email, password=content.DEFAULT_DEMO_PASSWORD, **extra
                )
            ctx.bumped("user")
        else:
            # Refresh editable profile fields but never the password or role.
            user.first_name = spec.get("first_name", "")
            user.last_name = spec.get("last_name", "")
            user.phone = spec.get("phone", "")
            state = ctx.state(spec["state"], required=False) if spec.get("state") else None
            user.state = state
            user.save(update_fields=["first_name", "last_name", "phone", "state"])
        sync_user_groups(user)
        ctx._users[email] = user
        if spec.get("is_superuser") and ctx._admin is None:
            ctx._admin = user

    # Default delivery addresses for the seeded customers.
    for spec in content.ADDRESSES:
        user = ctx.user(spec["email"])
        if user is None:
            continue
        state = ctx.state(spec["state"])
        lga = ctx.lga(spec["state"], spec["lga"])
        Address.objects.update_or_create(
            user=user,
            label=spec["label"],
            defaults={
                "recipient_name": spec["recipient_name"],
                "phone": spec["phone"],
                "state": state,
                "lga": lga,
                "city": spec["city"],
                "street_address": spec["street_address"],
                "landmark": spec.get("landmark", ""),
                "is_default": bool(spec.get("is_default", False)),
            },
        )
        ctx.bumped("address")

    ctx.log(
        f"  · {len(content.USERS)} accounts, {len(groups)} role groups, "
        f"{len(content.ADDRESSES)} addresses",
        verbosity=1,
    )


# ---------------------------------------------------------------------------
# Site configuration, navigation
# ---------------------------------------------------------------------------


def seed_site(ctx: SeedContext) -> None:
    """Site settings (with logo + favicon) and the header/footer navigation."""
    created = not SiteSetting.objects.filter(pk=1).exists()
    settings_obj = SiteSetting.load()
    spec = content.SITE_SETTINGS
    state = ctx.state(spec["state"], required=False)
    defaults = {
        "site_name": spec["site_name"],
        "tagline": spec["tagline"],
        "description": spec["description"],
        "announcement_text": spec["announcement_text"],
        "announcement_active": spec["announcement_active"],
        "phone": spec["phone"],
        "phone_secondary": spec["phone_secondary"],
        "whatsapp_number": spec["whatsapp_number"],
        "email": spec["email"],
        "address_line": spec["address_line"],
        "city": spec["city"],
        "state": state,
        "country": spec["country"],
        "facebook_url": spec["facebook_url"],
        "instagram_url": spec["instagram_url"],
        "twitter_url": spec["twitter_url"],
        "linkedin_url": spec["linkedin_url"],
        "youtube_url": spec["youtube_url"],
        "default_meta_title": spec["default_meta_title"],
        "default_meta_description": spec["default_meta_description"],
        "value_props": spec["value_props"],
        "logo": ctx.media("logo", title="AA Shinaka Logo", alt="AA Shinaka logo"),
        "favicon": ctx.media("favicon", title="AA Shinaka Favicon", alt="AA Shinaka favicon"),
    }
    if created:
        for field, value in defaults.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        ctx.bumped("site_setting")

    # Navigation.
    pages_by_slug = {page.slug: page for page in Page.objects.all()}
    service_pages_by_slug = {page.slug: page for page in ServicePage.objects.all()}
    nav_created = 0
    for entry in content.NAVIGATION:
        nav_created += _seed_navigation_item(
            ctx,
            entry,
            parent=None,
            pages_by_slug=pages_by_slug,
            service_pages_by_slug=service_pages_by_slug,
        )
    ctx.bumped("navigation_item", nav_created)
    ctx.log(f"  · site settings and {nav_created} navigation items", verbosity=1)


def _seed_navigation_item(
    ctx: SeedContext,
    entry: dict,
    *,
    parent: NavigationItem | None,
    pages_by_slug: dict,
    service_pages_by_slug: dict,
) -> int:
    label = entry["label"]
    placement = entry.get("placement", NavigationItem._meta.get_field("placement").default)
    sort_order = entry.get("sort_order", 0)
    url_name = entry.get("url_name", "")
    url = entry.get("url", "")
    page = None

    page_slug = entry.get("page")
    if page_slug:
        page = pages_by_slug.get(page_slug)
        if page is not None:
            url_name = ""
            url = ""
        else:
            service_page = service_pages_by_slug.get(page_slug)
            if service_page is not None:
                url = service_page.get_absolute_url()
                url_name = ""

    item, created = NavigationItem.objects.get_or_create(
        label=label,
        placement=placement,
        parent=parent,
        defaults={
            "url_name": url_name,
            "url": url,
            "page": page,
            "sort_order": sort_order,
            "is_active": True,
        },
    )
    count = int(created)
    for child in entry.get("children", []):
        count += _seed_navigation_item(
            ctx,
            child,
            parent=item,
            pages_by_slug=pages_by_slug,
            service_pages_by_slug=service_pages_by_slug,
        )
    return count


# ---------------------------------------------------------------------------
# CMS pages, heroes, divisions, service pages
# ---------------------------------------------------------------------------


def seed_pages(ctx: SeedContext) -> None:
    """Static CMS pages (About, Contact, Privacy, Terms) and hero banners."""
    for slug, title, page_type, summary, body, hero_key, featured in content.PAGES:
        hero = ctx.media(hero_key, title=f"{title} hero", alt=summary) if hero_key else None
        page, created = Page.objects.get_or_create(
            slug=slug,
            defaults={
                "title": title,
                "page_type": page_type,
                "summary": summary,
                "body": body,
                "hero_image": hero,
                "status": CmsPublishStatus.PUBLISHED,
                "published_at": timezone.now(),
                "is_featured": featured,
                "sort_order": 0,
            },
        )
        if created:
            ctx.bumped("page")

    for (
        title,
        eyebrow,
        subtitle,
        cta_label,
        cta_url,
        secondary_label,
        secondary_url,
        image_key,
        featured,
        sort_order,
    ) in content.HERO_BANNERS:
        slug = f"hero-{sort_order}"
        image = ctx.media(image_key, title=f"Hero: {title}", alt=subtitle)
        banner, created = HeroBanner.objects.get_or_create(
            slug=slug,
            defaults={
                "title": title,
                "eyebrow": eyebrow,
                "subtitle": subtitle,
                "cta_label": cta_label,
                "cta_url": cta_url,
                "secondary_cta_label": secondary_label,
                "secondary_cta_url": secondary_url,
                "image": image,
                "status": CmsPublishStatus.PUBLISHED,
                "published_at": timezone.now(),
                "is_featured": featured,
                "sort_order": sort_order,
            },
        )
        if created:
            ctx.bumped("hero_banner")
    ctx.log(
        f"  · {len(content.PAGES)} pages, {len(content.HERO_BANNERS)} hero banners", verbosity=1
    )


def seed_divisions_and_services(ctx: SeedContext) -> None:
    """Business divisions, their service pages, categories and FAQs."""
    divisions: dict[str, BusinessDivision] = {}
    for (
        name,
        short_description,
        description,
        icon,
        image_key,
        featured,
        sort_order,
    ) in content.DIVISIONS:
        slug = name.lower().replace(" & ", "-and-").replace(" ", "-")
        image = ctx.media(image_key, title=f"Division: {name}", alt=short_description)
        division, created = BusinessDivision.objects.get_or_create(
            slug=slug,
            defaults={
                "name": name,
                "short_description": short_description,
                "description": description,
                "icon": icon,
                "image": image,
                "status": CmsPublishStatus.PUBLISHED,
                "published_at": timezone.now(),
                "is_featured": featured,
                "sort_order": sort_order,
            },
        )
        divisions[name] = division
        if created:
            ctx.bumped("business_division")

    for (
        slug,
        division_name,
        title,
        eyebrow,
        intro,
        body,
        icon,
        hero_key,
        benefits,
        steps,
        sort_order,
    ) in content.SERVICE_PAGES:
        division = divisions.get(division_name)
        hero = ctx.media(hero_key, title=f"Service: {title}", alt=intro) if hero_key else None
        page, created = ServicePage.objects.get_or_create(
            slug=slug,
            defaults={
                "division": division,
                "title": title,
                "eyebrow": eyebrow,
                "intro": intro,
                "body": body,
                "hero_image": hero,
                "icon": icon,
                "benefits": benefits,
                "steps": steps,
                "cta_label": "Send an enquiry",
                "cta_url": "",
                "status": CmsPublishStatus.PUBLISHED,
                "published_at": timezone.now(),
                "is_featured": False,
                "sort_order": sort_order,
            },
        )
        ctx._service_pages[slug] = page
        if created:
            ctx.bumped("service_page")

    for service_slug, name, description, icon, sort_order in content.SERVICE_CATEGORIES:
        page = ctx.service_page(service_slug)
        if page is None:
            continue
        ServiceCategory.objects.get_or_create(
            service_page=page,
            name=name,
            defaults={"description": description, "icon": icon, "sort_order": sort_order},
        )
        ctx.bumped("service_category")

    service_page_slugs = [entry[0] for entry in content.SERVICE_PAGES]
    pages_by_slug = {slug: ctx.service_page(slug) for slug in service_page_slugs}
    for question, answer, service_slug, sort_order in content.FAQS:
        page = pages_by_slug.get(service_slug) if service_slug else None
        FAQ.objects.get_or_create(
            question=question,
            defaults={
                "answer": answer,
                "service_page": page,
                "sort_order": sort_order,
                "is_published": True,
            },
        )
        ctx.bumped("faq")

    ctx.log(
        f"  · {len(content.DIVISIONS)} divisions, {len(content.SERVICE_PAGES)} service pages, "
        f"{len(content.SERVICE_CATEGORIES)} service categories, {len(content.FAQS)} FAQs",
        verbosity=1,
    )


def seed_testimonials_and_team(ctx: SeedContext) -> None:
    for (
        author_name,
        author_role,
        company,
        quote,
        image_key,
        rating,
        featured,
        sort_order,
    ) in content.TESTIMONIALS:
        image = (
            ctx.media(image_key, title=f"Testimonial: {author_name}", alt=author_role)
            if image_key
            else None
        )
        testimonial, created = Testimonial.objects.get_or_create(
            author_name=author_name,
            quote=quote,
            defaults={
                "author_role": author_role,
                "company": company,
                "image": image,
                "rating": rating,
                "is_approved": True,
                "is_featured": featured,
                "sort_order": sort_order,
                "approved_by": ctx._admin,
                "approved_at": timezone.now(),
            },
        )
        if created:
            ctx.bumped("testimonial")

    for name, role_title, bio, image_key, sort_order in content.TEAM_MEMBERS:
        photo = ctx.media(image_key, title=f"Team: {name}", alt=role_title) if image_key else None
        member, created = TeamMember.objects.get_or_create(
            name=name,
            defaults={
                "role_title": role_title,
                "bio": bio,
                "photo": photo,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
        if created:
            ctx.bumped("team_member")

    ctx.log(
        f"  · {len(content.TESTIMONIALS)} testimonials, {len(content.TEAM_MEMBERS)} team members",
        verbosity=1,
    )


def seed_blog(ctx: SeedContext) -> None:
    from apps.cms.models import BlogCategory, BlogPost

    categories: dict[str, object] = {}
    for name, description in content.BLOG_CATEGORIES.items():
        slug = name.lower().replace(" & ", "-and-").replace(" ", "-")
        category, created = BlogCategory.objects.get_or_create(
            slug=slug,
            defaults={"name": name, "description": description},
        )
        categories[name] = category
        if created:
            ctx.bumped("blog_category")

    for (
        slug,
        title,
        category_name,
        excerpt,
        body,
        image_key,
        reading_minutes,
        featured,
        sort_order,
    ) in content.BLOG_POSTS:
        category = categories.get(category_name)
        image = ctx.media(image_key, title=f"Blog: {title}", alt=excerpt) if image_key else None
        post, created = BlogPost.objects.get_or_create(
            slug=slug,
            defaults={
                "title": title,
                "category": category,
                "author": ctx._admin,
                "excerpt": excerpt,
                "body": body,
                "featured_image": image,
                "reading_minutes": reading_minutes,
                "status": CmsPublishStatus.PUBLISHED,
                "published_at": timezone.now(),
                "is_featured": featured,
                "sort_order": sort_order,
            },
        )
        if created:
            ctx.bumped("blog_post")
    ctx.log(
        f"  · {len(content.BLOG_CATEGORIES)} blog categories, {len(content.BLOG_POSTS)} blog posts",
        verbosity=1,
    )


# ---------------------------------------------------------------------------
# Legacy demo records (backward compatibility with the original seeder)
# ---------------------------------------------------------------------------


def seed_legacy(ctx: SeedContext) -> None:
    """Keep the original baseline records so existing tests stay green."""
    from apps.cms.models import BlogCategory, BlogPost
    from apps.services.models import ConsultancyService
    from apps.training.models import Course, TrainingCategory

    legacy_page = content.LEGACY_PAGE
    Page.objects.get_or_create(
        slug=legacy_page["slug"],
        defaults={
            "title": legacy_page["title"],
            "page_type": PageType.CUSTOM,
            "summary": legacy_page["summary"],
            "body": legacy_page["body"],
            "status": CmsPublishStatus.DRAFT,
            "noindex": True,
        },
    )
    ctx.bumped("page")

    customer, customer_created = User.objects.get_or_create(
        email=content.LEGACY_DEMO_CUSTOMER_EMAIL,
        defaults={
            "first_name": "Seed Example",
            "last_name": "Customer",
            "role": UserRole.CUSTOMER,
            "is_active": False,
            "is_email_verified": False,
        },
    )
    if customer_created:
        customer.set_unusable_password()
        customer.save(update_fields=["password"])
        ctx.bumped("user")
    sync_user_groups(customer)

    blog_category, _ = BlogCategory.objects.get_or_create(
        slug=content.LEGACY_BLOG_CATEGORY["slug"],
        defaults={
            "name": content.LEGACY_BLOG_CATEGORY["name"],
            "description": content.LEGACY_BLOG_CATEGORY["description"],
        },
    )
    ctx.bumped("blog_category")

    for post in content.LEGACY_BLOG_POSTS:
        BlogPost.objects.get_or_create(
            slug=post["slug"],
            defaults={
                "title": post["title"],
                "category": blog_category,
                "excerpt": post["excerpt"],
                "body": post["body"],
                "status": CmsPublishStatus.DRAFT,
                "noindex": True,
                "reading_minutes": 2,
            },
        )
        ctx.bumped("blog_post")

    ConsultancyService.objects.get_or_create(
        slug=content.LEGACY_CONSULTANCY_SERVICE["slug"],
        defaults={
            "name": content.LEGACY_CONSULTANCY_SERVICE["name"],
            "is_active": False,
        },
    )
    ctx.bumped("consultancy_service")

    training_category, _ = TrainingCategory.objects.get_or_create(
        slug=content.LEGACY_TRAINING_CATEGORY["slug"],
        defaults={"name": content.LEGACY_TRAINING_CATEGORY["name"]},
    )
    ctx.bumped("training_category")

    Course.objects.get_or_create(
        slug=content.LEGACY_COURSE["slug"],
        defaults={
            "title": content.LEGACY_COURSE["title"],
            "category": training_category,
            "status": CourseStatus.DRAFT,
            "is_featured": False,
        },
    )
    ctx.bumped("course")


# ---------------------------------------------------------------------------
# Catalogue — categories, tags, products, listings, stock
# ---------------------------------------------------------------------------


def seed_catalog(ctx: SeedContext) -> None:
    """Build the category tree, tags, products, listings, prices and stock."""
    # Category tree.
    category_count = 0
    for name, _icon, _featured, children in content.CATEGORIES:
        parent = _ensure_category(ctx, name, parent=None)
        category_count += 1
        for child_name, _child_key in children:
            _ensure_category(ctx, child_name, parent=parent)
            category_count += 1

    # Tags.
    tags = {name: catalog_services.ensure_tag(name) for name in content.TAGS}

    # Warehouses (needed before listings reference them).
    for name, code, address, state_code, lga_name in content.WAREHOUSES:
        _ensure_warehouse(ctx, name, code, address, state_code, lga_name)

    # Products + listings.
    for product_spec in content.PRODUCTS:
        _seed_product(ctx, product_spec, tags)

    # Market reference prices.
    for product_name, state_code, year, season, price, unit_code in content.MARKET_REFERENCES:
        product = ctx.product(product_name)
        if product is None:
            continue
        catalog_services.record_market_reference(
            product,
            year=year,
            price_per_unit=D(price),
            unit=ctx.unit(unit_code),
            state=ctx.state(state_code, required=False) if state_code else None,
            season=season,
            source="AA Shinaka development survey",
            note="Development reference price.",
            actor=ctx._admin,
        )
        ctx.bumped("market_reference")

    ctx.log(
        f"  · {category_count} categories, {len(content.TAGS)} tags, "
        f"{len(content.PRODUCTS)} products, {len(content.WAREHOUSES)} warehouses",
        verbosity=1,
    )


def _ensure_category(ctx: SeedContext, name: str, parent: Category | None) -> Category:
    existing = ctx.category(name, parent=parent)
    if existing is not None:
        return existing
    category = catalog_services.create_category(
        name=name,
        parent=parent,
        is_featured=False,
        actor=ctx._admin,
    )
    return category


def _ensure_warehouse(ctx: SeedContext, name, code, address, state_code, lga_name):
    if ctx.warehouse(code) is not None:
        return
    catalog_services.create_warehouse(
        name=name,
        code=code,
        address=address,
        state=ctx.state(state_code),
        lga=ctx.lga(state_code, lga_name),
        actor=ctx._admin,
    )
    ctx.bumped("warehouse")


def _seed_product(ctx: SeedContext, spec: dict, tags: dict) -> None:
    category = ctx.category(spec["category"])
    if category is None:
        # Resolve the leaf category by name anywhere in the tree.
        category = Category.all_objects.filter(name__iexact=spec["category"]).first()
    if category is None:
        ctx.note(f"Skipping product '{spec['name']}': category '{spec['category']}' not found.")
        return

    unit = ctx.unit(spec["unit"])
    product_tags = [tags[name] for name in spec.get("tags", []) if name in tags]

    product = ctx.product(spec["name"])
    created = product is None
    if created:
        product = catalog_services.create_product(
            name=spec["name"],
            category=category,
            short_description=spec.get("short_description", ""),
            description=spec.get("description", ""),
            unit=unit,
            variety=spec.get("variety", ""),
            grade=spec.get("grade", ""),
            harvest_season=spec.get("harvest_season", ""),
            tags=product_tags,
            actor=ctx._admin,
        )
        ctx._products[spec["name"]] = product
        ctx.bumped("product")

        # Lead image (a published product requires at least one image).
        image_key = spec.get("image")
        if image_key:
            catalog_services.add_product_image(
                product,
                image=ctx.library.image(image_key, filename=f"{image_key}.jpg"),
                alt_text=spec["name"],
                sort_order=0,
                set_primary=True,
                actor=ctx._admin,
            )
            ctx.bumped("product_image")

        # Listings.
        for listing_spec in spec.get("listings", []):
            _seed_listing(ctx, product, listing_spec)

        # Publish only products we just created (never overwrite staff edits).
        if product.listings.filter(status=ListingStatus.ACTIVE).exists():
            catalog_services.set_product_status(
                product, status=PublishStatus.PUBLISHED, actor=ctx._admin
            )
    return


def _seed_listing(ctx: SeedContext, product: Product, spec: dict) -> None:
    state = ctx.state(spec["state"])
    lga = ctx.lga(spec["state"], spec["lga"])
    package_unit = ctx.unit(spec["package_unit"])
    warehouse = ctx.warehouse(spec["warehouse"])

    existing = ProductListing.objects.filter(
        product=product,
        state=state,
        lga=lga,
        package_size=D(spec["package_size"]),
        package_unit=package_unit,
    ).first()
    if existing is not None:
        return

    listing = catalog_services.create_listing(
        product=product,
        state=state,
        lga=lga,
        package_size=D(spec["package_size"]),
        package_unit=package_unit,
        selling_price=D(spec["price"]),
        compare_at_price=D(spec["compare_at"]) if spec.get("compare_at") else None,
        low_stock_threshold=D(spec.get("low_stock", 0)) or None,
        origin_verification=spec.get("origin_verification", "unverified"),
        origin_note=spec.get("origin_note", ""),
        actor=ctx._admin,
    )
    ctx.bumped("product_listing")

    for min_quantity, tier_price in spec.get("wholesale", []):
        catalog_services.set_wholesale_tier(
            listing,
            min_quantity=D(min_quantity),
            price=D(tier_price),
            actor=ctx._admin,
        )
        ctx.bumped("wholesale_tier")

    # Opening stock through the warehouse ledger.
    stock = D(spec.get("stock", 0))
    if stock > 0:
        catalog_services.adjust_stock(
            listing,
            delta=stock,
            warehouse=warehouse,
            kind=StockMovementKind.INTAKE,
            reference="seed",
            note="Opening development stock.",
            actor=ctx._admin,
        )

    catalog_services.set_listing_status(listing, status=ListingStatus.ACTIVE, actor=ctx._admin)


# ---------------------------------------------------------------------------
# Services — consultancy, farming, marketing, storage
# ---------------------------------------------------------------------------


def seed_services(ctx: SeedContext) -> None:
    for (
        name,
        summary,
        description,
        supports_online,
        supports_onsite,
        duration,
        fee,
        sort_order,
    ) in content.CONSULTANCY_SERVICES:
        ConsultancyService.objects.update_or_create(
            slug=_slug(name),
            defaults={
                "name": name,
                "summary": summary,
                "description": description,
                "supports_online": supports_online,
                "supports_onsite": supports_onsite,
                "duration_minutes": duration,
                "indicative_fee": D(fee),
                "is_active": True,
                "sort_order": sort_order,
            },
        )
        ctx.bumped("consultancy_service")

    for name, summary, description, unit_code, fee, sort_order in content.FARMING_SERVICES:
        FarmingService.objects.update_or_create(
            slug=_slug(name),
            defaults={
                "name": name,
                "summary": summary,
                "description": description,
                "unit": ctx.unit(unit_code),
                "indicative_fee": D(fee),
                "is_active": True,
                "sort_order": sort_order,
            },
        )
        ctx.bumped("farming_service")

    for name, summary, description, fee, sort_order in content.MARKETING_SERVICES:
        MarketingService.objects.update_or_create(
            slug=_slug(name),
            defaults={
                "name": name,
                "summary": summary,
                "description": description,
                "indicative_fee": D(fee),
                "is_active": True,
                "sort_order": sort_order,
            },
        )
        ctx.bumped("marketing_service")

    for name in content.PRODUCE_TYPES:
        ProduceType.objects.get_or_create(name=name, defaults={"is_active": True})
        ctx.bumped("produce_type")

    for (
        name,
        location,
        state_code,
        lga_name,
        capacity,
        capacity_unit,
        produce_names,
        conditions,
    ) in content.STORAGE_FACILITIES:
        _seed_storage_facility(
            ctx,
            name,
            location,
            state_code,
            lga_name,
            D(capacity),
            capacity_unit,
            produce_names,
            conditions,
        )

    ctx.log(
        f"  · {len(content.CONSULTANCY_SERVICES)} consultancy, "
        f"{len(content.FARMING_SERVICES)} farming, "
        f"{len(content.MARKETING_SERVICES)} marketing services, "
        f"{len(content.STORAGE_FACILITIES)} storage facilities",
        verbosity=1,
    )


def _seed_storage_facility(
    ctx, name, location, state_code, lga_name, capacity, capacity_unit, produce_names, conditions
):
    facility, created = StorageFacility.objects.get_or_create(
        name=name,
        defaults={
            "code": f"FAC-{_slug(name)[:18].upper()}",
            "location": location,
            "state": ctx.state(state_code),
            "lga": ctx.lga(state_code, lga_name),
            "capacity": capacity,
            "capacity_unit": capacity_unit,
            "storage_conditions": conditions,
            "is_active": True,
        },
    )
    if created:
        ctx.bumped("storage_facility")
    produce_types = [
        ProduceType.objects.get_or_create(name=produce_name, defaults={"is_active": True})[0]
        for produce_name in produce_names
    ]
    facility.accepted_produce_types.set(produce_types)

    # A couple of tracked capacity units per facility.
    for index, (unit_name, unit_capacity) in enumerate(
        (("Main bay", capacity), ("Overflow bay", capacity / 2)), start=0
    ):
        StorageUnit.objects.get_or_create(
            facility=facility,
            name=unit_name,
            defaults={
                "capacity": unit_capacity,
                "capacity_unit": capacity_unit,
                "storage_conditions": conditions,
                "is_active": True,
                "sort_order": index * 10,
            },
        )
        ctx.bumped("storage_unit")


# ---------------------------------------------------------------------------
# Training Academy
# ---------------------------------------------------------------------------


def seed_training(ctx: SeedContext) -> None:
    categories: dict[str, TrainingCategory] = {}
    for name, description, sort_order in content.TRAINING_CATEGORIES:
        category, created = TrainingCategory.objects.get_or_create(
            name=name,
            defaults={"description": description, "sort_order": sort_order},
        )
        categories[name] = category
        if created:
            ctx.bumped("training_category")

    for email, professional_title, biography, expertise in content.INSTRUCTOR_PROFILES:
        user = ctx.user(email)
        if user is None:
            continue
        InstructorProfile.objects.update_or_create(
            user=user,
            defaults={
                "professional_title": professional_title,
                "biography": biography,
                "expertise": expertise,
                "is_active": True,
            },
        )
        ctx.bumped("instructor_profile")

    for spec in content.COURSES:
        _seed_course(ctx, spec, categories)

    for name, address, city, state_code, capacity, facilities in content.TRAINING_VENUES:
        venue, created = TrainingVenue.objects.get_or_create(
            name=name,
            defaults={
                "address": address,
                "city": city,
                "state": ctx.state(state_code),
                "capacity": capacity,
                "facilities": facilities,
                "is_active": True,
            },
        )
        if created:
            ctx.bumped("training_venue")

    for (
        course_title,
        venue_name,
        delivery_mode,
        start_offset,
        duration_days,
        capacity,
        min_participants,
        fee,
        status,
    ) in content.TRAINING_SESSIONS:
        _seed_session(
            ctx,
            course_title,
            venue_name,
            delivery_mode,
            start_offset,
            duration_days,
            capacity,
            min_participants,
            D(fee),
            status,
        )

    template, created = CertificateTemplate.objects.get_or_create(
        name=content.CERTIFICATE_TEMPLATE["name"],
        defaults={
            "title": content.CERTIFICATE_TEMPLATE["title"],
            "body_text": content.CERTIFICATE_TEMPLATE["body_text"],
            "footer_text": content.CERTIFICATE_TEMPLATE["footer_text"],
            "is_active": True,
        },
    )
    if created:
        ctx.bumped("certificate_template")

    ctx.log(
        f"  · {len(content.TRAINING_CATEGORIES)} categories, "
        f"{len(content.COURSES)} courses, {len(content.TRAINING_VENUES)} venues, "
        f"{len(content.TRAINING_SESSIONS)} sessions",
        verbosity=1,
    )


def _seed_course(ctx: SeedContext, spec: dict, categories: dict) -> None:
    course = ctx.course(spec["title"])
    created = course is None
    if created:
        course = Course.objects.create(
            title=spec["title"],
            category=categories.get(spec["category"]),
            short_description=spec.get("short_description", ""),
            description=spec.get("description", ""),
            learning_objectives=spec.get("objectives", ""),
            prerequisites=spec.get("prerequisites", ""),
            duration_hours=D(spec.get("duration_hours", 0)),
            delivery_mode=spec.get("delivery_mode", DeliveryMode.IN_PERSON),
            status=CourseStatus.PUBLISHED,
            certificate_eligible=bool(spec.get("certificate", False)),
            is_featured=bool(spec.get("featured", False)),
            sort_order=spec.get("sort", 0),
            published_at=timezone.now(),
            created_by=ctx._admin,
        )
        image_key = spec.get("image")
        if image_key:
            course.featured_image.save(
                f"{image_key}.jpg",
                ctx.library.image(image_key, filename=f"{image_key}.jpg"),
                save=True,
            )
        ctx._courses[spec["title"]] = course
        ctx.bumped("course")

        module_count = 0
        lesson_count = 0
        for module_spec in spec.get("modules", []):
            module = CourseModule.objects.create(
                course=course,
                title=module_spec["title"],
                sort_order=module_count * 10,
            )
            module_count += 1
            for lesson_title, lesson_type, minutes in module_spec.get("lessons", []):
                CourseLesson.objects.create(
                    module=module,
                    title=lesson_title,
                    lesson_type=lesson_type,
                    content_text=f"<p>{lesson_title}</p>",
                    estimated_minutes=minutes,
                    sort_order=lesson_count,
                )
                lesson_count += 1
            ctx.bumped("course_module")
        ctx.bumped("course_lesson", lesson_count)

        # Assign the instructors to the course.
        for email, _title, _bio, _expertise in content.INSTRUCTOR_PROFILES:
            instructor = getattr(ctx.user(email), "instructor_profile", None)
            if instructor is None:
                continue
            InstructorAssignment.objects.get_or_create(
                instructor=instructor,
                course=course,
                defaults={
                    "role": "Lead instructor"
                    if email == content.INSTRUCTOR_PROFILES[0][0]
                    else "Instructor",
                    "is_active": True,
                    "assigned_by": ctx._admin,
                },
            )
            ctx.bumped("instructor_assignment")


def _seed_session(
    ctx,
    course_title,
    venue_name,
    delivery_mode,
    start_offset,
    duration_days,
    capacity,
    min_participants,
    fee,
    status,
):
    course = ctx.course(course_title)
    if course is None:
        return
    start_date = timezone.localdate() + dt.timedelta(days=start_offset)
    end_date = start_date + dt.timedelta(days=max(duration_days - 1, 0))
    deadline = start_date - dt.timedelta(days=max(start_offset // 2, 1))
    reference = f"TRN-{course.slug[:20].upper()}-{start_date:%Y%m%d}"
    venue = ctx.venue(venue_name) if venue_name else None
    session, created = TrainingSession.objects.get_or_create(
        reference=reference,
        defaults={
            "course": course,
            "title": f"{course.title} — {start_date:%b %Y}",
            "venue": venue,
            "delivery_mode": delivery_mode,
            "start_date": start_date,
            "end_date": end_date,
            "enrollment_deadline": deadline,
            "capacity": capacity,
            "min_participants": min_participants,
            "fee": fee,
            "status": status,
            "created_by": ctx._admin,
        },
    )
    if created:
        ctx.bumped("training_session")


# ---------------------------------------------------------------------------
# Export trade
# ---------------------------------------------------------------------------


def seed_export(ctx: SeedContext) -> None:
    # Destination countries (Nigeria already exists).
    for name, code in content.EXPORT_COUNTRIES:
        Country.objects.get_or_create(code=code, defaults={"name": name})
        ctx.bumped("country")

    # Document types first (requirements reference them).
    for (
        code,
        name,
        description,
        requires_expiry,
        is_official,
        sort_order,
    ) in content.EXPORT_DOCUMENT_TYPES:
        ExportDocumentType.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "requires_expiry": requires_expiry,
                "is_official": is_official,
                "is_active": True,
                "sort_order": sort_order,
            },
        )
        ctx.bumped("export_document_type")

    # Destinations.
    categories_by_name = {category.name: category for category in Category.all_objects.all()}
    for country_code, is_active, approval, category_names, summary in content.EXPORT_DESTINATIONS:
        country = Country.objects.filter(code__iexact=country_code).first()
        if country is None:
            continue
        destination, created = ExportDestination.objects.get_or_create(
            country=country,
            defaults={
                "country_code": country.code,
                "is_active": is_active,
                "approval_status": approval,
                "requirements_summary": summary,
                "approved_by": ctx._admin if is_active else None,
                "approved_at": timezone.now() if is_active else None,
                "last_verified_at": timezone.localdate() if is_active else None,
            },
        )
        if created:
            ctx.bumped("export_destination")
        if category_names:
            destination.supported_categories.set(
                [categories_by_name[name] for name in category_names if name in categories_by_name]
            )

    # Requirements (general) + document-type mappings.
    for (
        country_code,
        title,
        requirement_type,
        document_code,
        mandatory,
        description,
    ) in content.EXPORT_REQUIREMENTS:
        destination = ctx.destination(country_code)
        if destination is None:
            continue
        document_type = ctx.doc_type(document_code) if document_code else None
        ExportDestinationRequirement.objects.get_or_create(
            destination=destination,
            title=title,
            defaults={
                "description": description,
                "requirement_type": requirement_type,
                "document_type": document_type,
                "is_mandatory": mandatory,
                "is_active": True,
            },
        )
        ctx.bumped("export_requirement")
        if document_type is not None:
            ExportDocumentRequirement.objects.get_or_create(
                destination=destination,
                document_type=document_type,
                defaults={
                    "is_mandatory": mandatory,
                    "notes": description,
                    "is_active": True,
                },
            )
            ctx.bumped("export_document_requirement")

    # Restrictions.
    for country_code, restriction_type, description, category_name in content.EXPORT_RESTRICTIONS:
        destination = ctx.destination(country_code)
        if destination is None:
            continue
        category = categories_by_name.get(category_name) if category_name else None
        ExportTradeRestriction.objects.get_or_create(
            destination=destination,
            restriction_type=restriction_type,
            defaults={
                "category": category,
                "description": description,
                "is_active": True,
            },
        )
        ctx.bumped("export_restriction")

    # Product export profiles.
    for product_name, profile in content.EXPORT_PRODUCT_PROFILES.items():
        product = ctx.product(product_name)
        if product is None:
            continue
        grade, min_qty, min_unit, availability, require_inspection, destinations, notes = profile
        export_profile, created = ExportProductProfile.objects.get_or_create(
            product=product,
            defaults={
                "is_export_eligible": True,
                "export_grade": grade,
                "packaging_requirements": notes,
                "min_export_quantity": D(min_qty),
                "min_export_unit": ctx.unit(min_unit),
                "weight_unit": ctx.unit(min_unit),
                "export_availability": availability,
                "requires_inspection": require_inspection,
                "inspection_notes": notes,
                "notes": notes,
            },
        )
        if created:
            ctx.bumped("export_product_profile")
        export_profile.allowed_destinations.set(
            [ctx.destination(code) for code in destinations if ctx.destination(code)]
        )

    # Logistics providers.
    for (
        name,
        code,
        contact_name,
        contact_email,
        contact_phone,
        tracking_template,
    ) in content.LOGISTICS_PROVIDERS:
        LogisticsProvider.objects.get_or_create(
            name=name,
            defaults={
                "code": code,
                "contact_name": contact_name,
                "contact_email": contact_email,
                "contact_phone": contact_phone,
                "tracking_url_template": tracking_template,
                "is_active": True,
            },
        )
        ctx.bumped("logistics_provider")

    ctx.log(
        f"  · {len(content.EXPORT_DESTINATIONS)} destinations, "
        f"{len(content.EXPORT_DOCUMENT_TYPES)} document types, "
        f"{len(content.EXPORT_PRODUCT_PROFILES)} product profiles, "
        f"{len(content.LOGISTICS_PROVIDERS)} logistics providers",
        verbosity=1,
    )


# ---------------------------------------------------------------------------
# Orders — shipping configuration
# ---------------------------------------------------------------------------


def seed_shipping(ctx: SeedContext) -> None:
    states_by_code = {state.code: state for state in State.objects.all()}

    for name, code, description, state_codes in content.SHIPPING_ZONES:
        if ShippingZone.objects.filter(code__iexact=code).exists():
            continue
        zone = order_services.create_shipping_zone(
            name=name,
            code=code,
            description=description,
            states=[states_by_code[sc] for sc in state_codes if sc in states_by_code],
            actor=ctx._admin,
        )
        ctx.bumped("shipping_zone")

    for name, code, description, sort_order in content.SHIPPING_METHODS:
        if ShippingMethod.objects.filter(code__iexact=code).exists():
            continue
        order_services.create_shipping_method(
            name=name,
            code=code,
            description=description,
            sort_order=sort_order,
            actor=ctx._admin,
        )
        ctx.bumped("shipping_method")

    methods = {method.code: method for method in ShippingMethod.objects.all()}
    for zone_code, method_code, fee, free_over in content.SHIPPING_RATES:
        zone = ShippingZone.objects.filter(code__iexact=zone_code).first()
        method = methods.get(method_code)
        if zone is None or method is None:
            continue
        if ShippingRate.objects.filter(zone=zone, method=method).exists():
            continue
        order_services.create_shipping_rate(
            zone=zone,
            method=method,
            fee=D(fee),
            free_over=D(free_over) if free_over else None,
            actor=ctx._admin,
        )
        ctx.bumped("shipping_rate")

    ctx.log(
        f"  · {len(content.SHIPPING_ZONES)} zones, {len(content.SHIPPING_METHODS)} methods, "
        f"{len(content.SHIPPING_RATES)} rates",
        verbosity=1,
    )


# ---------------------------------------------------------------------------
# Optional transactional demo records (--with-demo-records)
# ---------------------------------------------------------------------------


def seed_demo_records(ctx: SeedContext) -> None:
    """Create a small set of *transactional* records so flows can be exercised.

    These are real orders, service requests, enrolments and export
    enquiries created through the public service layer — only enabled
    with ``--with-demo-records`` so a plain seed run stays safe.
    """
    from apps.export import services as export_services
    from apps.services import services as services_services
    from apps.training import services as training_services

    customers = [
        user
        for email in (
            "customer1@aashinaka.example",
            "customer2@aashinaka.example",
            "customer3@aashinaka.example",
        )
        if (user := ctx.user(email)) is not None
    ]
    if not customers:
        ctx.note("Demo records requested but no seeded customers found; skipping.")
        return

    _demo_service_requests(ctx, services_services, customers)
    _demo_enrolments(ctx, training_services, customers)
    _demo_export_enquiries(ctx, export_services, customers)
    _demo_orders(ctx, customers)

    ctx.log(
        "  · demo records created (service requests, enrolments, export enquiries, orders)",
        verbosity=1,
    )


def _demo_service_requests(ctx, services_services, customers) -> None:
    specs = [
        ("consultancy", "Request a farm business plan review", customers[0], "LA", "Ikeja"),
        (
            "farming",
            "Land preparation for a 2 hectare maize plot",
            customers[1],
            "KN",
            "Kano Municipal",
        ),
        ("marketing", "Offtake of 5 tonnes of sesame", customers[2], "OY", "Ibadan North"),
        ("storage", "Store 10 tonnes of maize for the dry season", customers[0], "KD", "Zaria"),
    ]
    for service_type, title, customer, state_code, lga_name in specs:
        if _has_service_request(customer, service_type):
            continue
        services_services.create_service_request(
            customer=customer,
            service_type=service_type,
            title=title,
            description=(
                "Development demo request created by seed_data. "
                "Please review and respond with a quotation."
            ),
            state=ctx.state(state_code),
            lga=ctx.lga(state_code, lga_name),
            notify=False,
        )
        ctx.bumped("service_request")


def _has_service_request(customer, service_type) -> bool:
    from apps.services.models import ServiceRequest

    return ServiceRequest.objects.filter(customer=customer, service_type=service_type).exists()


def _demo_enrolments(ctx, training_services, customers) -> None:
    sessions = list(TrainingSession.objects.filter(status="enrollment_open").order_by("start_date"))
    for customer, session in zip(customers, sessions, strict=False):
        if session.enrollments.filter(student=customer).exists():
            continue
        training_services.submit_enrollment(student=customer, session=session)
        ctx.bumped("enrollment")


def _demo_export_enquiries(ctx, export_services, customers) -> None:
    destination = ExportDestination.objects.filter(
        approval_status=ApprovalStatus.APPROVED, is_active=True
    ).first()
    if destination is None:
        ctx.note("No approved export destination; skipping demo export enquiry.")
        return
    eligible = [
        product
        for product in Product.all_objects.all()
        if getattr(product, "export_profile", None) is not None
        and product.export_profile.is_export_eligible
        and product.export_profile.allows_destination(destination)
    ]
    if not eligible:
        ctx.note("No export-eligible products for the destination; skipping demo enquiry.")
        return
    customer = customers[0]
    if _has_export_enquiry(customer, destination):
        return
    product = eligible[0]
    export_services.create_enquiry(
        customer=customer,
        destination=destination,
        actor=customer,
        delivery_destination=f"{destination.country.name} port",
        preferred_shipping_mode="sea",
        items=[
            {
                "product": product,
                "quantity": D(product.export_profile.min_export_quantity) or D(20),
                "unit": product.export_profile.min_export_unit or product.unit,
            }
        ],
    )
    ctx.bumped("export_enquiry")


def _has_export_enquiry(customer, destination) -> bool:
    from apps.export.models import ExportEnquiry

    return ExportEnquiry.objects.filter(customer=customer, destination=destination).exists()


def _demo_orders(ctx, customers) -> None:
    sellable = list(
        ProductListing.objects.filter(
            status=ListingStatus.ACTIVE,
            product__status=PublishStatus.PUBLISHED,
        )
        .exclude(stock_on_hand__lte=0)
        .order_by("?")
    )
    if not sellable:
        ctx.note("No sellable listings; skipping demo orders.")
        return

    methods = {method.code: method for method in ShippingMethod.objects.all()}
    for customer in customers:
        if Order_exists(customer):
            continue
        address = customer.addresses.order_by("-is_default").first()
        if address is None:
            continue
        method = methods.get("STANDARD") or methods.get("PICKUP")
        if method is None:
            continue
        cart = Cart.objects.filter(user=customer, status=CartStatus.ACTIVE).first()
        if cart is None:
            cart = Cart.objects.create(user=customer, status=CartStatus.ACTIVE)
        for listing in sellable[:2]:
            if cart.items.filter(listing=listing).exists():
                continue
            try:
                order_services.add_to_cart(cart, listing=listing, quantity=D(1))
            except Exception:
                continue
        if not cart.items.exists():
            continue
        try:
            order_services.place_order(
                user=customer,
                cart=cart,
                address=address,
                shipping_method=method,
                customer_note="Development demo order created by seed_data.",
            )
            ctx.bumped("order")
        except Exception as exc:
            ctx.note(f"Demo order for {customer.email} skipped: {exc}")


def Order_exists(customer) -> bool:
    from apps.orders.models import Order

    return Order.objects.filter(user=customer).exists()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_all(ctx: SeedContext, *, skip_locations: bool = False) -> None:
    """Run every seeder in dependency order."""
    seed_units(ctx)
    seed_locations(ctx, skip=skip_locations)
    seed_roles_and_users(ctx)
    seed_pages(ctx)
    seed_divisions_and_services(ctx)
    seed_site(ctx)
    seed_testimonials_and_team(ctx)
    seed_blog(ctx)
    seed_legacy(ctx)
    seed_catalog(ctx)
    seed_services(ctx)
    seed_training(ctx)
    seed_export(ctx)
    seed_shipping(ctx)
    if ctx.with_demo_records:
        seed_demo_records(ctx)


def dry_run(ctx: SeedContext, *, skip_locations: bool = False) -> None:
    """Read-only preflight: report what exists and what would be created."""

    def present(model, **filters):
        return model.objects.filter(**filters).exists()

    states = State.objects.count()
    lgas = LGA.objects.count()
    ctx.log("Dry run: no changes written.", verbosity=0)
    ctx.log(f"  Locations: {states} states, {lgas} LGAs", verbosity=0)
    ctx.log(f"  Role groups: {present_group_count()}/{len(UserRole.values)}", verbosity=0)
    ctx.log(f"  Users: {User.objects.count()} ({len(content.USERS)} planned)", verbosity=0)
    ctx.log(
        f"  CMS: {SiteSetting.objects.count()} settings, {Page.objects.count()} pages, "
        f"{HeroBanner.objects.count()} heroes, {BusinessDivision.objects.count()} divisions, "
        f"{ServicePage.objects.count()} service pages",
        verbosity=0,
    )
    ctx.log(
        f"  Catalogue: {Category.all_objects.count()} categories, "
        f"{Product.all_objects.count()} products, "
        f"{ProductListing.objects.count()} listings, "
        f"{Warehouse.objects.count()} warehouses",
        verbosity=0,
    )
    ctx.log(
        f"  Services: {ConsultancyService.objects.count()} consultancy, "
        f"{FarmingService.objects.count()} farming, "
        f"{MarketingService.objects.count()} marketing, "
        f"{StorageFacility.objects.count()} storage facilities",
        verbosity=0,
    )
    ctx.log(
        f"  Training: {TrainingCategory.objects.count()} categories, "
        f"{Course.objects.count()} courses, {TrainingSession.objects.count()} sessions",
        verbosity=0,
    )
    ctx.log(
        f"  Export: {ExportDestination.objects.count()} destinations, "
        f"{ExportDocumentType.objects.count()} document types, "
        f"{ExportProductProfile.objects.count()} product profiles",
        verbosity=0,
    )
    ctx.log(
        f"  Shipping: {ShippingZone.objects.count()} zones, "
        f"{ShippingMethod.objects.count()} methods, "
        f"{ShippingRate.objects.count()} rates",
        verbosity=0,
    )
    ctx.log(
        f"  Images: {'enabled' if ctx.library.enabled else 'disabled (--no-images)'}"
        + (", force refresh" if ctx.force_images else ""),
        verbosity=0,
    )


def present_group_count() -> int:
    from django.contrib.auth.models import Group

    from apps.accounts.roles import role_group_name

    names = [role_group_name(role) for role in UserRole.values]
    return Group.objects.filter(name__in=names).count()


def _slug(name: str) -> str:
    return (
        name.lower()
        .replace(" & ", "-and-")
        .replace("&", "and")
        .replace(" ", "-")
        .replace("(", "")
        .replace(")", "")
        .replace("/", "-")
        .replace("--", "-")
        .strip("-")
    )

"""Service-domain models: consultancy, farming, marketing and storage.

Phase 7 introduces a *shared* service-request foundation plus explicit,
service-specific records that hang off it:

* :class:`ServiceRequest` — the common request (customer, division, status,
  priority, structured location) every division shares, with its own
  :class:`ServiceRequestStatusHistory`, :class:`ServiceAssignment`,
  :class:`ServiceAttachment`, :class:`ServiceComment` and
  :class:`ServiceActivityLog`.
* Consultancy: :class:`ConsultancyService`, :class:`Consultant`,
  :class:`ConsultantAvailability`, :class:`ConsultationAppointment`,
  :class:`ConsultationReport`.
* Farming: :class:`FarmingService`, :class:`FarmServiceRequest`,
  :class:`FarmProject`, :class:`FarmProjectMilestone`, :class:`FarmVisit`,
  :class:`FarmProgressReport`.
* Marketing: :class:`MarketingService`, :class:`MarketingEnquiry`,
  :class:`MarketingProposal`, :class:`MarketingCampaign`,
  :class:`MarketingActivity`.
* Storage: :class:`ProduceType`, :class:`StorageFacility`,
  :class:`StorageUnit`, :class:`StorageServiceRequest`,
  :class:`StorageBooking`, :class:`StorageCapacityAllocation`,
  :class:`StorageCheckIn`, :class:`StorageCheckOut`,
  :class:`StorageInspection`.
* Reusable pricing: :class:`ServiceQuotation` + :class:`ServiceQuotationItem`.

Money is always ``DecimalField``. Quantities are ``Decimal`` so a booking can
be partially filled without float drift. The workflows themselves are only
identical where that is *true* — storage has capacity allocations, consultancy
has consultant schedules — so the shared request deliberately does not force a
single state machine on every division.
"""

from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from apps.catalog.models import UnitOfMeasure

User = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Base / helpers
# ---------------------------------------------------------------------------


def generate_reference(prefix: str, model, field: str = "reference") -> str:
    """Allocate a unique, human-readable reference such as ``AS-SR-20261013-A1B2C3``."""
    from django.utils import timezone as _tz

    today = _tz.now().strftime("%Y%m%d")
    for _ in range(10):
        candidate = f"{prefix}-{today}-{secrets.token_hex(3).upper()}"
        if not model.objects.filter(**{field: candidate}).exists():
            return candidate
    raise ValueError("Could not allocate a unique reference.")


def _fill_reference(model, prefix: str) -> None:
    if not model.reference:
        model.reference = generate_reference(prefix, type(model))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ServiceType(models.TextChoices):
    CONSULTANCY = "consultancy", "Agricultural consultancy"
    FARMING = "farming", "Farming services"
    MARKETING = "marketing", "Agricultural marketing"
    STORAGE = "storage", "Storage & warehousing"


class ServiceRequestStatus(models.TextChoices):
    """Shared request pipeline. Detail models add division-specific states."""

    SUBMITTED = "submitted", "Submitted"
    UNDER_REVIEW = "under_review", "Under review"
    QUOTED = "quoted", "Quotation issued"
    CONFIRMED = "confirmed", "Confirmed"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


#: Allowed shared-pipeline transitions. Terminal states have no exits.
REQUEST_TRANSITIONS: dict[str, set[str]] = {
    ServiceRequestStatus.SUBMITTED: {
        ServiceRequestStatus.UNDER_REVIEW,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.UNDER_REVIEW: {
        ServiceRequestStatus.QUOTED,
        ServiceRequestStatus.CONFIRMED,
        ServiceRequestStatus.IN_PROGRESS,
        ServiceRequestStatus.COMPLETED,
        ServiceRequestStatus.REJECTED,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.QUOTED: {
        ServiceRequestStatus.CONFIRMED,
        ServiceRequestStatus.IN_PROGRESS,
        ServiceRequestStatus.COMPLETED,
        ServiceRequestStatus.REJECTED,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.CONFIRMED: {
        ServiceRequestStatus.IN_PROGRESS,
        ServiceRequestStatus.COMPLETED,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.IN_PROGRESS: {
        ServiceRequestStatus.COMPLETED,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.COMPLETED: set(),
    ServiceRequestStatus.REJECTED: set(),
    ServiceRequestStatus.CANCELLED: set(),
}


class ServicePriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class CommentVisibility(models.TextChoices):
    CUSTOMER = "customer", "Visible to customer"
    INTERNAL = "internal", "Internal only"


class ConsultationMode(models.TextChoices):
    ONLINE = "online", "Online"
    ONSITE = "onsite", "On-site"


class AppointmentStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    CONFIRMED = "confirmed", "Confirmed"
    RESCHEDULED = "rescheduled", "Rescheduled"
    COMPLETED = "completed", "Completed"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


ACTIVE_APPOINTMENT_STATES = frozenset(
    {AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED}
)


class FarmAreaUnit(models.TextChoices):
    HECTARE = "hectare", "Hectare"
    ACRE = "acre", "Acre"
    SQUARE_METRE = "square_metre", "Square metre"


class FarmingSeason(models.TextChoices):
    DRY = "dry", "Dry season"
    WET = "wet", "Wet season"
    ALL_YEAR = "all_year", "All year"


class FarmProjectStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    ACTIVE = "active", "Active"
    ON_HOLD = "on_hold", "On hold"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class MilestoneStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    BLOCKED = "blocked", "Blocked"


class VisitStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class MarketingProposalStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ISSUED = "issued", "Issued"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"


class MarketingCampaignStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class StorageCapacityUnit(models.TextChoices):
    TONNE = "tonne", "Tonne"
    KILOGRAM = "kg", "Kilogram"
    BAG = "bag", "Bag (50kg)"
    CRATE = "crate", "Crate"
    PALLET = "pallet", "Pallet"
    CUBIC_METRE = "cubic_metre", "Cubic metre"


class StorageBookingStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    CONFIRMED = "confirmed", "Confirmed"
    CHECKED_IN = "checked_in", "Checked in"
    CHECKED_OUT = "checked_out", "Checked out"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class InspectionCondition(models.TextChoices):
    GOOD = "good", "Good"
    FAIR = "fair", "Fair"
    DAMAGED = "damaged", "Damaged"


class FarmRequestStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    REVIEWED = "reviewed", "Reviewed"
    QUOTED = "quoted", "Quotation issued"
    APPROVED = "approved", "Approved"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


# ---------------------------------------------------------------------------
# Shared service-request foundation
# ---------------------------------------------------------------------------


class ServiceRequestQuerySet(models.QuerySet):
    def open(self) -> ServiceRequestQuerySet:
        return self.exclude(
            status__in=[
                ServiceRequestStatus.COMPLETED,
                ServiceRequestStatus.REJECTED,
                ServiceRequestStatus.CANCELLED,
            ]
        )

    def for_customer(self, user) -> ServiceRequestQuerySet:
        return self.filter(customer=user)


class ServiceRequest(models.Model):
    """The common request record shared by every service division."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=32, unique=True, editable=False)
    customer = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="service_requests"
    )
    service_type = models.CharField(max_length=20, choices=ServiceType.choices, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=ServiceRequestStatus.choices,
        default=ServiceRequestStatus.SUBMITTED,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10, choices=ServicePriority.choices, default=ServicePriority.NORMAL
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_service_requests",
    )
    state = models.ForeignKey(
        "locations.State",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="service_requests",
    )
    lga = models.ForeignKey(
        "locations.LGA",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="service_requests",
    )
    preferred_date = models.DateField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    objects = ServiceRequestQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Service request"
        verbose_name_plural = "Service requests"
        indexes = [
            models.Index(fields=["service_type", "status"]),
            models.Index(fields=["customer", "service_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} · {self.get_service_type_display()}"

    def save(self, *args, **kwargs):
        _fill_reference(self, "AS-SR")
        super().save(*args, **kwargs)

    @property
    def is_open(self) -> bool:
        return self.status not in {
            ServiceRequestStatus.COMPLETED,
            ServiceRequestStatus.REJECTED,
            ServiceRequestStatus.CANCELLED,
        }

    def can_transition_to(self, status: str) -> bool:
        return status in REQUEST_TRANSITIONS.get(self.status, set())


class ServiceRequestStatusHistory(models.Model):
    """Append-only record of every status change on a request."""

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Service request status history"
        verbose_name_plural = "Service request status history"

    def __str__(self) -> str:
        return f"{self.request_id}: {self.from_status or '—'} → {self.to_status}"


class ServiceAssignment(models.Model):
    """A staff member assigned to a request (a request may have several)."""

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="assignments"
    )
    staff = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="service_assignments"
    )
    role = models.CharField(max_length=40, blank=True, help_text="e.g. lead, consultant, manager")
    assigned_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_active = models.BooleanField(default=True, db_index=True)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Service assignment"
        verbose_name_plural = "Service assignments"
        constraints = [
            models.UniqueConstraint(
                fields=["request", "staff", "role"], name="uniq_service_assignment"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.staff_id} → {self.request_id}"


class ServiceAttachment(models.Model):
    """A file attached to a request. Customer visibility is explicit."""

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="attachments"
    )
    uploaded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    file = models.FileField(upload_to="service_attachments/%Y/%m/")
    label = models.CharField(max_length=120, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    is_customer_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Service attachment"
        verbose_name_plural = "Service attachments"

    def __str__(self) -> str:
        return self.label or (self.file.name if self.file else "attachment")


class ServiceComment(models.Model):
    """A note on a request, optionally internal-only."""

    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField()
    visibility = models.CharField(
        max_length=10, choices=CommentVisibility.choices, default=CommentVisibility.CUSTOMER
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Service comment"
        verbose_name_plural = "Service comments"

    def __str__(self) -> str:
        return self.body[:60]


class ServiceActivityLog(models.Model):
    """Append-only activity trail for a request (staff + customer actions)."""

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="activity_log"
    )
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    summary = models.CharField(max_length=240, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Service activity log"
        verbose_name_plural = "Service activity log"

    def __str__(self) -> str:
        return f"{self.action} · {self.created_at:%Y-%m-%d %H:%M}"


class ServiceNotificationLog(models.Model):
    """Deduplication ledger so a state change notifies a customer exactly once."""

    event = models.CharField(max_length=60)
    dedupe_key = models.CharField(max_length=160, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)

    class Meta:
        verbose_name = "Service notification log"
        verbose_name_plural = "Service notification log"

    def __str__(self) -> str:
        return self.dedupe_key


# ---------------------------------------------------------------------------
# Reusable quotations
# ---------------------------------------------------------------------------


class QuotationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    ISSUED = "issued", "Issued"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class QuotationPaymentStatus(models.TextChoices):
    UNPAID = "unpaid", "Unpaid"
    PAID = "paid", "Paid"


class ServiceQuotation(models.Model):
    """A priced quotation linked to a service request.

    Lifecycle: ``draft → pending_approval → issued → accepted|rejected`` and
    ``issued → expired``. Once issued the customer may only accept or reject;
    accepted quotations are frozen (immutable snapshot of the priced terms).
    """

    _FROZEN_FIELDS = ("subtotal", "tax_amount", "total", "currency", "reference")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=32, unique=True, editable=False)
    customer = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="service_quotations"
    )
    request = models.ForeignKey(
        ServiceRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quotations",
    )
    currency = models.CharField(max_length=3, default="NGN")
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valid_until = models.DateField(null=True, blank=True)
    terms = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=QuotationStatus.choices, default=QuotationStatus.DRAFT, db_index=True
    )
    approved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=200, blank=True)
    payment_status = models.CharField(
        max_length=10,
        choices=QuotationPaymentStatus.choices,
        default=QuotationPaymentStatus.UNPAID,
        db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="superseded_by"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Service quotation"
        verbose_name_plural = "Service quotations"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0) & models.Q(tax_amount__gte=0),
                name="chk_service_quotation_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(total__gte=0), name="chk_service_quotation_total_nonneg"
            ),
        ]
        indexes = [models.Index(fields=["status", "customer"])]

    def __str__(self) -> str:
        return self.reference

    def save(self, *args, **kwargs):
        _fill_reference(self, "AS-QT")
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if (
                original is not None
                and original.status == QuotationStatus.ACCEPTED
                and any(
                    getattr(original, field) != getattr(self, field)
                    for field in self._FROZEN_FIELDS
                )
            ):
                raise ValidationError("An accepted quotation is immutable.")
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone as _tz

        if self.status != QuotationStatus.ISSUED or not self.valid_until:
            return False
        return self.valid_until < _tz.localdate()

    @property
    def can_be_accepted(self) -> bool:
        return self.status == QuotationStatus.ISSUED and not self.is_expired

    @property
    def is_paid(self) -> bool:
        return self.payment_status == QuotationPaymentStatus.PAID

    def recompute_totals(self) -> None:
        """Recompute the totals from the priced line items.

        The client never supplies totals; this is the single source of truth.
        """
        from decimal import Decimal

        from django.conf import settings

        subtotal = sum((item.line_total for item in self.items.all()), start=Decimal("0.00"))
        rate = Decimal(str(getattr(settings, "ORDER_TAX_RATE", "0") or "0"))
        self.subtotal = subtotal.quantize(Decimal("0.01"))
        self.tax_amount = (self.subtotal * rate).quantize(Decimal("0.01"))
        self.total = (self.subtotal + self.tax_amount).quantize(Decimal("0.01"))


class ServiceQuotationItem(models.Model):
    """A single priced line on a quotation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quotation = models.ForeignKey(ServiceQuotation, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit = models.ForeignKey(
        UnitOfMeasure, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ["sort_order", "created_at"]
        verbose_name = "Service quotation item"
        verbose_name_plural = "Service quotation items"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="chk_service_quotation_item_qty"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="chk_service_quotation_item_price"
            ),
        ]

    def __str__(self) -> str:
        return self.description


# ---------------------------------------------------------------------------
# Consultancy
# ---------------------------------------------------------------------------


class ConsultancyService(models.Model):
    """A bookable consultancy offering (catalogue of consultation types)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    summary = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)
    supports_online = models.BooleanField(default=True)
    supports_onsite = models.BooleanField(default=False)
    duration_minutes = models.PositiveIntegerField(default=60)
    indicative_fee = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="NGN")
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Consultancy service"
        verbose_name_plural = "Consultancy services"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify as _slug

            self.slug = _slug(self.name)
        super().save(*args, **kwargs)


class Consultant(models.Model):
    """A staff user who can be assigned to consultation appointments."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        "accounts.User", on_delete=models.PROTECT, related_name="consultant_profile"
    )
    headline = models.CharField(max_length=150, blank=True)
    bio = models.TextField(blank=True)
    specializations = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["user__first_name", "user__last_name"]
        verbose_name = "Consultant"
        verbose_name_plural = "Consultants"

    def __str__(self) -> str:
        return str(self.user.get_full_name() or self.user.email)


class ConsultantAvailability(models.Model):
    """Weekly (``weekday``) or one-off (``specific_date``) availability slot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    consultant = models.ForeignKey(
        Consultant, on_delete=models.CASCADE, related_name="availability"
    )
    weekday = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="0=Monday … 6=Sunday (recurring)."
    )
    specific_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ["weekday", "specific_date", "start_time"]
        verbose_name = "Consultant availability"
        verbose_name_plural = "Consultant availability"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(weekday__isnull=False, specific_date__isnull=True)
                    | models.Q(weekday__isnull=True, specific_date__isnull=False)
                ),
                name="chk_availability_one_schedule",
            ),
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="chk_availability_time_order",
            ),
        ]

    def __str__(self) -> str:
        when = self.specific_date or f"weekday {self.weekday}"
        return f"{self.consultant_id} · {when} {self.start_time}-{self.end_time}"

    def covers(self, start, end) -> bool:
        """Whether this window fully covers the ``[start, end)`` datetime window."""
        if self.weekday is not None:
            if start.weekday() != self.weekday or end.weekday() != self.weekday:
                return False
        else:
            if start.date() != self.specific_date or end.date() != self.specific_date:
                return False
        return start.time() >= self.start_time and end.time() <= self.end_time


class ConsultationAppointment(models.Model):
    """A scheduled consultation for a consultancy request.

    A *preferred date* on the request is only a request; an appointment becomes
    a booking when staff confirm it. Overlap prevention lives in the service
    layer (transactional, consultant row locked).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.OneToOneField(
        ServiceRequest, on_delete=models.CASCADE, related_name="consultation_appointment"
    )
    service = models.ForeignKey(
        ConsultancyService,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appointments",
    )
    consultant = models.ForeignKey(
        Consultant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appointments",
    )
    mode = models.CharField(
        max_length=10, choices=ConsultationMode.choices, default=ConsultationMode.ONLINE
    )
    scheduled_start = models.DateTimeField(db_index=True)
    scheduled_end = models.DateTimeField()
    status = models.CharField(
        max_length=15,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.REQUESTED,
        db_index=True,
    )
    location = models.CharField(max_length=240, blank=True)
    meeting_url = models.URLField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    confirmed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    rescheduled_from = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["-scheduled_start"]
        verbose_name = "Consultation appointment"
        verbose_name_plural = "Consultation appointments"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(scheduled_end__gt=models.F("scheduled_start")),
                name="chk_appointment_time_order",
            ),
        ]
        indexes = [models.Index(fields=["consultant", "status", "scheduled_start"])]

    def __str__(self) -> str:
        return f"{self.request_id} · {self.scheduled_start:%Y-%m-%d %H:%M}"


class ConsultationReport(models.Model):
    """Post-consultation outcome and (optionally) an uploaded report file."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        ConsultationAppointment, on_delete=models.CASCADE, related_name="reports"
    )
    summary = models.TextField()
    findings = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    file = models.FileField(upload_to="consultation_reports/%Y/%m/", blank=True)
    issued_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    issued_at = models.DateTimeField(auto_now_add=True, editable=False)
    is_customer_visible = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-issued_at"]
        verbose_name = "Consultation report"
        verbose_name_plural = "Consultation reports"

    def __str__(self) -> str:
        return f"Report for {self.appointment_id}"


# ---------------------------------------------------------------------------
# Farming
# ---------------------------------------------------------------------------


class FarmingService(models.Model):
    """A farming service offering (land prep, planting support, advisory, ...)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    summary = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)
    unit = models.ForeignKey(
        UnitOfMeasure, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    indicative_fee = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="NGN")
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Farming service"
        verbose_name_plural = "Farming services"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class FarmServiceRequest(models.Model):
    """The farming-specific details attached to a shared request."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.OneToOneField(
        ServiceRequest, on_delete=models.CASCADE, related_name="farm_request"
    )
    farm_location = models.CharField(max_length=240)
    state = models.ForeignKey(
        "locations.State", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    lga = models.ForeignKey(
        "locations.LGA", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    farm_size = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    area_unit = models.CharField(
        max_length=15, choices=FarmAreaUnit.choices, default=FarmAreaUnit.HECTARE
    )
    crop_type = models.CharField(max_length=120, blank=True)
    season = models.CharField(
        max_length=12, choices=FarmingSeason.choices, default=FarmingSeason.ALL_YEAR
    )
    requested_service = models.ForeignKey(
        FarmingService, null=True, blank=True, on_delete=models.SET_NULL, related_name="requests"
    )
    expected_start_date = models.DateField(null=True, blank=True)
    budget_min = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    budget_max = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    additional_requirements = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        verbose_name = "Farm service request"
        verbose_name_plural = "Farm service requests"

    def __str__(self) -> str:
        return f"Farm request · {self.request_id}"


class FarmProject(models.Model):
    """An approved farming project. Only activated after approval + agreement."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.OneToOneField(
        FarmServiceRequest, on_delete=models.CASCADE, related_name="project"
    )
    reference = models.CharField(max_length=32, unique=True, editable=False)
    name = models.CharField(max_length=180)
    manager = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="farm_projects",
    )
    status = models.CharField(
        max_length=12,
        choices=FarmProjectStatus.choices,
        default=FarmProjectStatus.DRAFT,
        db_index=True,
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    agreement_reference = models.CharField(max_length=80, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Farm project"
        verbose_name_plural = "Farm projects"

    def __str__(self) -> str:
        return f"{self.reference} · {self.name}"

    def save(self, *args, **kwargs):
        _fill_reference(self, "AS-FP")
        super().save(*args, **kwargs)


class FarmProjectMilestone(models.Model):
    """A tracked milestone in a farm project."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(FarmProject, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    sequence = models.PositiveIntegerField(default=1)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        choices=MilestoneStatus.choices,
        default=MilestoneStatus.PENDING,
        db_index=True,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["sequence", "created_at"]
        verbose_name = "Farm project milestone"
        verbose_name_plural = "Farm project milestones"

    def __str__(self) -> str:
        return f"{self.sequence}. {self.title}"


class FarmVisit(models.Model):
    """A scheduled/recorded visit to a project site."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(FarmProject, on_delete=models.CASCADE, related_name="visits")
    officer = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="farm_visits",
    )
    scheduled_date = models.DateField(null=True, blank=True)
    visit_date = models.DateField(null=True, blank=True)
    purpose = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=VisitStatus.choices, default=VisitStatus.PLANNED, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["-scheduled_date", "-created_at"]
        verbose_name = "Farm visit"
        verbose_name_plural = "Farm visits"

    def __str__(self) -> str:
        return f"Visit · {self.project_id}"


class FarmProgressReport(models.Model):
    """Progress update on a project based on real project data."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        FarmProject, on_delete=models.CASCADE, related_name="progress_reports"
    )
    visit = models.ForeignKey(
        FarmVisit, null=True, blank=True, on_delete=models.SET_NULL, related_name="progress_reports"
    )
    title = models.CharField(max_length=180)
    summary = models.TextField()
    progress_percent = models.PositiveSmallIntegerField(default=0)
    file = models.FileField(upload_to="farm_reports/%Y/%m/", blank=True)
    reported_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_customer_visible = models.BooleanField(default=True, db_index=True)
    reported_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ["-reported_at"]
        verbose_name = "Farm progress report"
        verbose_name_plural = "Farm progress reports"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(progress_percent__lte=100),
                name="chk_farm_report_progress",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.progress_percent}%)"


# ---------------------------------------------------------------------------
# Marketing
# ---------------------------------------------------------------------------


class MarketingService(models.Model):
    """An agricultural marketing service offering."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    summary = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)
    indicative_fee = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="NGN")
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Marketing service"
        verbose_name_plural = "Marketing services"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class MarketingEnquiry(models.Model):
    """Marketing-specific fields for a shared request.

    AA Shinaka remains the direct seller for its e-commerce catalogue; this
    workflow is a separate service and never creates third-party seller accounts.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.OneToOneField(
        ServiceRequest, on_delete=models.CASCADE, related_name="marketing_request"
    )
    service = models.ForeignKey(
        MarketingService, null=True, blank=True, on_delete=models.SET_NULL, related_name="enquiries"
    )
    product_type = models.CharField(max_length=150)
    available_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    unit = models.ForeignKey(
        UnitOfMeasure, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    product_location = models.CharField(max_length=240, blank=True)
    target_market = models.CharField(max_length=200, blank=True)
    marketing_requirements = models.TextField(blank=True)
    preferred_timeline = models.CharField(max_length=120, blank=True)
    additional_information = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        verbose_name = "Marketing enquiry"
        verbose_name_plural = "Marketing enquiries"

    def __str__(self) -> str:
        return f"Marketing · {self.request_id}"


class MarketingProposal(models.Model):
    """Narrative proposal for a marketing enquiry; prices live on the quotation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enquiry = models.ForeignKey(
        MarketingEnquiry, on_delete=models.CASCADE, related_name="proposals"
    )
    quotation = models.ForeignKey(
        "ServiceQuotation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="marketing_proposals",
    )
    reference = models.CharField(max_length=32, unique=True, editable=False)
    title = models.CharField(max_length=180)
    scope = models.TextField(blank=True)
    approach = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=MarketingProposalStatus.choices,
        default=MarketingProposalStatus.DRAFT,
        db_index=True,
    )
    issued_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Marketing proposal"
        verbose_name_plural = "Marketing proposals"

    def __str__(self) -> str:
        return self.reference

    def save(self, *args, **kwargs):
        _fill_reference(self, "AS-MP")
        super().save(*args, **kwargs)


class MarketingCampaign(models.Model):
    """An approved marketing activity run for an enquiry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enquiry = models.ForeignKey(
        MarketingEnquiry, on_delete=models.CASCADE, related_name="campaigns"
    )
    reference = models.CharField(max_length=32, unique=True, editable=False)
    name = models.CharField(max_length=180)
    officer = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="marketing_campaigns",
    )
    status = models.CharField(
        max_length=10,
        choices=MarketingCampaignStatus.choices,
        default=MarketingCampaignStatus.PLANNED,
        db_index=True,
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    targets = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Marketing campaign"
        verbose_name_plural = "Marketing campaigns"

    def __str__(self) -> str:
        return f"{self.reference} · {self.name}"

    def save(self, *args, **kwargs):
        _fill_reference(self, "AS-MC")
        super().save(*args, **kwargs)


class MarketingActivity(models.Model):
    """A single recorded marketing activity on a campaign."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(
        MarketingCampaign, on_delete=models.CASCADE, related_name="activities"
    )
    occurred_on = models.DateField()
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    outcome = models.TextField(blank=True)
    file = models.FileField(upload_to="marketing_reports/%Y/%m/", blank=True)
    recorded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ["-occurred_on", "-created_at"]
        verbose_name = "Marketing activity"
        verbose_name_plural = "Marketing activities"

    def __str__(self) -> str:
        return self.title


# ---------------------------------------------------------------------------
# Storage & warehousing
# ---------------------------------------------------------------------------


class ProduceType(models.Model):
    """A reference type of produce accepted by storage facilities."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Produce type"
        verbose_name_plural = "Produce types"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class StorageFacility(models.Model):
    """A physical warehouse / storage facility with a capacity ceiling."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160, unique=True)
    code = models.CharField(max_length=24, unique=True, blank=True)
    location = models.CharField(max_length=240, blank=True)
    state = models.ForeignKey(
        "locations.State", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    lga = models.ForeignKey(
        "locations.LGA", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    capacity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    capacity_unit = models.CharField(
        max_length=15, choices=StorageCapacityUnit.choices, default=StorageCapacityUnit.TONNE
    )
    accepted_produce_types = models.ManyToManyField(
        ProduceType, blank=True, related_name="facilities"
    )
    storage_conditions = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["name"]
        verbose_name = "Storage facility"
        verbose_name_plural = "Storage facilities"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gte=0), name="chk_storage_facility_capacity"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"FAC-{secrets.token_hex(3).upper()}"
        super().save(*args, **kwargs)

    def accepts(self, produce_type) -> bool:
        if produce_type is None:
            return True
        return self.accepted_produce_types.filter(pk=produce_type.pk).exists()


class StorageUnit(models.Model):
    """A capacity unit (bay/silo/room) inside a facility."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey(StorageFacility, on_delete=models.CASCADE, related_name="units")
    name = models.CharField(max_length=120)
    capacity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    capacity_unit = models.CharField(
        max_length=15,
        choices=StorageCapacityUnit.choices,
        default=StorageCapacityUnit.TONNE,
    )
    storage_conditions = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Storage unit"
        verbose_name_plural = "Storage units"
        constraints = [
            models.UniqueConstraint(fields=["facility", "name"], name="uniq_storage_unit_name"),
            models.CheckConstraint(
                condition=models.Q(capacity__gte=0), name="chk_storage_unit_capacity"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.facility_id} · {self.name}"


class StorageServiceRequest(models.Model):
    """Storage-specific fields for a shared request."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.OneToOneField(
        ServiceRequest, on_delete=models.CASCADE, related_name="storage_request"
    )
    produce_type = models.ForeignKey(
        ProduceType, null=True, blank=True, on_delete=models.SET_NULL, related_name="requests"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit = models.ForeignKey(
        UnitOfMeasure, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    preferred_facility = models.ForeignKey(
        StorageFacility,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requests",
    )
    preferred_location = models.CharField(max_length=240, blank=True)
    requested_start_date = models.DateField(null=True, blank=True)
    requested_end_date = models.DateField(null=True, blank=True)
    special_handling = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        verbose_name = "Storage service request"
        verbose_name_plural = "Storage service requests"

    def __str__(self) -> str:
        return f"Storage · {self.request_id}"


class StorageBooking(models.Model):
    """A confirmed (or pending) storage booking holding a capacity allocation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.OneToOneField(
        StorageServiceRequest, on_delete=models.CASCADE, related_name="booking"
    )
    reference = models.CharField(max_length=32, unique=True, editable=False)
    facility = models.ForeignKey(StorageFacility, on_delete=models.PROTECT, related_name="bookings")
    unit = models.ForeignKey(
        StorageUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings"
    )
    quotation = models.ForeignKey(
        "ServiceQuotation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="storage_bookings",
    )
    produce_type = models.ForeignKey(
        ProduceType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit_of_measure = models.ForeignKey(
        UnitOfMeasure, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=12,
        choices=StorageBookingStatus.choices,
        default=StorageBookingStatus.REQUESTED,
        db_index=True,
    )
    confirmed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Storage booking"
        verbose_name_plural = "Storage bookings"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="chk_storage_booking_dates",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0), name="chk_storage_booking_quantity"
            ),
        ]
        indexes = [models.Index(fields=["facility", "status", "start_date", "end_date"])]

    def __str__(self) -> str:
        return f"{self.reference} · {self.facility_id}"

    def save(self, *args, **kwargs):
        _fill_reference(self, "AS-SB")
        super().save(*args, **kwargs)

    @property
    def allocatable(self) -> bool:
        return self.status in {StorageBookingStatus.REQUESTED, StorageBookingStatus.CONFIRMED}


class StorageCapacityAllocation(models.Model):
    """A reservation of facility capacity for a booking over a date range.

    Overbooking prevention locks the facility and sums overlapping active
    allocations in the service layer; this table is the durable ledger.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        StorageBooking, on_delete=models.CASCADE, related_name="allocations"
    )
    facility = models.ForeignKey(
        StorageFacility, on_delete=models.PROTECT, related_name="allocations"
    )
    unit = models.ForeignKey(
        StorageUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="allocations"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    start_date = models.DateField()
    end_date = models.DateField()
    allocated_at = models.DateTimeField(auto_now_add=True, editable=False)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-allocated_at"]
        verbose_name = "Storage capacity allocation"
        verbose_name_plural = "Storage capacity allocations"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="chk_storage_allocation_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="chk_storage_allocation_dates",
            ),
        ]
        indexes = [models.Index(fields=["facility", "start_date", "end_date"])]

    def __str__(self) -> str:
        return f"{self.quantity} · {self.facility_id}"

    @property
    def is_active(self) -> bool:
        return self.released_at is None


class StorageCheckIn(models.Model):
    """Physical intake of produce against a booking."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(StorageBooking, on_delete=models.CASCADE, related_name="check_ins")
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    condition_notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    occurred_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "Storage check-in"
        verbose_name_plural = "Storage check-ins"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="chk_storage_checkin_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"Check-in {self.quantity} · {self.booking_id}"


class StorageCheckOut(models.Model):
    """Release of produce from a booking."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(StorageBooking, on_delete=models.CASCADE, related_name="check_outs")
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    condition_notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    occurred_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "Storage check-out"
        verbose_name_plural = "Storage check-outs"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="chk_storage_checkout_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"Check-out {self.quantity} · {self.booking_id}"


class StorageInspection(models.Model):
    """A recorded facility/booking inspection."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey(
        StorageFacility, on_delete=models.CASCADE, related_name="inspections"
    )
    booking = models.ForeignKey(
        StorageBooking,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inspections",
    )
    inspected_at = models.DateTimeField(default=timezone.now)
    inspected_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    condition = models.CharField(
        max_length=10, choices=InspectionCondition.choices, default=InspectionCondition.GOOD
    )
    findings = models.TextField(blank=True)
    file = models.FileField(upload_to="storage_inspections/%Y/%m/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ["-inspected_at"]
        verbose_name = "Storage inspection"
        verbose_name_plural = "Storage inspections"

    def __str__(self) -> str:
        return f"Inspection · {self.facility_id} · {self.inspected_at:%Y-%m-%d}"

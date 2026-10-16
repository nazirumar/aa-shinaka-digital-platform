"""Agricultural export domain models (Phase 8).

The export domain is intentionally its own application: it has a dedicated staff
role (Export Officer), its own capability set, its own documents/compliance and
shipment records, and its own customer + staff portals. It **extends** the
catalogue (it never duplicates ``Product``/``ProductListing``) and reuses the
Phase 6 payment infrastructure for settlement.

Design rules:

* Money and quantities are always ``Decimal``. No exchange rate, freight price
  or customs charge is ever invented — those are staff-entered or sourced.
* Destinations, requirements and restrictions are configuration, not code; they
  default to inactive/unapproved until a human approves them.
* Only real, staff-entered shipment milestones are stored — there is no
  fabricated GPS/live tracking.
* Accepted export quotations are frozen (versioned via revisions); export
  orders may only be created from accepted commercial terms.
"""

from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

User = settings.AUTH_USER_MODEL

# The Incoterms edition staff must choose from. Documented explicitly so no rule
# is assumed; the named place is always required when a quotation is issued.
INCOTERMS_VERSION = "2020"


def generate_reference(prefix: str) -> str:
    """A human-readable, collision-resistant reference (``AS-XX-YYYYMMDD-XXXXXX``)."""
    return f"{prefix}-{timezone.now():%Y%m%d}-{secrets.token_hex(3).upper()}"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class UUIDTimeStampedModel(models.Model):
    """Timestamped base with a UUID primary key (matches the platform PKs)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class RequirementType(models.TextChoices):
    DOCUMENTATION = "documentation", "Documentation"
    PHYTOSANITARY = "phytosanitary", "Phytosanitary"
    CERTIFICATION = "certification", "Certification"
    INSPECTION = "inspection", "Inspection"
    LABELLING = "labelling", "Labelling"
    PACKAGING = "packaging", "Packaging"
    QUARANTINE = "quarantine", "Quarantine"
    OTHER = "other", "Other"


class RestrictionType(models.TextChoices):
    PROHIBITED = "prohibited", "Prohibited"
    QUOTA = "quota", "Quota limited"
    LICENCE_REQUIRED = "licence_required", "Licence required"
    SEASONAL = "seasonal", "Seasonal"
    OTHER = "other", "Other"


class ExportAvailability(models.TextChoices):
    AVAILABLE = "available", "Available"
    LIMITED = "limited", "Limited"
    SEASONAL = "seasonal", "Seasonal"
    UNAVAILABLE = "unavailable", "Unavailable"


class ExportEnquiryStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    UNDER_REVIEW = "under_review", "Under review"
    REQUIREMENTS_REQUESTED = "requirements_requested", "Requirements requested"
    QUOTED = "quoted", "Quoted"
    CONVERTED = "converted", "Converted to order"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


# Allowed enquiry transitions. Terminal states map to an empty set.
EXPORT_ENQUIRY_TRANSITIONS: dict[str, frozenset[str]] = {
    ExportEnquiryStatus.SUBMITTED: frozenset(
        {
            ExportEnquiryStatus.UNDER_REVIEW,
            ExportEnquiryStatus.REQUIREMENTS_REQUESTED,
            ExportEnquiryStatus.REJECTED,
            ExportEnquiryStatus.CANCELLED,
        }
    ),
    ExportEnquiryStatus.UNDER_REVIEW: frozenset(
        {
            ExportEnquiryStatus.REQUIREMENTS_REQUESTED,
            ExportEnquiryStatus.QUOTED,
            ExportEnquiryStatus.REJECTED,
            ExportEnquiryStatus.CANCELLED,
        }
    ),
    ExportEnquiryStatus.REQUIREMENTS_REQUESTED: frozenset(
        {
            ExportEnquiryStatus.UNDER_REVIEW,
            ExportEnquiryStatus.QUOTED,
            ExportEnquiryStatus.CANCELLED,
        }
    ),
    ExportEnquiryStatus.QUOTED: frozenset(
        {
            ExportEnquiryStatus.CONVERTED,
            ExportEnquiryStatus.REJECTED,
            ExportEnquiryStatus.CANCELLED,
        }
    ),
    ExportEnquiryStatus.CONVERTED: frozenset(),
    ExportEnquiryStatus.REJECTED: frozenset(),
    ExportEnquiryStatus.CANCELLED: frozenset(),
}


class ShippingMode(models.TextChoices):
    NOT_SPECIFIED = "not_specified", "Not specified"
    SEA = "sea", "Sea freight"
    AIR = "air", "Air freight"
    ROAD = "road", "Road"
    RAIL = "rail", "Rail"
    MULTIMODAL = "multimodal", "Multimodal"


class Incoterm(models.TextChoices):
    """Incoterms 2020 rules (any mode + sea/inland waterway)."""

    EXW = "EXW", "EXW — Ex Works"
    FCA = "FCA", "FCA — Free Carrier"
    FAS = "FAS", "FAS — Free Alongside Ship"
    FOB = "FOB", "FOB — Free On Board"
    CFR = "CFR", "CFR — Cost and Freight"
    CIF = "CIF", "CIF — Cost, Insurance and Freight"
    CPT = "CPT", "CPT — Carriage Paid To"
    CIP = "CIP", "CIP — Carriage and Insurance Paid To"
    DAP = "DAP", "DAP — Delivered At Place"
    DPU = "DPU", "DPU — Delivered At Place Unloaded"
    DDP = "DDP", "DDP — Delivered Duty Paid"


class ExportQuotationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    ISSUED = "issued", "Issued"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"
    SUPERSEDED = "superseded", "Superseded"


class ExportChargeType(models.TextChoices):
    PRODUCT = "product", "Product cost"
    PACKAGING = "packaging", "Packaging"
    TRANSPORT = "transport", "Transport"
    INSURANCE = "insurance", "Insurance"
    HANDLING = "handling", "Handling"
    OTHER = "other", "Other charge"


class ExportOrderStatus(models.TextChoices):
    PENDING_PAYMENT = "pending_payment", "Pending payment"
    PAYMENT_VERIFIED = "payment_verified", "Payment verified"
    IN_PRODUCTION = "in_production", "In production"
    READY_FOR_SHIPMENT = "ready_for_shipment", "Ready for shipment"
    SHIPPED = "shipped", "Shipped"
    DELIVERED = "delivered", "Delivered"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


# Legal export-order transitions. ``ready_for_shipment`` is only reachable once
# the compliance checklist is approved (enforced in the service layer).
EXPORT_ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    ExportOrderStatus.PENDING_PAYMENT: frozenset(
        {ExportOrderStatus.PAYMENT_VERIFIED, ExportOrderStatus.CANCELLED}
    ),
    ExportOrderStatus.PAYMENT_VERIFIED: frozenset(
        {ExportOrderStatus.IN_PRODUCTION, ExportOrderStatus.CANCELLED}
    ),
    ExportOrderStatus.IN_PRODUCTION: frozenset(
        {ExportOrderStatus.READY_FOR_SHIPMENT, ExportOrderStatus.CANCELLED}
    ),
    ExportOrderStatus.READY_FOR_SHIPMENT: frozenset(
        {ExportOrderStatus.SHIPPED, ExportOrderStatus.CANCELLED}
    ),
    ExportOrderStatus.SHIPPED: frozenset(
        {ExportOrderStatus.DELIVERED, ExportOrderStatus.CANCELLED}
    ),
    ExportOrderStatus.DELIVERED: frozenset({ExportOrderStatus.COMPLETED}),
    ExportOrderStatus.COMPLETED: frozenset(),
    ExportOrderStatus.CANCELLED: frozenset(),
}


class ComplianceStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    BLOCKED = "blocked", "Blocked"
    CLEARED = "cleared", "Cleared"


class FulfillmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PRODUCTION = "in_production", "In production"
    READY = "ready", "Ready"
    DISPATCHED = "dispatched", "Dispatched"
    DELIVERED = "delivered", "Delivered"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class DocumentVerificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUBMITTED = "submitted", "Submitted"
    VERIFIED = "verified", "Verified"
    REJECTED = "rejected", "Rejected"


class DocumentReviewDecision(models.TextChoices):
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CHANGES_REQUESTED = "changes_requested", "Changes requested"


class ComplianceItemStatus(models.TextChoices):
    REQUIRED = "required", "Required"
    PENDING = "pending", "Pending"
    SUBMITTED = "submitted", "Submitted"
    VERIFIED = "verified", "Verified"
    REJECTED = "rejected", "Rejected"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


class ComplianceChecklistStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class TransportMode(models.TextChoices):
    SEA = "sea", "Sea"
    AIR = "air", "Air"
    ROAD = "road", "Road"
    RAIL = "rail", "Rail"
    MULTIMODAL = "multimodal", "Multimodal"


class ShipmentStatus(models.TextChoices):
    PREPARING = "preparing", "Preparing"
    READY_FOR_DISPATCH = "ready_for_dispatch", "Ready for dispatch"
    DISPATCHED = "dispatched", "Dispatched"
    IN_TRANSIT = "in_transit", "In transit"
    CUSTOMS_PROCESSING = "customs_processing", "Customs processing"
    DELIVERED = "delivered", "Delivered"
    EXCEPTION = "exception", "Exception"
    CANCELLED = "cancelled", "Cancelled"


SHIPMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    ShipmentStatus.PREPARING: frozenset(
        {ShipmentStatus.READY_FOR_DISPATCH, ShipmentStatus.CANCELLED}
    ),
    ShipmentStatus.READY_FOR_DISPATCH: frozenset(
        {ShipmentStatus.DISPATCHED, ShipmentStatus.CANCELLED}
    ),
    ShipmentStatus.DISPATCHED: frozenset(
        {ShipmentStatus.IN_TRANSIT, ShipmentStatus.EXCEPTION, ShipmentStatus.CANCELLED}
    ),
    ShipmentStatus.IN_TRANSIT: frozenset(
        {ShipmentStatus.CUSTOMS_PROCESSING, ShipmentStatus.DELIVERED, ShipmentStatus.EXCEPTION}
    ),
    ShipmentStatus.CUSTOMS_PROCESSING: frozenset(
        {ShipmentStatus.DELIVERED, ShipmentStatus.EXCEPTION}
    ),
    ShipmentStatus.EXCEPTION: frozenset(
        {ShipmentStatus.IN_TRANSIT, ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED}
    ),
    ShipmentStatus.DELIVERED: frozenset(),
    ShipmentStatus.CANCELLED: frozenset(),
}


# ---------------------------------------------------------------------------
# Task 1 — destinations, requirements, restrictions
# ---------------------------------------------------------------------------


class ExportDestination(UUIDTimeStampedModel):
    """An approved international market AA Shinaka may export to.

    A destination is **never** active without explicit staff approval; it is not
    a company branch and does not imply that every product may be exported there.
    """

    country = models.ForeignKey(
        "locations.Country", on_delete=models.PROTECT, related_name="export_destinations"
    )
    country_code = models.CharField(max_length=3, blank=True, db_index=True)
    is_active = models.BooleanField(default=False, db_index=True)
    approval_status = models.CharField(
        max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
    )
    supported_categories = models.ManyToManyField(
        "catalog.Category", blank=True, related_name="export_destinations"
    )
    requirements_summary = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    last_verified_at = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["country__name"]
        verbose_name = "Export destination"
        verbose_name_plural = "Export destinations"
        constraints = [
            models.UniqueConstraint(fields=["country"], name="uniq_export_destination_country"),
        ]
        indexes = [
            models.Index(fields=["is_active", "approval_status"]),
            models.Index(fields=["country_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.country.name} ({self.country_code or self.country.code})"

    def save(self, *args, **kwargs):
        if self.country_id and not self.country_code:
            self.country_code = self.country.code
        super().save(*args, **kwargs)

    @property
    def is_approved(self) -> bool:
        return self.approval_status == ApprovalStatus.APPROVED

    def supports_category(self, category) -> bool:
        """Whether every allowed category includes ``category`` (or a parent).

        An empty ``supported_categories`` set is *not* treated as "everything":
        the destination must be configured, and this returns ``False`` until it
        is.
        """
        if not self.pk or category is None:
            return False
        allowed = set(self.supported_categories.values_list("path", flat=True))
        return any(path and category.path.startswith(path) for path in allowed)


class ExportDestinationRequirement(UUIDTimeStampedModel):
    """A documented import/export requirement for a destination (or product)."""

    destination = models.ForeignKey(
        ExportDestination, on_delete=models.CASCADE, related_name="requirements"
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    requirement_type = models.CharField(
        max_length=20, choices=RequirementType.choices, default=RequirementType.DOCUMENTATION
    )
    category = models.ForeignKey(
        "catalog.Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_requirements",
    )
    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_requirements",
    )
    document_type = models.ForeignKey(
        "export.ExportDocumentType",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="destination_requirements",
    )
    is_mandatory = models.BooleanField(default=True)
    source = models.CharField(max_length=200, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    review_interval_days = models.PositiveIntegerField(default=0)
    last_verified_at = models.DateField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["destination__country__name", "title"]
        verbose_name = "Export destination requirement"
        verbose_name_plural = "Export destination requirements"

    def __str__(self) -> str:
        return f"{self.title} ({self.destination.country_code})"

    @property
    def is_stale(self) -> bool:
        """Whether the requirement is due for re-verification."""
        if not self.review_interval_days:
            return False
        if self.last_verified_at is None:
            return True
        from datetime import timedelta

        return (timezone.localdate() - self.last_verified_at) > timedelta(
            days=self.review_interval_days
        )


class ExportTradeRestriction(UUIDTimeStampedModel):
    """A known trade restriction for a destination and (optionally) a product."""

    destination = models.ForeignKey(
        ExportDestination, on_delete=models.CASCADE, related_name="restrictions"
    )
    category = models.ForeignKey(
        "catalog.Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_restrictions",
    )
    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_restrictions",
    )
    restriction_type = models.CharField(max_length=20, choices=RestrictionType.choices)
    description = models.TextField()
    source = models.CharField(max_length=200, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    last_verified_at = models.DateField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["destination__country__name", "restriction_type"]
        verbose_name = "Export trade restriction"
        verbose_name_plural = "Export trade restrictions"

    def __str__(self) -> str:
        return f"{self.get_restriction_type_display()} · {self.destination.country_code}"


# ---------------------------------------------------------------------------
# Task 2 — export product configuration (extends the catalogue)
# ---------------------------------------------------------------------------


class ExportProductProfile(UUIDTimeStampedModel):
    """Export-specific configuration for an existing catalogue ``Product``.

    This is a *profile*, not a duplicate product. A product is export-eligible
    only when this profile says so; destination restrictions are expressed both
    positively (``allowed_destinations``) and negatively (``ExportTradeRestriction``).
    """

    product = models.OneToOneField(
        "catalog.Product", on_delete=models.CASCADE, related_name="export_profile"
    )
    is_export_eligible = models.BooleanField(default=False, db_index=True)
    export_grade = models.CharField(max_length=60, blank=True)
    packaging_requirements = models.TextField(blank=True)
    min_export_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    min_export_unit = models.ForeignKey(
        "catalog.UnitOfMeasure",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    weight_unit = models.ForeignKey(
        "catalog.UnitOfMeasure",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    specifications = models.JSONField(default=dict, blank=True)
    export_availability = models.CharField(
        max_length=16,
        choices=ExportAvailability.choices,
        default=ExportAvailability.UNAVAILABLE,
    )
    requires_inspection = models.BooleanField(default=False)
    inspection_notes = models.TextField(blank=True)
    allowed_destinations = models.ManyToManyField(
        ExportDestination, blank=True, related_name="eligible_products"
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["product__name"]
        verbose_name = "Export product profile"
        verbose_name_plural = "Export product profiles"
        constraints = [
            models.CheckConstraint(
                condition=Q(min_export_quantity__gte=0),
                name="chk_export_profile_min_qty_nonneg",
            ),
        ]

    def __str__(self) -> str:
        return f"Export profile · {self.product.name}"

    @property
    def is_available(self) -> bool:
        return (
            self.is_export_eligible and self.export_availability != ExportAvailability.UNAVAILABLE
        )

    def allows_destination(self, destination) -> bool:
        """Whether this product may be exported to ``destination``.

        If no positive allow-list is configured, the destination is permitted
        unless an active restriction prohibits it. Any active restriction that
        names the product (or its category) blocks it.
        """
        from .selectors import active_restriction_for

        if active_restriction_for(destination=destination, product=self.product) is not None:
            return False
        allowed = list(self.allowed_destinations.all())
        if allowed and destination not in allowed:
            return False
        if destination.supported_categories.exists():
            category = self.product.category
            if not destination.supported_categories.filter(pk__in=_category_ancestors(category)):
                return False
        return True


def _category_ancestors(category):
    """Return the ids of ``category`` and its ancestors (best-effort)."""
    ids = []
    seen = set()
    node = category
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        ids.append(node.pk)
        node = getattr(node, "parent", None)
    return ids


# ---------------------------------------------------------------------------
# Task 3 — export enquiries
# ---------------------------------------------------------------------------


class ExportEnquiry(UUIDTimeStampedModel):
    """A customer's request for a quotation to export a product to a country."""

    reference = models.CharField(max_length=32, unique=True, editable=False)
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="export_enquiries")
    destination = models.ForeignKey(
        ExportDestination, on_delete=models.PROTECT, related_name="enquiries"
    )
    status = models.CharField(
        max_length=24,
        choices=ExportEnquiryStatus.choices,
        default=ExportEnquiryStatus.SUBMITTED,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=[
            ("low", "Low"),
            ("normal", "Normal"),
            ("high", "High"),
            ("urgent", "Urgent"),
        ],
        default="normal",
    )
    origin_state = models.ForeignKey(
        "locations.State",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    origin_lga = models.ForeignKey(
        "locations.LGA",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    delivery_destination = models.CharField(max_length=255)
    preferred_shipping_mode = models.CharField(
        max_length=16, choices=ShippingMode.choices, default=ShippingMode.NOT_SPECIFIED
    )
    requested_delivery_period = models.CharField(max_length=120, blank=True)
    requested_delivery_date = models.DateField(null=True, blank=True)
    packaging_requirements = models.TextField(blank=True)
    additional_requirements = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_enquiries_assigned",
    )
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Export enquiry"
        verbose_name_plural = "Export enquiries"
        indexes = [
            models.Index(fields=["status", "destination"]),
            models.Index(fields=["customer", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} · {self.destination.country_code}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_reference("AS-EXQ")
        super().save(*args, **kwargs)

    @property
    def is_open(self) -> bool:
        return self.status not in {
            ExportEnquiryStatus.CONVERTED,
            ExportEnquiryStatus.REJECTED,
            ExportEnquiryStatus.CANCELLED,
        }

    @property
    def item_count(self) -> int:
        return self.items.count()


class ExportEnquiryItem(UUIDTimeStampedModel):
    enquiry = models.ForeignKey(ExportEnquiry, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="export_enquiry_items"
    )
    listing = models.ForeignKey(
        "catalog.ProductListing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.ForeignKey("catalog.UnitOfMeasure", on_delete=models.PROTECT, related_name="+")
    packaging_requirements = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Export enquiry item"
        verbose_name_plural = "Export enquiry items"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="chk_export_enquiry_qty_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product} × {self.quantity}"


class ExportEnquiryAttachment(UUIDTimeStampedModel):
    enquiry = models.ForeignKey(ExportEnquiry, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="export/enquiries/%Y/%m/")
    label = models.CharField(max_length=150, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Export enquiry attachment"
        verbose_name_plural = "Export enquiry attachments"

    def __str__(self) -> str:
        return self.label or self.file.name


class ExportEnquiryStatusHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enquiry = models.ForeignKey(
        ExportEnquiry, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24)
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Export enquiry status history"
        verbose_name_plural = "Export enquiry status history"

    def __str__(self) -> str:
        return f"{self.enquiry.reference}: {self.from_status} → {self.to_status}"


# ---------------------------------------------------------------------------
# Task 4 — export quotations
# ---------------------------------------------------------------------------


# Financial / commercial fields that freeze once a quotation is accepted.
QUOTATION_FROZEN_FIELDS = (
    "currency",
    "exchange_rate_reference",
    "incoterm",
    "incoterm_version",
    "named_place",
    "payment_terms",
    "delivery_terms",
    "valid_until",
    "subtotal",
    "total",
)


class ExportQuotation(UUIDTimeStampedModel):
    """A priced offer for an export enquiry, in a chosen currency and Incoterm."""

    reference = models.CharField(max_length=32, unique=True, editable=False)
    enquiry = models.ForeignKey(
        ExportEnquiry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotations",
    )
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="export_quotations")
    destination = models.ForeignKey(
        ExportDestination, on_delete=models.PROTECT, related_name="quotations"
    )
    status = models.CharField(
        max_length=20,
        choices=ExportQuotationStatus.choices,
        default=ExportQuotationStatus.DRAFT,
        db_index=True,
    )
    currency = models.CharField(max_length=3, default="USD")
    exchange_rate_reference = models.CharField(max_length=120, blank=True)
    incoterm = models.CharField(max_length=3, choices=Incoterm.choices, blank=True)
    incoterm_version = models.CharField(max_length=8, default=INCOTERMS_VERSION)
    named_place = models.CharField(max_length=180, blank=True)
    payment_terms = models.TextField(blank=True)
    delivery_terms = models.TextField(blank=True)
    valid_until = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deposit_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Percentage of the total required as a deposit before fulfilment.",
    )
    revision = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="superseded_by",
    )
    prepared_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Export quotation"
        verbose_name_plural = "Export quotations"
        constraints = [
            models.CheckConstraint(
                condition=Q(total__gte=0), name="chk_export_quotation_total_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0), name="chk_export_quotation_subtotal_nonneg"
            ),
        ]
        indexes = [models.Index(fields=["status", "destination"])]

    def __str__(self) -> str:
        return f"{self.reference} ({self.currency} {self.total})"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_reference("AS-EXQT")
        if not self._state.adding and self.status == ExportQuotationStatus.ACCEPTED:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("status", *QUOTATION_FROZEN_FIELDS)
                .first()
            )
            if previous is not None and previous["status"] == ExportQuotationStatus.ACCEPTED:
                for field in QUOTATION_FROZEN_FIELDS:
                    if str(getattr(self, field)) != str(previous[field]):
                        from django.core.exceptions import ValidationError

                        raise ValidationError(
                            "An accepted export quotation is immutable; issue a revision instead."
                        )
        super().save(*args, **kwargs)

    @property
    def is_accepted(self) -> bool:
        return self.status == ExportQuotationStatus.ACCEPTED

    def required_deposit(self):
        from decimal import ROUND_HALF_UP, Decimal

        if not self.deposit_percentage:
            return Decimal("0.00")
        return (self.total * self.deposit_percentage / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


class ExportQuotationItem(UUIDTimeStampedModel):
    quotation = models.ForeignKey(ExportQuotation, on_delete=models.CASCADE, related_name="items")
    charge_type = models.CharField(
        max_length=16, choices=ExportChargeType.choices, default=ExportChargeType.PRODUCT
    )
    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    listing = models.ForeignKey(
        "catalog.ProductListing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    unit = models.ForeignKey(
        "catalog.UnitOfMeasure", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "created_at"]
        verbose_name = "Export quotation item"
        verbose_name_plural = "Export quotation items"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=0), name="chk_export_quote_item_qty_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0), name="chk_export_quote_item_price_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(amount__gte=0), name="chk_export_quote_item_amount_nonneg"
            ),
        ]

    def __str__(self) -> str:
        return self.description

    def save(self, *args, **kwargs):
        from decimal import ROUND_HALF_UP, Decimal

        quantity = self.quantity or Decimal("0")
        unit_price = self.unit_price or Decimal("0")
        self.amount = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class ExportQuotationRevision(UUIDTimeStampedModel):
    """An immutable snapshot taken whenever a quotation is revised."""

    quotation = models.ForeignKey(
        ExportQuotation, on_delete=models.CASCADE, related_name="revisions"
    )
    revision_number = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict, blank=True)
    changes_summary = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-revision_number"]
        verbose_name = "Export quotation revision"
        verbose_name_plural = "Export quotation revisions"
        constraints = [
            models.UniqueConstraint(
                fields=["quotation", "revision_number"],
                name="uniq_export_quotation_revision",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quotation.reference} r{self.revision_number}"


# ---------------------------------------------------------------------------
# Task 5 — export orders
# ---------------------------------------------------------------------------


class ExportOrder(UUIDTimeStampedModel):
    """A firm export order created only from an accepted export quotation."""

    reference = models.CharField(max_length=32, unique=True, editable=False)
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="export_orders")
    destination = models.ForeignKey(
        ExportDestination, on_delete=models.PROTECT, related_name="orders"
    )
    quotation = models.OneToOneField(
        ExportQuotation, on_delete=models.PROTECT, related_name="order"
    )
    status = models.CharField(
        max_length=20,
        choices=ExportOrderStatus.choices,
        default=ExportOrderStatus.PENDING_PAYMENT,
        db_index=True,
    )
    currency = models.CharField(max_length=3, default="USD")
    incoterm = models.CharField(max_length=3, choices=Incoterm.choices, blank=True)
    incoterm_version = models.CharField(max_length=8, default=INCOTERMS_VERSION)
    named_place = models.CharField(max_length=180, blank=True)
    payment_terms = models.TextField(blank=True)
    commercial_terms = models.JSONField(default=dict, blank=True)
    origin_details = models.TextField(blank=True)
    payment_requirements = models.TextField(blank=True)
    compliance_status = models.CharField(
        max_length=16, choices=ComplianceStatus.choices, default=ComplianceStatus.PENDING
    )
    fulfillment_status = models.CharField(
        max_length=16, choices=FulfillmentStatus.choices, default=FulfillmentStatus.PENDING
    )
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    balance_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    assigned_to = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_orders_assigned",
    )
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Export order"
        verbose_name_plural = "Export orders"
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0), name="chk_export_order_total_nonneg"),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0), name="chk_export_order_paid_nonneg"
            ),
        ]
        indexes = [models.Index(fields=["status", "destination"])]

    def __str__(self) -> str:
        return f"{self.reference} · {self.destination.country_code}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_reference("AS-EXO")
        super().save(*args, **kwargs)

    @property
    def balance_due(self):
        from decimal import Decimal

        return max(self.total - self.amount_paid, Decimal("0.00"))

    @property
    def is_fully_paid(self) -> bool:
        return self.amount_paid >= self.total

    @property
    def is_compliance_cleared(self) -> bool:
        checklist = getattr(self, "compliance_checklist", None)
        return bool(checklist and checklist.status == ComplianceChecklistStatus.APPROVED)


class ExportOrderItem(UUIDTimeStampedModel):
    order = models.ForeignKey(ExportOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="export_order_items",
    )
    listing = models.ForeignKey(
        "catalog.ProductListing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.ForeignKey(
        "catalog.UnitOfMeasure", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    packaging_requirements = models.CharField(max_length=255, blank=True)
    origin_state = models.ForeignKey(
        "locations.State", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    origin_lga = models.ForeignKey(
        "locations.LGA", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Export order item"
        verbose_name_plural = "Export order items"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="chk_export_order_item_qty_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.description

    def save(self, *args, **kwargs):
        from decimal import ROUND_HALF_UP, Decimal

        quantity = self.quantity or Decimal("0")
        unit_price = self.unit_price or Decimal("0")
        self.line_total = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class ExportOrderStatusHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(ExportOrder, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24)
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Export order status history"
        verbose_name_plural = "Export order status history"

    def __str__(self) -> str:
        return f"{self.order.reference}: {self.from_status} → {self.to_status}"


# ---------------------------------------------------------------------------
# Task 6 — export documents
# ---------------------------------------------------------------------------


class ExportDocumentType(UUIDTimeStampedModel):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    requires_expiry = models.BooleanField(default=False)
    is_official = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Export document type"
        verbose_name_plural = "Export document types"

    def __str__(self) -> str:
        return self.name


class ExportDocument(UUIDTimeStampedModel):
    """A document attached to an export order (private storage)."""

    reference = models.CharField(max_length=32, unique=True, editable=False)
    order = models.ForeignKey(ExportOrder, on_delete=models.CASCADE, related_name="documents")
    document_type = models.ForeignKey(
        ExportDocumentType, on_delete=models.PROTECT, related_name="documents"
    )
    file = models.FileField(upload_to="export/documents/%Y/%m/")
    issuing_organization = models.CharField(max_length=180, blank=True)
    document_reference = models.CharField(max_length=160, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    verification_status = models.CharField(
        max_length=16,
        choices=DocumentVerificationStatus.choices,
        default=DocumentVerificationStatus.PENDING,
        db_index=True,
    )
    is_customer_visible = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Export document"
        verbose_name_plural = "Export documents"
        indexes = [models.Index(fields=["order", "verification_status"])]

    def __str__(self) -> str:
        return f"{self.reference} · {self.document_type.name}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_reference("AS-EXD")
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return bool(self.expiration_date and self.expiration_date < timezone.localdate())


class ExportDocumentRequirement(UUIDTimeStampedModel):
    """Configuration: which document types a destination/product requires."""

    destination = models.ForeignKey(
        ExportDestination,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="document_requirements",
    )
    category = models.ForeignKey(
        "catalog.Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    document_type = models.ForeignKey(
        ExportDocumentType, on_delete=models.PROTECT, related_name="requirements"
    )
    is_mandatory = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    source = models.CharField(max_length=200, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    last_verified_at = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["document_type__sort_order", "document_type__name"]
        verbose_name = "Export document requirement"
        verbose_name_plural = "Export document requirements"

    def __str__(self) -> str:
        return f"{self.document_type.name}"


class ExportDocumentReview(UUIDTimeStampedModel):
    document = models.ForeignKey(ExportDocument, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decision = models.CharField(max_length=20, choices=DocumentReviewDecision.choices)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Export document review"
        verbose_name_plural = "Export document reviews"

    def __str__(self) -> str:
        return f"{self.document.reference} · {self.get_decision_display()}"


# ---------------------------------------------------------------------------
# Task 7 — compliance checklist
# ---------------------------------------------------------------------------


class ExportComplianceChecklist(UUIDTimeStampedModel):
    order = models.OneToOneField(
        ExportOrder, on_delete=models.CASCADE, related_name="compliance_checklist"
    )
    status = models.CharField(
        max_length=16,
        choices=ComplianceChecklistStatus.choices,
        default=ComplianceChecklistStatus.PENDING,
        db_index=True,
    )
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Export compliance checklist"
        verbose_name_plural = "Export compliance checklists"

    def __str__(self) -> str:
        return f"Compliance · {self.order.reference}"

    @property
    def total_items(self) -> int:
        return self.items.count()

    @property
    def outstanding_items(self) -> int:
        return self.items.filter(
            is_mandatory=True,
            status__in=[
                ComplianceItemStatus.REQUIRED,
                ComplianceItemStatus.PENDING,
                ComplianceItemStatus.SUBMITTED,
                ComplianceItemStatus.REJECTED,
            ],
        ).count()

    @property
    def is_complete(self) -> bool:
        return self.outstanding_items == 0


class ExportComplianceChecklistItem(UUIDTimeStampedModel):
    checklist = models.ForeignKey(
        ExportComplianceChecklist, on_delete=models.CASCADE, related_name="items"
    )
    requirement = models.ForeignKey(
        ExportDestinationRequirement,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    document_requirement = models.ForeignKey(
        ExportDocumentRequirement,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    document = models.ForeignKey(
        ExportDocument,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="compliance_items",
    )
    document_type = models.ForeignKey(
        ExportDocumentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=ComplianceItemStatus.choices,
        default=ComplianceItemStatus.REQUIRED,
    )
    is_mandatory = models.BooleanField(default=True)
    source = models.CharField(max_length=200, blank=True)
    source_reference = models.CharField(max_length=300, blank=True)
    last_reviewed_at = models.DateField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Export compliance item"
        verbose_name_plural = "Export compliance items"

    def __str__(self) -> str:
        return self.title


# ---------------------------------------------------------------------------
# Task 8 — shipment & logistics
# ---------------------------------------------------------------------------


class LogisticsProvider(UUIDTimeStampedModel):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=40, unique=True, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    tracking_url_template = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional. Use {tracking} as the tracking-reference placeholder.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Logistics provider"
        verbose_name_plural = "Logistics providers"

    def __str__(self) -> str:
        return self.name

    def tracking_url(self, tracking_reference: str) -> str:
        if self.tracking_url_template and tracking_reference:
            return self.tracking_url_template.replace("{tracking}", tracking_reference)
        return ""


class ExportShipment(UUIDTimeStampedModel):
    reference = models.CharField(max_length=32, unique=True, editable=False)
    order = models.ForeignKey(ExportOrder, on_delete=models.CASCADE, related_name="shipments")
    provider = models.ForeignKey(
        LogisticsProvider,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shipments",
    )
    transport_mode = models.CharField(max_length=16, choices=TransportMode.choices)
    origin = models.CharField(max_length=200)
    destination = models.CharField(max_length=200)
    departure_date = models.DateField(null=True, blank=True)
    estimated_arrival = models.DateField(null=True, blank=True)
    actual_arrival = models.DateField(null=True, blank=True)
    tracking_reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=24,
        choices=ShipmentStatus.choices,
        default=ShipmentStatus.PREPARING,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Export shipment"
        verbose_name_plural = "Export shipments"
        indexes = [models.Index(fields=["status", "order"])]

    def __str__(self) -> str:
        return f"{self.reference} · {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_reference("AS-EXS")
        super().save(*args, **kwargs)

    @property
    def tracking_url(self) -> str:
        return self.provider.tracking_url(self.tracking_reference) if self.provider else ""


class ExportShipmentItem(UUIDTimeStampedModel):
    shipment = models.ForeignKey(ExportShipment, on_delete=models.CASCADE, related_name="items")
    order_item = models.ForeignKey(
        ExportOrderItem, on_delete=models.PROTECT, related_name="shipment_items"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Export shipment item"
        verbose_name_plural = "Export shipment items"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="chk_export_shipment_item_qty_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_item.description} × {self.quantity}"


class ShipmentMilestone(UUIDTimeStampedModel):
    """A real, staff-entered shipment milestone (never fabricated GPS data)."""

    shipment = models.ForeignKey(
        ExportShipment, on_delete=models.CASCADE, related_name="milestones"
    )
    status = models.CharField(max_length=24, choices=ShipmentStatus.choices)
    occurred_at = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    is_staff_entered = models.BooleanField(default=True)
    recorded_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-occurred_at", "-created_at"]
        verbose_name = "Shipment milestone"
        verbose_name_plural = "Shipment milestones"

    def __str__(self) -> str:
        return f"{self.shipment.reference} · {self.get_status_display()}"


class ShipmentDocument(UUIDTimeStampedModel):
    shipment = models.ForeignKey(ExportShipment, on_delete=models.CASCADE, related_name="documents")
    document = models.ForeignKey(
        ExportDocument,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shipments",
    )
    file = models.FileField(upload_to="export/shipments/%Y/%m/", blank=True)
    label = models.CharField(max_length=150, blank=True)
    uploaded_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Shipment document"
        verbose_name_plural = "Shipment documents"

    def __str__(self) -> str:
        return self.label or (self.document.reference if self.document else self.file.name)


# ---------------------------------------------------------------------------
# Task 13 — notification dedupe log
# ---------------------------------------------------------------------------


class ExportNotificationLog(models.Model):
    """Records that a notification was sent for a stable dedupe key.

    Reusing the Phase 6 email helper keeps a single mail path; this log stops a
    retried transition from notifying twice.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dedupe_key = models.CharField(max_length=180, unique=True)
    event = models.CharField(max_length=60)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Export notification log"
        verbose_name_plural = "Export notification logs"

    def __str__(self) -> str:
        return f"{self.event}: {self.dedupe_key}"


__all__ = [
    "ApprovalStatus",
    "ComplianceChecklistStatus",
    "ComplianceItemStatus",
    "ComplianceStatus",
    "DocumentReviewDecision",
    "DocumentVerificationStatus",
    "ExportAvailability",
    "ExportChargeType",
    "ExportComplianceChecklist",
    "ExportComplianceChecklistItem",
    "ExportDestination",
    "ExportDestinationRequirement",
    "ExportDocument",
    "ExportDocumentRequirement",
    "ExportDocumentReview",
    "ExportDocumentType",
    "ExportEnquiry",
    "ExportEnquiryAttachment",
    "ExportEnquiryItem",
    "ExportEnquiryStatus",
    "ExportEnquiryStatusHistory",
    "ExportNotificationLog",
    "ExportOrder",
    "ExportOrderItem",
    "ExportOrderStatus",
    "ExportOrderStatusHistory",
    "ExportProductProfile",
    "ExportQuotation",
    "ExportQuotationItem",
    "ExportQuotationRevision",
    "ExportQuotationStatus",
    "ExportShipment",
    "ExportShipmentItem",
    "ExportTradeRestriction",
    "FulfillmentStatus",
    "Incoterm",
    "LogisticsProvider",
    "RequirementType",
    "RestrictionType",
    "ShipmentDocument",
    "ShipmentMilestone",
    "ShipmentStatus",
    "ShippingMode",
    "TransportMode",
    "UUIDTimeStampedModel",
    "generate_reference",
]

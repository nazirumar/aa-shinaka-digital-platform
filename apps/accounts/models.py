"""Custom user model and customer addresses.

The user model is email-first (no username) and carries the platform role that
drives permissions across the customer portal and the staff dashboard. It must
exist before the first migration because every other app depends on it.

Phase 2 refines the role set to the ten canonical platform roles and adds email
verification state. Changing ``choices`` is a validation-only change; a data
migration maps any Phase 1 role values onto the new set.
"""

import uuid
from typing import ClassVar

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models import Q


class UserRole(models.TextChoices):
    """The ten canonical platform roles.

    ``CUSTOMER`` is the only role that can be self-assigned. All other roles are
    staff roles and are granted only by an authorised administrator.
    """

    CUSTOMER = "customer", "Customer"
    SALES_OFFICER = "sales_officer", "Sales Officer"
    INVENTORY_OFFICER = "inventory_officer", "Inventory Officer"
    CONSULTANT = "consultant", "Consultant"
    TRAINING_MANAGER = "training_manager", "Training Manager"
    EXPORT_OFFICER = "export_officer", "Export Officer"
    FINANCE_OFFICER = "finance_officer", "Finance Officer"
    CONTENT_EDITOR = "content_editor", "Content Editor"
    ADMINISTRATOR = "administrator", "Administrator"
    OWNER = "owner", "Owner / Super Admin"


STAFF_ROLES: frozenset[str] = frozenset(
    role for role in UserRole.values if role != UserRole.CUSTOMER
)

# Roles that only an owner/superuser may grant.
PRIVILEGED_ROLES: frozenset[str] = frozenset({UserRole.ADMINISTRATOR, UserRole.OWNER})


class UserManager(BaseUserManager):
    """Manager for the email-based custom user model."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        # Case-normalise the whole address so `Ada@X.com` and `ada@x.com`
        # resolve to the same account.
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", UserRole.CUSTOMER)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.OWNER)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        # Email login is case-insensitive.
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=20, blank=True, db_index=True)
    role = models.CharField(
        max_length=32,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER,
        db_index=True,
    )
    state = models.ForeignKey(
        "locations.State",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )
    is_email_verified = models.BooleanField(default=False, db_index=True)
    email_verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    # Rotated on successful verification so previously issued tokens cannot be
    # replayed.
    email_verification_nonce = models.UUIDField(default=uuid.uuid4, editable=False)
    marketing_opt_in = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        ordering: ClassVar[list[str]] = ["-date_joined"]
        verbose_name = "User"
        verbose_name_plural = "Users"
        permissions: ClassVar[list[tuple[str, str]]] = [
            ("view_staff", "Can view the staff directory"),
            ("add_staff", "Can create staff accounts"),
            ("change_staff", "Can edit staff accounts"),
            ("deactivate_staff", "Can activate or deactivate staff accounts"),
            ("assign_roles", "Can assign staff roles"),
        ]

    objects = UserManager()

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return self.get_full_name() or self.email

    @property
    def is_staff_role(self) -> bool:
        return self.role in STAFF_ROLES

    @property
    def is_owner(self) -> bool:
        return self.is_superuser or self.role == UserRole.OWNER

    @property
    def display_role(self) -> str:
        return self.get_role_display()


class Address(models.Model):
    """A customer delivery address.

    State/LGA reference the verified Nigeria location data; no location values
    are hardcoded here.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=50, blank=True)
    recipient_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    country = models.CharField(max_length=64, default="Nigeria")
    state = models.ForeignKey("locations.State", on_delete=models.PROTECT, related_name="addresses")
    lga = models.ForeignKey("locations.LGA", on_delete=models.PROTECT, related_name="addresses")
    city = models.CharField(max_length=120)
    street_address = models.CharField(max_length=255)
    landmark = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=16, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-is_default", "-updated_at"]
        verbose_name = "Address"
        verbose_name_plural = "Addresses"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(is_default=True),
                name="uniq_default_address_per_user",
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["user", "is_default"], name="acct_addr_user_default_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.recipient_name}, {self.city} ({self.state.code})"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.lga_id and self.state_id and self.lga.state_id != self.state_id:
            raise ValidationError(
                {"lga": "The selected LGA does not belong to the selected state."}
            )

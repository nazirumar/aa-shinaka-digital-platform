"""Forms for registration, authentication, profiles, addresses and staff."""

from __future__ import annotations

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.core.exceptions import ValidationError

from .models import Address, User
from .permissions import assignable_roles
from .services import create_staff, register_customer, save_address, update_staff

INPUT_CLASSES = (
    "mt-1 w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-stone-900 "
    "placeholder:text-stone-400 focus:border-brand-500 focus:outline-none focus:ring-2 "
    "focus:ring-brand-200"
)
SELECT_CLASSES = INPUT_CLASSES
CHECKBOX_CLASSES = "h-4 w-4 rounded border-stone-300 text-brand-600 focus:ring-brand-500"
TEXTAREA_CLASSES = INPUT_CLASSES


class TailwindFormMixin:
    """Apply consistent Tailwind widget classes to every field."""

    def _apply_widget_classes(self) -> None:
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = SELECT_CLASSES
            elif isinstance(widget, forms.CheckboxInput):
                css = CHECKBOX_CLASSES
            elif isinstance(widget, forms.Textarea):
                css = TEXTAREA_CLASSES
            else:
                css = INPUT_CLASSES
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {css}".strip()


class RegisterForm(TailwindFormMixin, UserCreationForm):
    """Public customer registration."""

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    phone = forms.CharField(max_length=20)
    accept_terms = forms.BooleanField(
        required=True,
        label="I agree to the Terms of Service and Privacy Policy",
        error_messages={
            "required": "You must accept the Terms of Service and Privacy Policy to register."
        },
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "email", "phone")
        widgets = {
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs.setdefault("autocomplete", "new-password")
        self._apply_widget_classes()

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def save(self, commit: bool = True) -> User:
        return register_customer(
            email=self.cleaned_data["email"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            phone=self.cleaned_data["phone"],
            password=self.cleaned_data["password1"],
        )


class EmailAuthenticationForm(TailwindFormMixin, AuthenticationForm):
    """Email/password login form with generic, non-enumerating errors."""

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class ProfileForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone", "state", "marketing_opt_in")
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class StyledPasswordChangeForm(TailwindFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class StyledSetPasswordForm(TailwindFormMixin, SetPasswordForm):
    """Used by the password-reset confirm view."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class StyledPasswordResetForm(TailwindFormMixin, PasswordResetForm):
    """Used by the password-reset request view."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_classes()


class AddressForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Address
        fields = (
            "label",
            "recipient_name",
            "phone",
            "state",
            "lga",
            "city",
            "street_address",
            "landmark",
            "postal_code",
            "is_default",
        )
        widgets = {
            "recipient_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel"}),
            "city": forms.TextInput(attrs={"autocomplete": "address-level2"}),
            "street_address": forms.TextInput(attrs={"autocomplete": "street-address"}),
            "postal_code": forms.TextInput(attrs={"autocomplete": "postal-code"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["state"].queryset = self.fields["state"].queryset.filter(is_active=True)
        self.fields["lga"].queryset = self.fields["lga"].queryset.filter(is_active=True)
        self.fields["state"].empty_label = "Select a state"
        self.fields["lga"].empty_label = "Select an LGA"
        self._apply_widget_classes()
        # The LGA select is populated by HTMX when a state is chosen.
        self.fields["lga"].widget.attrs.update(
            {
                "hx-get": "/accounts/lgas/",
                "hx-target": "#id_lga",
                "hx-trigger": "change from:#id_state",
                "hx-include": "#id_state",
            }
        )

    def clean(self):
        cleaned = super().clean()
        state = cleaned.get("state")
        lga = cleaned.get("lga")
        if state and lga and lga.state_id != state.id:
            self.add_error("lga", "The selected LGA does not belong to the selected state.")
        return cleaned

    def save(self, commit: bool = True) -> Address:
        if self.user is None:
            raise ValueError("AddressForm requires a user.")
        return save_address(
            user=self.user,
            address=self.instance if self.instance.pk else None,
            make_default=self.cleaned_data.get("is_default", False),
            **{name: self.cleaned_data[name] for name in self.Meta.fields if name != "is_default"},
        )


class StaffCreateForm(TailwindFormMixin, UserCreationForm):
    """Admin-side staff account creation."""

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    phone = forms.CharField(max_length=20, required=False)
    role = forms.ChoiceField(choices=[])

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "email", "phone")

    def __init__(self, *args, actor=None, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.request = request
        if actor is not None:
            self.fields["role"].choices = assignable_roles(actor)
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs.setdefault("autocomplete", "new-password")
        self._apply_widget_classes()

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def save(self, commit: bool = True) -> User:
        return create_staff(
            actor=self.actor,
            email=self.cleaned_data["email"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            phone=self.cleaned_data.get("phone", ""),
            role=self.cleaned_data["role"],
            password=self.cleaned_data["password1"],
            request=self.request,
        )


class StaffEditForm(TailwindFormMixin, forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    phone = forms.CharField(max_length=20, required=False)

    def __init__(self, *args, target=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.target = target
        self.actor = actor
        if target is not None and not self.is_bound:
            self.initial.update(
                {
                    "first_name": target.first_name,
                    "last_name": target.last_name,
                    "phone": target.phone,
                }
            )
        self._apply_widget_classes()

    def save(self) -> User:
        return update_staff(
            actor=self.actor,
            target=self.target,
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            phone=self.cleaned_data.get("phone", ""),
        )


class StaffRoleForm(TailwindFormMixin, forms.Form):
    role = forms.ChoiceField(choices=[])

    def __init__(self, *args, actor=None, target=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.target = target
        if actor is not None:
            self.fields["role"].choices = assignable_roles(actor)
        if target is not None and not self.is_bound:
            self.initial["role"] = target.role
        self._apply_widget_classes()

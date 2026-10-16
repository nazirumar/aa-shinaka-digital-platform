"""MFA forms."""

from __future__ import annotations

from django import forms


class ConfirmTOTPForm(forms.Form):
    code = forms.CharField(max_length=10, label="Verification code")


class VerifyTOTPForm(forms.Form):
    code = forms.CharField(max_length=10, label="Verification code", required=False)
    recovery_code = forms.CharField(max_length=20, label="Recovery code", required=False)

    def clean(self):
        cleaned = super().clean()
        code = cleaned.get("code", "").strip()
        recovery = cleaned.get("recovery_code", "").strip()
        if not code and not recovery:
            raise forms.ValidationError("Enter a verification code or recovery code.")
        if code and recovery:
            raise forms.ValidationError(
                "Enter either a verification code or recovery code, not both."
            )
        cleaned["code"] = code
        cleaned["recovery_code"] = recovery.upper()
        return cleaned

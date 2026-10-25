from django import forms
from django.utils.translation import gettext_lazy as _

from council.models import CouncilDocument, CouncilLibraryFolder, CouncilMember


class CouncilMemberForm(forms.ModelForm):
    class Meta:
        model = CouncilMember
        fields = ["full_name", "email", "phone", "role", "organisation", "term_start", "term_end", "notes", "is_active"]
        widgets = {
            "term_start": forms.DateInput(attrs={"type": "date"}),
            "term_end": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }


class CouncilLibraryFolderForm(forms.ModelForm):
    class Meta:
        model = CouncilLibraryFolder
        fields = ["name", "description", "access_level", "allowed_users", "allowed_groups"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("access_level") == CouncilLibraryFolder.ACCESS_RESTRICTED
            and not cleaned.get("allowed_users")
            and not cleaned.get("allowed_groups")
        ):
            raise forms.ValidationError(
                _("Choose at least one allowed user or group for a restricted folder.")
            )
        return cleaned


class CouncilDocumentForm(forms.ModelForm):
    class Meta:
        model = CouncilDocument
        fields = ["title", "description", "document", "expires_on"]
        widgets = {
            "expires_on": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

from django import forms
from django.utils.translation import gettext_lazy as _

from petty_cash.models import PettyCashAccount, PettyCashEntry


class PettyCashAccountForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            for name in ("opening_balance", "currency"):
                self.fields[name].disabled = True
            self.fields["opening_balance"].help_text = _("Use a cash top-up or adjustment to change the balance.")
            self.fields["currency"].help_text = _("Create a separate cash float for another currency.")

    def clean_name(self):
        name = self.cleaned_data["name"]
        from horilla.horilla_middlewares import _thread_locals
        request = getattr(_thread_locals, "request", None)
        company = self.instance.company_id_id
        if not self.instance.pk and request:
            selected = request.session.get("selected_company")
            company = selected if selected and selected != "all" else None
        if PettyCashAccount._base_manager.filter(company_id_id=company, name=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("A cash float with this name already exists in this company."))
        return name

    class Meta:
        model = PettyCashAccount
        fields = ["name", "custodian", "opening_balance", "currency", "notes", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class PettyCashEntryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["direction"].required = False
        self.fields["direction"].help_text = _("Only choose a direction for adjustments. Top-ups are Cash in; expenses are Cash out.")
    class Meta:
        model = PettyCashEntry
        fields = [
            "account", "transaction_date", "entry_type", "direction", "amount", "category",
            "payee", "description", "reference", "receipt",
        ]
        widgets = {
            "transaction_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        entry_type = cleaned.get("entry_type")
        if entry_type == PettyCashEntry.TYPE_TOP_UP:
            cleaned["direction"] = PettyCashEntry.DIRECTION_IN
        elif entry_type == PettyCashEntry.TYPE_EXPENSE:
            cleaned["direction"] = PettyCashEntry.DIRECTION_OUT
        elif entry_type == PettyCashEntry.TYPE_ADJUSTMENT and not cleaned.get("direction"):
            self.add_error("direction", _("Choose Cash in or Cash out for an adjustment."))
        return cleaned

    def save(self, commit=True):
        entry = super().save(commit=False)
        # Keep direction server-controlled for normal cashbook movements.
        if entry.entry_type == PettyCashEntry.TYPE_TOP_UP:
            entry.direction = PettyCashEntry.DIRECTION_IN
        elif entry.entry_type == PettyCashEntry.TYPE_EXPENSE:
            entry.direction = PettyCashEntry.DIRECTION_OUT
        if commit:
            entry.save()
            self.save_m2m()
        return entry


class PettyCashVoidForm(forms.Form):
    void_reason = forms.CharField(
        max_length=250,
        label=_("Why is this entry being voided?"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )

from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from base.models import Company
from pms.models import Period, QuestionTemplate
from pms.review_workflow import open_period


class OpenQuarterForm(forms.Form):
    company = forms.ModelChoiceField(queryset=Company.objects.none())
    question_template = forms.ModelChoiceField(queryset=QuestionTemplate.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.all()
        self.fields["question_template"].queryset = QuestionTemplate.objects.all()
        for field in self.fields.values():
            field.widget.attrs["class"] = "oh-select w-100"


@login_required
@permission_required("pms.change_period", raise_exception=True)
@require_http_methods(["GET", "POST"])
def quarter_control(request, pk):
    period = get_object_or_404(Period, pk=pk)
    form = OpenQuarterForm(request.POST or None)
    result = None
    if request.method == "POST":
        if request.POST.get("action") == "close":
            with transaction.atomic():
                period = Period.objects.select_for_update().get(pk=pk)
                period.is_open = False
                period.save(update_fields=["is_open"])
            result = "Review period closed. Submitted ratings are preserved."
        elif request.user.has_perm("pms.add_feedback") and form.is_valid():
            try:
                count = open_period(period, form.cleaned_data["company"], form.cleaned_data["question_template"])
                period.refresh_from_db()
                result = f"Review period opened. {count} new employee reviews assigned. Staff can review their reporting managers; managers can review their staff under 360° Feedback."
            except ValidationError as exc:
                form.add_error(None, exc)
        elif not request.user.has_perm("pms.add_feedback"):
            form.add_error(None, "You also need permission to create feedback reviews.")
    return render(request, "cbv/period/quarter_control.html", {"period": period, "form": form, "result": result})

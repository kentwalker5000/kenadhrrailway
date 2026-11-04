"""Company-level loss-of-pay configuration for the payroll settings page."""

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from base.auth_backends import get_home_company_id
from base.models import Company
from horilla.decorators import login_required, permission_required
from payroll.models.models import LossOfPayPolicy


@login_required
@permission_required("payroll.view_payslipautogenerate")
@require_http_methods(["GET", "POST"])
def loss_of_pay_settings(request):
    from payroll.forms.forms import LossOfPayPolicyForm

    company_id = get_home_company_id(request.user)
    if not company_id:
        return HttpResponse(_("Your account is not assigned to a company."), status=403)
    company = Company._base_manager.get(pk=company_id)
    can_edit = request.user.has_perm("payroll.change_payslipautogenerate")
    if request.method == "POST" and not can_edit:
        return HttpResponse(_("Permission denied."), status=403)

    saved = False
    if request.method == "POST":
        with transaction.atomic():
            Company._base_manager.select_for_update().get(pk=company_id)
            policy = LossOfPayPolicy._base_manager.filter(company_id=company_id).first()
            form = LossOfPayPolicyForm(
                request.POST, instance=policy or LossOfPayPolicy(company=company)
            )
            if form.is_valid():
                form.save()
                saved = True
    else:
        policy = LossOfPayPolicy._base_manager.filter(company_id=company_id).first()
        form = LossOfPayPolicyForm(instance=policy or LossOfPayPolicy(company=company))

    if not can_edit:
        for field in form.fields.values():
            field.disabled = True

    return render(
        request,
        "cbv/payroll_settings/loss_of_pay.html",
        {
            "form": form,
            "company": company,
            "can_edit": can_edit,
            "saved": saved,
            "configured": bool(policy) or saved,
        },
    )

"""Platform developer console for company registration oversight."""

from django import forms
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from base.forms import CompanyForm
from base.models import Company
from base.platform_access import platform_developer_required
from employee.models import Employee, EmployeeWorkInformation


class DeveloperCompanyForm(CompanyForm):
    """Company form used only by the platform developer console."""

    is_active = forms.BooleanField(label=_("Company account is active"), required=False)

    class Meta(CompanyForm.Meta):
        fields = (
            "company",
            "hq",
            "address",
            "country",
            "state",
            "city",
            "zip",
            "icon",
            "is_active",
        )
        exclude = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # CompanyForm hides HQ from a normal one-company HR account. Platform
        # developers need to be able to correct it without entering a tenant.
        if "hq" not in self.fields:
            self.fields["hq"] = forms.BooleanField(
                label=_("Headquarters"), required=False
            )


def _company_rows(search_query=""):
    companies = Company.objects.select_related("created_by").order_by("company", "pk")
    if search_query:
        companies = companies.filter(
            Q(company__icontains=search_query)
            | Q(address__icontains=search_query)
            | Q(city__icontains=search_query)
            | Q(state__icontains=search_query)
            | Q(country__icontains=search_query)
        )
    companies = list(companies)
    company_ids = [company.pk for company in companies]
    if not company_ids:
        return companies

    employee_counts = {
        row["company_id"]: row
        for row in EmployeeWorkInformation._base_manager.filter(
            company_id_id__in=company_ids
        )
        .values("company_id")
        .annotate(
            employee_count=Count("employee_id", distinct=True),
            active_employee_count=Count(
                "employee_id", filter=Q(employee_id__is_active=True), distinct=True
            ),
        )
    }
    administrators = (
        Employee._base_manager.filter(
            employee_work_info__company_id_id__in=company_ids,
            employee_user_id__is_superuser=True,
            is_active=True,
        )
        .select_related("employee_user_id", "employee_work_info__company_id")
        .order_by("employee_first_name", "pk")
    )
    administrators_by_company = {company_id: [] for company_id in company_ids}
    for administrator in administrators:
        company_id = administrator.employee_work_info.company_id_id
        administrators_by_company[company_id].append(administrator)

    for company in companies:
        counts = employee_counts.get(company.pk, {})
        company.employee_count = counts.get("employee_count", 0)
        company.active_employee_count = counts.get("active_employee_count", 0)
        company.company_administrators = administrators_by_company[company.pk]
    return companies


@platform_developer_required
@require_http_methods(["GET"])
def developer_dashboard(request):
    search_query = request.GET.get("q", "").strip()[:100]
    companies = _company_rows(search_query)
    all_companies = Company.objects.all()
    context = {
        "companies": companies,
        "search_query": search_query,
        "total_companies": all_companies.count(),
        "active_companies": all_companies.filter(is_active=True).count(),
        "archived_companies": all_companies.filter(is_active=False).count(),
        "unrecorded_registrations": all_companies.filter(
            created_by__isnull=True
        ).count(),
    }
    return render(request, "developer/dashboard.html", context)


@platform_developer_required
@require_http_methods(["GET", "POST"])
def developer_company_edit(request, pk):
    company = get_object_or_404(Company.objects.select_related("created_by"), pk=pk)
    if request.method == "POST":
        form = DeveloperCompanyForm(request.POST, request.FILES, instance=company)
        if form.is_valid():
            form.save()
            messages.success(request, _("Company details updated."))
            return redirect("developer-dashboard")
    else:
        form = DeveloperCompanyForm(instance=company)

    employee_count = EmployeeWorkInformation._base_manager.filter(
        company_id=company
    ).count()
    return render(
        request,
        "developer/company_edit.html",
        {"company": company, "form": form, "employee_count": employee_count},
    )

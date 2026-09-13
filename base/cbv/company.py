"""
this page is handling the cbv methods for company in settings
"""

from typing import Any

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _

from base.auth_backends import get_account_companies, single_company_login_active
from base.filters import CompanyFilter
from base.forms import CompanyForm
from base.models import Company
from horilla.http.response import HorillaRedirect
from horilla_views.cbv_methods import login_required, permission_required
from horilla_views.forms import DynamicBulkUpdateForm
from horilla_views.generic.cbv.views import (
    HorillaFormView,
    HorillaListView,
    HorillaNavView,
)


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required(perm="base.view_company"), name="dispatch")
class CompanyListView(HorillaListView):
    """
    list view for company in settings
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("company-list")
        self.actions = []
        if self.request.user.has_perm("base.change_company"):
            self.actions.append(
                {
                    "action": _("Edit"),
                    "icon": "create-outline",
                    "attrs": """
                        class="oh-btn oh-btn--light-bkg oh-btn--sq-sm"
                        hx-get='{get_update_url}?instance_ids={ordered_ids}'
								hx-target="#genericModalBody"
								data-toggle="oh-modal-toggle"
								data-target="#genericModal"
                      """,
                }
            )
        if (
            not single_company_login_active()
            and self.request.user.has_perm("base.delete_company")
        ):
            self.actions.append(
                {
                    "action": _("Delete"),
                    "icon": "trash-outline",
                    "attrs": """
                            class="oh-btn oh-btn--danger oh-btn--sq-sm"
                            hx-get="{get_delete_url}?model=base.company&pk={pk}"
                            data-toggle="oh-modal-toggle"
                            data-target="#deleteConfirmation"
                            hx-target="#deleteConfirmationBody"
                        """,
                }
            )

    model = Company
    filter_class = CompanyFilter
    selected_instances_key_id = "selectedInstance"
    bulk_update_fields = ["country", "state", "city", "zip"]

    def get(self, request, *args, **kwargs):
        if single_company_login_active():
            return render(
                request,
                "base/company/company_profile.html",
                {"company": get_account_companies(request.user).first()},
            )
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if single_company_login_active():
            return HttpResponse(status=405)
        return super().post(request, *args, **kwargs)

    def bulk_update_accessibility(self):
        return not single_company_login_active() and super().bulk_update_accessibility()

    def import_accessibility(self):
        return not single_company_login_active() and super().import_accessibility()

    def get_bulk_form(self):
        """
        Bulk from generating method
        """

        form = DynamicBulkUpdateForm(
            root_model=Company, bulk_update_fields=self.bulk_update_fields
        )

        form.fields["country"] = forms.ChoiceField(
            widget=forms.Select(
                attrs={
                    "class": "oh-select oh-select-2",
                    "required": True,
                    "style": "width: 100%; height:45px;",
                }
            )
        )

        form.fields["state"] = forms.ChoiceField(
            widget=forms.Select(
                attrs={
                    "class": "oh-select oh-select-2",
                    "required": True,
                    "style": "width: 100%; height:45px;",
                }
            )
        )

        return form

    columns = [
        (_("Company"), "company_icon_with_name"),
        (_("Is Hq"), "hq"),
        (_("Address"), "address"),
        (_("Country"), "country"),
        (_("State"), "state"),
        (_("City"), "city"),
        (_("Zip"), "zip"),
    ]

    sortby_mapping = [
        (_("Company"), "company_icon_with_name"),
        (_("Country"), "country"),
        (_("State"), "state"),
        (_("City"), "city"),
        (_("Zip"), "zip"),
    ]

    row_attrs = """
                id="companyTr{get_delete_instance}"
                """

    header_attrs = {
        "company_icon_with_name": """ style="width:180px !important" """,
        "action": """ style="width:180px !important" """,
    }


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required(perm="base.view_company"), name="dispatch")
class CompanyNavView(HorillaNavView):
    """
    nav bar of the department view
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("company-list")
        if (
            not single_company_login_active()
            and self.request.user.has_perm("base.add_company")
        ):
            self.create_attrs = f"""
                                onclick = "event.stopPropagation();"
                                data-toggle="oh-modal-toggle"
                                data-target="#genericModal"
                                hx-target="#genericModalBody"
                                hx-get="{reverse('company-create-form')}"
                                """

    nav_title = _("Company")
    search_swap_target = "#listContainer"
    filter_instance = CompanyFilter()


@method_decorator(login_required, name="dispatch")
class CompanyCreateForm(HorillaFormView):
    """
    form view for creating and editing company in settings
    """

    model = Company
    form_class = CompanyForm
    new_display_title = _("Create Company")
    template_name = "cbv/company/company_form.html"

    def dispatch(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        if single_company_login_active() and pk is None:
            return HttpResponse(status=403)
        permission = "base.change_company" if pk is not None else "base.add_company"
        if not request.user.has_perm(permission):
            return HttpResponse(status=403)
        if pk is not None:
            get_object_or_404(get_account_companies(request.user), pk=pk)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        if pk is None:
            return None
        return get_object_or_404(get_account_companies(self.request.user), pk=pk)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        if self.form.instance and getattr(self.form.instance, "pk", None):
            self.form_class.verbose_name = _("Update Company")

        form.fields["country"].widget = forms.Select(
            attrs={
                "class": "oh-select oh-select-2",
            }
        )
        form.fields["state"].widget = forms.Select(
            attrs={"class": "oh-select oh-select-2"}
        )
        return form

    def form_invalid(self, form: Any) -> HttpResponse:
        """
        Handles and renders form errors or defers to superclass.
        """

        if self.form.instance and getattr(self.form.instance, "pk", None):
            self.form_class.verbose_name = _("Update Company")

        if not form.is_valid():
            errors = form.errors.as_data()
            return render(
                self.request, self.template_name, {"form": form, "errors": errors}
            )
        return super().form_invalid(form)

    def form_valid(self, form: CompanyForm) -> HttpResponse:
        if form.is_valid():
            updating = bool(form.instance.pk)
            form.save()
            if updating:
                messages.success(
                    self.request, _("Company details updated successfully.")
                )
            else:
                messages.success(
                    self.request, _("Company created successfully.")
                )
            if single_company_login_active():
                return HorillaRedirect(
                    self.request, redirect_to=reverse("company-view")
                )
            return self.HttpResponse()

        return super().form_valid(form)

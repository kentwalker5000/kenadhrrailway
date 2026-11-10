"""Public company onboarding, separate from the deployment initialization wizard."""

import hashlib

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.template import Context
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from base.models import Company, CompanyGroupAssignment
from base.public_site import _public_templates
from employee.models import Employee, EmployeeWorkInformation, phone_validator

# Only the company and core HR setup records. In particular, shared auth groups,
# platform settings, and Django admin access are never granted by public signup.
ADMIN_MODELS = {
    "base": ("department", "jobposition", "jobrole", "worktype", "employeetype",
             "employeeshift", "employeeshiftschedule"),
    "employee": ("employee", "employeeworkinformation", "employeebankdetails"),
}


def registration_enabled():
    return bool(
        settings.KENADHR_COMPANY_REGISTRATION
        and settings.COMPANY_SCOPED_PERMISSIONS
        and settings.SINGLE_COMPANY_LOGIN
    )


class CompanyRegistrationForm(forms.Form):
    company = forms.CharField(label="Company name", max_length=50)
    country = forms.CharField(max_length=50)
    city = forms.CharField(max_length=50)
    address = forms.CharField(label="Office address", max_length=255)
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150)
    email = forms.EmailField(label="Work email", max_length=150,
                            help_text="Use this email address to sign in.")
    phone = forms.CharField(label="Phone number", max_length=20, validators=[phone_validator])
    password1 = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput,
                               help_text="Use at least 8 characters. Avoid common passwords.")
    password2 = forms.CharField(label="Confirm password", strip=False, widget=forms.PasswordInput)
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["autocomplete"] = {
                "company": "organization", "first_name": "given-name", "last_name": "family-name",
                "email": "email", "phone": "tel", "password1": "new-password", "password2": "new-password",
                "country": "country-name", "city": "address-level2", "address": "street-address",
            }.get(name, "off")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        User = get_user_model()
        if (User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists()
                or Employee._base_manager.filter(email__iexact=email).exists()):
            raise forms.ValidationError("An account already uses this email. Sign in or reset your password.")
        return email

    def clean(self):
        data = super().clean()
        if data.get("website"):
            raise forms.ValidationError("Unable to accept this registration.")
        if data.get("company") and data.get("address") and Company.objects.filter(
            company__iexact=data["company"], address__iexact=data["address"]
        ).exists():
            self.add_error("company", "This company and office address are already registered.")
        if data.get("password1"):
            user = get_user_model()(username=data.get("email", ""), email=data.get("email", ""),
                                    first_name=data.get("first_name", ""), last_name=data.get("last_name", ""))
            try:
                validate_password(data["password1"], user)
            except ValidationError as exc:
                self.add_error("password1", exc)
        if data.get("password1") and data.get("password2") and data["password1"] != data["password2"]:
            self.add_error("password2", "The passwords do not match.")
        return data

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        user = get_user_model().objects.create_user(
            username=data["email"], email=data["email"], password=data["password1"],
            first_name=data["first_name"], last_name=data["last_name"],
            is_staff=False, is_superuser=False,
        )
        company = Company.objects.create(
            company=data["company"], country=data["country"], city=data["city"],
            address=data["address"], state="", zip="", created_by=user,
        )
        employee = Employee.objects.create(
            employee_user_id=user, employee_first_name=data["first_name"],
            employee_last_name=data["last_name"], email=data["email"], phone=data["phone"],
        )
        # Employee.save creates a blank work-information record itself.
        EmployeeWorkInformation.objects.update_or_create(
            employee_id=employee, defaults={"company_id": company, "email": data["email"]},
        )
        # A dedicated group per company prevents edits to another tenant's role.
        group = Group.objects.create(name=f"Company {company.pk} administrators")
        allowed = Q(content_type__app_label="base", codename__in=("view_company", "change_company"))
        for app_label, models in ADMIN_MODELS.items():
            allowed |= Q(content_type__app_label=app_label, codename__in=[
                f"{action}_{model}" for model in models for action in ("add", "view", "change", "delete")
            ])
        allowed |= Q(content_type__app_label="employee", codename__in=("view_ownprofile", "change_ownprofile"))
        group.permissions.set(Permission.objects.filter(allowed))
        CompanyGroupAssignment.objects.create(user=user, company=company, group=group, created_by=user)
        CompanyGroupAssignment.sync_user_group_membership(user, group)
        return user, company


def _render(request, form, status=200, unavailable=False):
    return HttpResponse(_public_templates.get_template("register.html").render(Context({
        "form": form, "csrf_token": get_token(request), "unavailable": unavailable,
    })), status=status)


@sensitive_post_parameters("password1", "password2")
@never_cache
@require_http_methods(["GET", "POST"])
def register_company(request):
    if request.user.is_authenticated:
        return redirect("/")
    if not registration_enabled():
        return _render(request, None, status=503, unavailable=True)
    form = CompanyRegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        # Use the server's peer address; never trust a caller-supplied forwarding header.
        identity = hashlib.sha256(request.META.get("REMOTE_ADDR", "unknown").encode()).hexdigest()
        key = f"company-registration:{identity}"
        if cache.add(key, 1, timeout=3600):
            attempts = 1
        else:
            try:
                attempts = cache.incr(key)
            except ValueError:  # Bucket expired between add and incr.
                cache.add(key, 1, timeout=3600)
                attempts = 1
        if attempts > settings.KENADHR_REGISTRATION_HOURLY_LIMIT:
            form.add_error(None, "Too many registration attempts. Please try again in an hour.")
            response = _render(request, form, status=429)
            response["Retry-After"] = "3600"
            return response
        if form.is_valid():
            try:
                user, company = form.save()
            except (IntegrityError, ValidationError):
                form.add_error(None, "We could not create the account. Check your details; if you already registered, sign in.")
            else:
                login(request, user, backend="base.auth_backends.CompanyScopedBackend")
                request.session["selected_company"] = str(company.pk)
                return redirect("company-registration-complete")
    return _render(request, form)


@never_cache
@require_http_methods(["GET"])
def registration_complete(request):
    if not request.user.is_authenticated:
        return redirect("login")
    from base.auth_backends import get_home_company_id

    company = Company.objects.filter(pk=get_home_company_id(request.user)).first()
    if company is None or company.created_by_id != request.user.pk:
        return redirect("/")
    return HttpResponse(_public_templates.get_template("registered.html").render(Context({
        "company": company, "email": request.user.username,
    })))

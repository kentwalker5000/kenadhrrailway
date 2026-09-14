"""Protect employee identity and company assignments on ORM bulk updates."""

from django.core.exceptions import ValidationError
from django.dispatch import receiver

from base.auth_backends import get_home_company_id, single_company_login_active
from base.platform_access import is_platform_developer
from employee.models import Employee, EmployeeWorkInformation
from horilla.horilla_middlewares import _thread_locals
from horilla.signals import pre_bulk_update


@receiver(pre_bulk_update, sender=EmployeeWorkInformation)
@receiver(pre_bulk_update, sender=Employee)
def protect_employee_identity(sender, queryset, kwargs, **unused):
    request = getattr(_thread_locals, "request", None)
    if (
        not single_company_login_active()
        or not request
        or not request.user.is_authenticated
    ):
        return
    if is_platform_developer(request.user):
        return
    if (
        sender is Employee
        and {"employee_user_id", "employee_user_id_id", "id", "pk"} & kwargs.keys()
    ):
        raise ValidationError("Account identity cannot be changed through bulk update.")
    if sender is EmployeeWorkInformation:
        if {"employee_id", "employee_id_id", "id", "pk"} & kwargs.keys():
            raise ValidationError(
                "Employee identity cannot be changed through bulk update."
            )
        home = get_home_company_id(request.user)
        for field in ("company_id", "company_id_id"):
            if field in kwargs:
                value = getattr(kwargs[field], "pk", kwargs[field])
                if home is None or str(value) != str(home):
                    raise ValidationError(
                        "Employees must remain in your assigned company."
                    )

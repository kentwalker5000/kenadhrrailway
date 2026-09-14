"""Authorize an uploaded file through its owning record, never its URL alone."""

from functools import lru_cache

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.db import models

from base.auth_backends import get_home_company_id
from base.platform_access import is_platform_developer

# These rows only hold files. Their parent record controls access.
FILE_HOLDERS = {
    "base.baserequestfile",
    "base.attachment",
    "employee.notefiles",
    "employee.policymultiplefile",
    "recruitment.stagefiles",
    "leave.leaverequestfile",
    "asset.returnimages",
    "attendance.attendancerequestfile",
    "payroll.reimbursementmultipleattachment",
    "payroll.reimbursementfile",
    "offboarding.offboardingstagemultiplefile",
}
PARENTS = {
    "base.worktyperequestcomment": ("request_id",),
    "base.shiftrequestcomment": ("request_id",),
    "attendance.attendancerequestcomment": ("request_id",),
    "leave.leaverequestcomment": ("request_id",),
    "leave.leaveallocationrequestcomment": ("request_id",),
    "leave.compensatoryleaverequestcomment": ("request_id",),
    "payroll.reimbursementrequestcomment": ("request_id",),
    "recruitment.candidatedocument": ("candidate_id",),
    "recruitment.stagenote": ("candidate_id",),
    "recruitment.recruitmentsurveyanswer": ("candidate_id",),
    "recruitment.resume": ("recruitment_id",),
    "onboarding.onboardingportal": ("candidate_id",),
    "helpdesk.attachment": ("ticket", "comment"),
    "helpdesk.comment": ("ticket",),
    "asset.assetdocuments": ("asset_report",),
    "asset.assetreport": ("asset_id",),
    "offboarding.offboardingnote": ("employee_id",),
    "offboarding.exitreason": ("offboarding_employee_id",),
}


@lru_cache(maxsize=1)
def file_models():
    return tuple(
        (
            model,
            tuple(
                f.name for f in model._meta.fields if isinstance(f, models.FileField)
            ),
        )
        for model in apps.get_models()
        if not model._meta.proxy
        and not model._meta.model_name.startswith("historical")
        and any(isinstance(f, models.FileField) for f in model._meta.fields)
    )


def public_file(path):
    # Only actual published image records qualify, not an arbitrary directory
    # prefix (which could contain an unrelated upload).
    if not path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico")):
        return False
    return apps.get_model("base", "Company")._base_manager.filter(icon=path).exists()


def employee_access(user, employee, permission, company_id):
    info = getattr(employee, "employee_work_info", None)
    if not info or info.company_id_id != company_id:
        return False
    return (
        user.has_perm(permission)
        or employee.employee_user_id_id == user.pk
        or info.reporting_manager_id_id
        == getattr(getattr(user, "employee_get", None), "pk", None)
    )


def record_access(user, record, company_id, depth=0):
    if record is None or depth > 5:
        return False
    label = record._meta.label_lower
    permission = f"{record._meta.app_label}.view_{record._meta.model_name}"
    if label.startswith("horilla_backup."):
        return False  # OAuth secrets are never downloadable media.
    if label in FILE_HOLDERS:
        for relation in record._meta.related_objects:
            if relation.many_to_many:
                parents = relation.related_model._base_manager.filter(
                    **{relation.field.name: record.pk}
                )
                if any(
                    record_access(user, parent, company_id, depth + 1)
                    for parent in parents
                ):
                    return True
        return False
    if label in PARENTS:
        return any(
            record_access(user, getattr(record, field, None), company_id, depth + 1)
            for field in PARENTS[label]
        )

    employee_model = apps.get_model("employee", "Employee")
    if label == "employee.employee":
        info = getattr(record, "employee_work_info", None)
        return bool(info and info.company_id_id == company_id)

    # Determine tenant membership independently of request-local query scoping.
    manager = record.__class__._default_manager
    company_path = (
        manager.get_company_filter_path()
        if hasattr(manager, "get_company_filter_path")
        else None
    )
    if company_path:
        membership = models.Q(**{company_path: company_id})
        if label in {"employee.policy", "base.announcement", "leave.leavetype"}:
            membership |= models.Q(**{company_path + "__isnull": True})
        if not record.__class__._base_manager.filter(membership, pk=record.pk).exists():
            return False

    caller = getattr(user, "employee_get", None)
    caller_pk = getattr(caller, "pk", None)
    if label == "employee.policy":
        return (
            user.has_perm(permission)
            or record.is_visible_to_all
            or record.specific_employees.filter(pk=caller_pk).exists()
        )
    if label == "base.announcement":
        if user.has_perm(permission):
            return True
        return record.filtered_employees.filter(pk=caller_pk).exists() or (
            not record.employees.exists()
            and not record.department.exists()
            and not record.job_position.exists()
        )
    if label == "leave.leavetype":
        return True
    if label in {"recruitment.candidate", "recruitment.recruitment"}:
        recruitment = record.recruitment_id if label.endswith(".candidate") else record
        if recruitment.company_id_id != company_id:
            return False
        if user.has_perm(permission) or user.has_perm("recruitment.view_candidate"):
            return True
        return (
            recruitment.recruitment_managers.filter(pk=caller_pk).exists()
            or recruitment.stage_set.filter(stage_managers=caller_pk).exists()
        )
    if label in {"project.project", "project.task"}:
        if user.has_perm(permission):
            return True
        project = record.project if label.endswith(".task") else record
        return (
            project.managers.filter(pk=caller_pk).exists()
            or project.task_set.filter(
                models.Q(task_members=caller_pk) | models.Q(task_managers=caller_pk)
            ).exists()
        )
    if label == "helpdesk.ticket" and record.assigned_to.filter(pk=caller_pk).exists():
        return True

    # Private personnel records are visible to their owner, reporting manager,
    # or an HR user with the record's view permission, within the same company.
    for field_name in ("employee_id", "assigned_to_employee_id"):
        try:
            field = record._meta.get_field(field_name)
        except FieldDoesNotExist:
            continue
        if field.related_model is employee_model:
            related = getattr(record, field_name)
            employees = related.all() if field.many_to_many else [related]
            return any(
                employee_access(user, emp, permission, company_id)
                for emp in employees
                if emp
            )
    return bool(company_path and user.has_perm(permission))


def can_download(user, path):
    if (
        not user
        or not user.is_authenticated
        or not user.is_active
        or user.is_new_employee
    ):
        return False
    company_id = get_home_company_id(user)
    platform = is_platform_developer(user)
    if not company_id and not platform:
        return False
    parts = path.split("/")
    candidates = file_models()
    matching = [
        (model, fields)
        for model, fields in candidates
        if parts[:2] == [model._meta.app_label, model._meta.model_name]
    ]
    for model, fields in matching or candidates:
        if model._meta.app_label == "horilla_backup":
            continue
        match = models.Q()
        for field in fields:
            match |= models.Q(**{field: path})
        for record in model._base_manager.filter(match):
            try:
                if platform or record_access(user, record, company_id):
                    return True
            except ObjectDoesNotExist:
                continue
    return False

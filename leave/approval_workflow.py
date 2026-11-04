"""The web and API share the same ordered leave approval transaction."""
import hashlib
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from employee.models import Employee, EmployeeWorkInformation
from leave.models import AvailableLeave, LeaveManagerReview, LeaveRequest, LeaveRequestConditionApproval


def notify_hr_after_review(leave, actor, company_id):
    from notifications.signals import notify
    users = get_user_model().objects.filter(
        employee_get__employee_work_info__company_id_id=company_id, is_active=True,
    ).filter(Q(is_superuser=True) | Q(groups__permissions__codename="final_approve_leaverequest") |
             Q(user_permissions__codename="final_approve_leaverequest")).exclude(pk=actor.employee_user_id_id).distinct()
    for user in users:
        notify.send(actor, recipient=user, verb="A manager has reviewed a leave request. Your final HR approval is needed.",
                    icon="people-circle", redirect=f"/leave/request-view?id={leave.pk}")


def signature(leave):
    fields = (leave.employee_id_id, leave.leave_type_id_id, leave.start_date, leave.end_date,
              leave.start_date_breakdown, leave.end_date_breakdown, leave.requested_days)
    return hashlib.sha256(repr(fields).encode()).hexdigest()


def current_review(leave, manager_id):
    return LeaveManagerReview.objects.filter(leave_request=leave, reviewed_by_id=manager_id,
                                            request_signature=signature(leave)).first()


def is_ceo_for_hr_leave(leave, actor_work, work):
    """The CEO finalizes the HR lead's own request after their review."""
    if actor_work.employee_id_id != work.reporting_manager_id_id:
        return False
    position = actor_work.job_position_id
    title = position.job_position.strip().lower() if position else ""
    if "chief executive officer" not in title and title != "ceo":
        return False
    owner = leave.employee_id
    owner_user = owner.employee_user_id
    owner_position = work.job_position_id
    owner_title = owner_position.job_position.strip().lower() if owner_position else ""
    return bool((owner_user and owner_user.has_perm("leave.final_approve_leaverequest")) or
                "head of people and culture" in owner_title)


def approval_stage(leave):
    if leave.status != "requested":
        return leave.get_status_display()
    work = EmployeeWorkInformation.objects.filter(employee_id=leave.employee_id).first()
    if not work or not work.reporting_manager_id_id:
        return "Reporting manager needed"
    review = current_review(leave, work.reporting_manager_id_id)
    if not review:
        return "Awaiting manager review"
    manager_work = EmployeeWorkInformation.objects.filter(employee_id=work.reporting_manager_id).first()
    if manager_work and is_ceo_for_hr_leave(leave, manager_work, work):
        return "Awaiting CEO approval"
    return "Awaiting HR approval"


def can_approve(leave, user):
    actor = Employee.objects.filter(employee_user_id=user).first()
    if leave.status != "requested" or not actor or actor.pk == leave.employee_id_id:
        return False
    work = EmployeeWorkInformation.objects.filter(employee_id=leave.employee_id).first()
    actor_work = EmployeeWorkInformation.objects.filter(employee_id=actor).first()
    if not work or not actor_work or not work.company_id_id or work.company_id_id != actor_work.company_id_id:
        return False
    if not current_review(leave, work.reporting_manager_id_id):
        return actor.pk == work.reporting_manager_id_id
    ceo_hr_exception = is_ceo_for_hr_leave(leave, actor_work, work)
    manager_work = EmployeeWorkInformation.objects.filter(employee_id=work.reporting_manager_id).first()
    if manager_work and is_ceo_for_hr_leave(leave, manager_work, work) and not ceo_hr_exception:
        return False
    if actor.pk == work.reporting_manager_id_id and not ceo_hr_exception:
        return False
    pending = LeaveRequestConditionApproval.objects.filter(leave_request_id=leave, is_approved=False).order_by("sequence", "pk").first()
    if pending:
        return pending.manager_id_id == actor.pk and not pending.is_rejected
    return ceo_hr_exception or user.has_perm("leave.final_approve_leaverequest")


def can_reject(leave, user):
    if leave.status == "requested":
        return can_approve(leave, user)
    actor = Employee.objects.filter(employee_user_id=user).first()
    if leave.status != "approved" or not actor or actor.pk == leave.employee_id_id:
        return False
    company_id = EmployeeWorkInformation.objects.filter(employee_id=leave.employee_id).values_list("company_id_id", flat=True).first()
    return bool(company_id and user.has_perm("leave.final_approve_leaverequest") and
                EmployeeWorkInformation.objects.filter(employee_id=actor, company_id_id=company_id).exists())


@transaction.atomic
def approve_leave(leave_id, user):
    leave = LeaveRequest.objects.select_for_update().get(pk=leave_id)
    actor = Employee.objects.filter(employee_user_id=user).first()
    if not actor or actor.pk == leave.employee_id_id:
        raise PermissionDenied("You cannot review or approve your own leave request.")
    work = EmployeeWorkInformation.objects.filter(employee_id=leave.employee_id).first()
    actor_work = EmployeeWorkInformation.objects.filter(employee_id=actor).first()
    if not work or not actor_work or not work.company_id_id or work.company_id_id != actor_work.company_id_id:
        raise PermissionDenied("The approver must belong to the employee's company.")
    if leave.status != "requested":
        raise ValidationError("Only pending leave requests can be reviewed or approved.")
    if not work.reporting_manager_id_id or work.reporting_manager_id_id == leave.employee_id_id:
        raise ValidationError("Assign a reporting manager before reviewing this leave request.")
    review = current_review(leave, work.reporting_manager_id_id)
    if not review:
        if actor.pk != work.reporting_manager_id_id:
            raise PermissionDenied("The reporting manager must review this request before HR can approve it.")
        LeaveManagerReview.objects.update_or_create(leave_request=leave, defaults={
            "reviewed_by": actor, "request_signature": signature(leave),
        })
        first_stage = LeaveRequestConditionApproval.objects.filter(leave_request_id=leave, is_approved=False).order_by("sequence", "pk").first()
        if first_stage and first_stage.manager_id_id == actor.pk and not first_stage.is_rejected:
            first_stage.is_approved = True
            first_stage.save(update_fields=["is_approved"])
        if is_ceo_for_hr_leave(leave, actor_work, work):
            return leave, "CEO review recorded. Awaiting CEO final approval."
        transaction.on_commit(lambda: notify_hr_after_review(leave, actor, work.company_id_id), robust=True)
        return leave, "Manager review recorded. Awaiting company Admin/HR approval."
    ceo_hr_exception = is_ceo_for_hr_leave(leave, actor_work, work)
    manager_work = EmployeeWorkInformation.objects.filter(employee_id=work.reporting_manager_id).first()
    if manager_work and is_ceo_for_hr_leave(leave, manager_work, work) and not ceo_hr_exception:
        raise PermissionDenied("The CEO must give final approval for the HR lead's leave.")
    if actor.pk == review.reviewed_by_id and not ceo_hr_exception:
        raise PermissionDenied("Your review is recorded. A different company Admin/HR must give final approval.")
    pending = LeaveRequestConditionApproval.objects.filter(leave_request_id=leave, is_approved=False).order_by("sequence", "pk").first()
    if pending:
        if pending.manager_id_id != actor.pk:
            raise PermissionDenied("Earlier approval stages must be completed first.")
        if pending.is_rejected:
            raise ValidationError("This approval stage was rejected.")
        pending.is_approved = True
        pending.save(update_fields=["is_approved"])
        return leave, "Approval stage recorded. Awaiting remaining stages and final HR approval."
    if not ceo_hr_exception and not user.has_perm("leave.final_approve_leaverequest"):
        raise PermissionDenied("Only the company's Admin/HR can give final approval.")
    available = AvailableLeave.objects.select_for_update().filter(employee_id=leave.employee_id, leave_type_id=leave.leave_type_id).first()
    if not available or available.available_days + available.carryforward_days < leave.requested_days:
        raise ValidationError("The employee does not have enough available leave days.")
    carry = min(available.carryforward_days, leave.requested_days)
    regular = leave.requested_days - carry
    available.carryforward_days -= carry
    available.available_days -= regular
    leave.approved_carryforward_days = carry
    leave.approved_available_days = regular
    leave.status = "approved"
    available.save()
    leave.save()
    return leave, "Leave request approved by CEO." if ceo_hr_exception else "Leave request approved by HR."

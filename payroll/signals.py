from datetime import datetime

from django.db.models.signals import post_save, pre_delete, m2m_changed
from django.db.models.deletion import ProtectedError
from django.dispatch import receiver

from employee.models import EmployeeWorkInformation
from payroll.methods.deductions import create_deductions
from payroll.models.models import Allowance, Contract, Deduction, LoanAccount, Payslip


@receiver(pre_delete, sender=Payslip)
def protect_finalised_payslip(sender, instance, **kwargs):
    if instance.status in ("confirmed", "paid"):
        raise ProtectedError(
            "Confirmed or paid payslips cannot be deleted.", [instance]
        )


@receiver(pre_delete, sender=Deduction)
def protect_reserved_installment(sender, instance, **kwargs):
    if (
        instance.is_installment
        and Payslip._base_manager.filter(installment_ids=instance).exists()
    ):
        raise ProtectedError(
            "Installments included in payroll cannot be deleted.", [instance]
        )


@receiver(post_save, sender=EmployeeWorkInformation)
def employeeworkinformation_post_save(sender, instance, **_kwargs):
    """
    This method is used to override the save method for EmployeeWorkInformation Model
    """
    # Skip during fixture load — demo contracts come from payroll_data.json
    if _kwargs.get("raw"):
        return

    active_employee = (
        instance.employee_id
        if instance.employee_id and instance.employee_id.is_active == True
        else None
    )
    if active_employee is not None:
        all_contracts = Contract.objects.entire()
        contract_exists = all_contracts.filter(employee_id_id=active_employee).exists()
        if not contract_exists:
            contract = Contract()
            contract.contract_name = f"{active_employee}'s Contract"
            contract.employee_id = active_employee
            contract.contract_start_date = (
                instance.date_joining if instance.date_joining else datetime.today()
            )
            contract.wage = (
                instance.basic_salary if instance.basic_salary is not None else 0
            )
            contract.contract_status = "active"
            contract.save()


@receiver(post_save, sender=LoanAccount)
def create_installments(sender, instance, created, **kwargs):
    """Create components once; preserve schedules already reserved by payroll."""
    if kwargs.get("raw"):
        return
    from payroll.methods.loans import allowance_ids_on_payslips

    slips = Payslip._base_manager.filter(employee_id=instance.employee_id)
    payout_used = instance.allowance_id_id in allowance_ids_on_payslips(slips)
    payout_allowed = (
        instance.type != "fine"
        and not getattr(instance, "asset_id_id", None)
        and not instance.disbursed_externally
    )
    if payout_allowed and not instance.settled and not payout_used:
        allowance = instance.allowance_id or Allowance()
        allowance.title = instance.title
        allowance.amount = instance.loan_amount
        allowance.one_time_date = instance.provided_date
        allowance.is_fixed = True
        allowance.is_taxable = False
        allowance.is_loan = True
        allowance.if_condition = "ge"
        allowance.only_show_under_employee = True
        allowance.include_active_employees = False
        allowance.save()
        allowance.specific_employees.set([instance.employee_id])
        if instance.allowance_id_id != allowance.pk:
            instance.allowance_id = allowance
            # Avoid recursively saving the loan and rebuilding its schedule.
            LoanAccount._base_manager.filter(pk=instance.pk).update(
                allowance_id=allowance
            )
    elif not payout_allowed and instance.allowance_id_id and not payout_used:
        allowance = instance.allowance_id
        LoanAccount._base_manager.filter(pk=instance.pk).update(allowance_id=None)
        instance.allowance_id = None
        allowance.delete()

    if instance.settled:
        return
    deductions = instance.deduction_ids.all()
    if slips.filter(installment_ids__in=deductions).exists():
        return
    if deductions.exists() and not getattr(instance, "_schedule_changed", False):
        return
    deductions.delete()
    instance.deduction_ids.add(
        *[
            create_deductions(instance, amount, due_date)
            for due_date, amount in instance.get_installments().items()
        ]
    )


@receiver(post_save, sender=Payslip)
def record_loan_repayments(sender, instance, **kwargs):
    if kwargs.get("raw"):
        # loaddata assigns M2M fields after saving the deserialized object.
        instance._loading_loan_fixture = True
        return
    if not getattr(instance, "_assigning_installments", False):
        from payroll.methods.loans import settle_repaid_loans

        settle_repaid_loans(instance)


@receiver(m2m_changed, sender=Payslip.installment_ids.through)
def protect_installment_reservations(
    sender, instance, action, reverse, pk_set, **kwargs
):
    from django.core.exceptions import ValidationError
    from employee.models import Employee
    from payroll.methods.loans import settle_repaid_loans

    if getattr(instance, "_loading_loan_fixture", False):
        return
    if reverse:
        # All payroll writes go through the payslip side. Prevent reverse writes
        # from bypassing the same reservation/finalisation checks.
        if action.startswith("pre_"):
            raise ValidationError(
                "Change installment reservations through the payslip."
            )
        return
    if action.startswith("pre_"):
        Employee._base_manager.select_for_update().get(pk=instance.employee_id_id)
        status = Payslip._base_manager.values_list("status", flat=True).get(
            pk=instance.pk
        )
        current = set(instance.installment_ids.values_list("pk", flat=True))
        changes_existing = action in ("pre_remove", "pre_clear") and bool(current)
        # Initial assignment while creating a final payslip is allowed; later
        # changes to financial history are not.
        if (
            status in ("confirmed", "paid")
            and not getattr(instance, "_assigning_installments", False)
            and (changes_existing or (action == "pre_add" and pk_set))
        ):
            raise ValidationError(
                "Confirmed or paid installment reservations cannot be changed."
            )
        if action == "pre_add" and pk_set:
            if (
                Payslip._base_manager.exclude(pk=instance.pk)
                .filter(installment_ids__in=pk_set)
                .exists()
            ):
                raise ValidationError(
                    "An installment is already reserved by another payslip."
                )
            if Deduction._base_manager.filter(
                pk__in=pk_set, specific_employees=instance.employee_id
            ).distinct().count() != len(pk_set):
                raise ValidationError(
                    "Installments must belong to the payslip employee."
                )
    if action == "post_add":
        settle_repaid_loans(instance)

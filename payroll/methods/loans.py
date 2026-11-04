"""Loan reservations and repayment accounting shared by every payroll entry point."""

from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.db import transaction
from django.utils import timezone

from payroll.models.models import Deduction, LoanAccount, Payslip


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def other_payslips(employee, start_date, end_date):
    # Drafts reserve components too. Regenerating the SAME period keeps its own
    # reservation, whereas deleting the draft makes its components available.
    return Payslip._base_manager.filter(employee_id=employee).exclude(
        start_date=start_date, end_date=end_date
    )


def allowance_ids_on_payslips(payslips):
    return {
        item.get("allowance_id")
        for data in payslips.values_list("pay_head_data", flat=True)
        if isinstance(data, dict)
        for item in data.get("allowances", [])
        if isinstance(item, dict) and item.get("allowance_id") is not None
    }


def eligible_deductions(deductions, employee, start_date, end_date):
    regular = Q(is_installment=False) & (
        Q(one_time_date__isnull=True) | Q(one_time_date__range=(start_date, end_date))
    )
    # Unreserved arrears remain due; don't silently lose a missed month.
    due = Q(is_installment=True, one_time_date__lte=end_date)
    reserved = (
        other_payslips(employee, start_date, end_date)
        .filter(installment_ids__isnull=False)
        .values("installment_ids")
    )
    settled = LoanAccount._base_manager.filter(
        settled=True, deduction_ids__isnull=False
    ).values("deduction_ids")
    return (
        deductions.filter(regular | due)
        .exclude(is_installment=True, pk__in=reserved)
        .exclude(is_installment=True, pk__in=settled)
        .distinct()
    )


def filter_loan_allowances(allowances, employee, start_date, end_date):
    used = allowance_ids_on_payslips(other_payslips(employee, start_date, end_date))
    external = LoanAccount._base_manager.filter(
        Q(disbursed_externally=True) | Q(settled=True), allowance_id__isnull=False
    ).values("allowance_id")
    return allowances.exclude(is_loan=True, pk__in=used).exclude(
        is_loan=True, pk__in=external
    )


def validate_loan_reservations(employee, start_date, end_date, installments, pay_data):
    """Recheck a calculated snapshot under save_payslip's employee lock."""
    ids = {item.pk for item in installments}
    other = other_payslips(employee, start_date, end_date)
    if other.filter(installment_ids__in=ids).exists():
        raise ValidationError(
            "A loan installment is already on another payslip. Recalculate payroll."
        )
    rows = {
        row["deduction_id"]: row["amount"]
        for key in ("pretax_deductions", "post_tax_deductions")
        for row in pay_data.get(key, [])
        if row.get("deduction_id") in ids
    }
    current = Deduction._base_manager.filter(
        pk__in=ids, specific_employees=employee
    ).distinct()
    if set(current.values_list("pk", flat=True)) != ids:
        raise ValidationError("The loan schedule changed. Recalculate payroll.")
    for deduction in current:
        if deduction.pk not in rows or money(rows[deduction.pk]) != money(
            deduction.amount
        ):
            raise ValidationError(
                "The installment amount changed. Recalculate payroll."
            )
    # Existing final payments may still be previewed, but no new reservation of
    # a manually settled loan may be written.
    if LoanAccount._base_manager.filter(settled=True, deduction_ids__in=ids).exists():
        raise ValidationError("This loan has been settled. Recalculate payroll.")
    reserved_ids = other.filter(installment_ids__isnull=False).values("installment_ids")
    for loan in LoanAccount._base_manager.filter(deduction_ids__in=ids).distinct():
        already_reserved = (
            loan.deduction_ids.filter(pk__in=reserved_ids).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )
        proposed = (
            loan.deduction_ids.filter(pk__in=ids).aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )
        if money(already_reserved) + money(proposed) > money(loan.loan_amount):
            raise ValidationError(
                "Loan repayments exceed the outstanding balance. Review the repayment schedule."
            )
    allowance_ids = {row.get("allowance_id") for row in pay_data.get("allowances", [])}
    loans = LoanAccount._base_manager.filter(allowance_id__in=allowance_ids)
    used = allowance_ids_on_payslips(other)
    for loan in loans.select_related("allowance_id"):
        if (
            loan.employee_id_id != employee.pk
            or loan.disbursed_externally
            or loan.settled
            or loan.allowance_id_id in used
        ):
            raise ValidationError(
                "A loan payout is already recorded or was paid outside payroll. Recalculate payroll."
            )
        amount = next(
            row["amount"]
            for row in pay_data["allowances"]
            if row.get("allowance_id") == loan.allowance_id_id
        )
        if money(amount) != money(loan.loan_amount):
            raise ValidationError(
                "The loan payout amount changed. Recalculate payroll."
            )


def paid_installments(loan):
    paid_ids = Payslip._base_manager.filter(
        status="paid", installment_ids__isnull=False
    ).values("installment_ids")
    return loan.deduction_ids.filter(pk__in=paid_ids)


def paid_amount(loan):
    return money(paid_installments(loan).aggregate(total=Sum("amount"))["total"] or 0)


def settle_repaid_loans(payslip):
    if payslip.status != "paid":
        return
    for loan in LoanAccount._base_manager.filter(
        deduction_ids__in=payslip.installment_ids.all(), settled=False
    ).distinct():
        if paid_amount(loan) >= money(loan.loan_amount):
            # Do not invoke schedule rebuilding while recording repayment.
            LoanAccount._base_manager.filter(pk=loan.pk, settled=False).update(
                settled=True, settled_date=timezone.now()
            )


@transaction.atomic
def change_installment_amount(loan, deduction_id, raw_amount):
    """Redistribute only unreserved future installments, preserving the total."""
    from decimal import InvalidOperation
    from employee.models import Employee
    from base.methods import get_next_month_same_date
    from payroll.methods.deductions import create_deductions

    Employee._base_manager.select_for_update().get(pk=loan.employee_id_id)
    loan.refresh_from_db()
    if loan.settled:
        raise ValidationError("A settled loan cannot be changed.")
    try:
        amount = Decimal(str(raw_amount))
        if not amount.is_finite() or amount < 0 or amount != money(amount):
            raise ValueError
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(
            "Enter a non-negative amount with no more than two decimal places."
        )
    deductions = loan.deduction_ids.order_by("one_time_date", "pk")
    deduction = deductions.filter(pk=deduction_id).first()
    if not deduction:
        raise ValidationError("Installment not found.")
    affected = deductions.filter(one_time_date__gte=deduction.one_time_date)
    if Payslip._base_manager.filter(installment_ids__in=affected).exists():
        raise ValidationError(
            "This change would alter an installment already included in payroll."
        )
    before = deductions.filter(one_time_date__lt=deduction.one_time_date)
    remaining = money(loan.loan_amount) - money(
        before.aggregate(total=Sum("amount"))["total"] or 0
    )
    if amount > remaining:
        raise ValidationError(
            "The installment cannot exceed the remaining scheduled balance."
        )
    after = list(deductions.filter(one_time_date__gt=deduction.one_time_date))
    remainder = remaining - amount
    if not after and remainder:
        new = create_deductions(
            loan, float(remainder), get_next_month_same_date(deduction.one_time_date)
        )
        loan.deduction_ids.add(new)
        after = [new]
    if after:
        share = money(remainder / len(after))
        amounts = [share] * (len(after) - 1) + [remainder - share * (len(after) - 1)]
        if any(value < 0 for value in amounts):
            raise ValidationError(
                "Reduce the number of future installments before applying this amount."
            )
        for item, value in zip(after, amounts):
            if value == 0:
                item.delete()
            else:
                item.amount = float(value)
                item.save(update_fields=["amount"])
    if amount == 0:
        # Deferring a payment must not create a zero-valued 'paid' installment.
        deduction.delete()
    else:
        deduction.amount = float(amount)
        deduction.save(update_fields=["amount"])
    LoanAccount._base_manager.filter(pk=loan.pk).update(
        installments=loan.deduction_ids.count()
    )

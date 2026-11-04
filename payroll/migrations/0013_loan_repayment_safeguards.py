from django.db import migrations, models


def correct_unreserved_components(apps, schema_editor):
    """Correct editable components without rewriting any saved payslip snapshot."""
    Loan = apps.get_model("payroll", "LoanAccount")
    Deduction = apps.get_model("payroll", "Deduction")
    Allowance = apps.get_model("payroll", "Allowance")
    Payslip = apps.get_model("payroll", "Payslip")
    db = schema_editor.connection.alias
    finalised = Payslip.objects.using(db).filter(status__in=("confirmed", "paid"))
    reserved = finalised.filter(installment_ids__isnull=False).values("installment_ids")
    loan_deductions = (
        Loan.objects.using(db)
        .filter(deduction_ids__isnull=False)
        .values("deduction_ids")
    )
    Deduction.objects.using(db).filter(pk__in=loan_deductions).exclude(
        pk__in=reserved
    ).update(is_pretax=False, if_condition="ge")
    used_allowances = set()
    for data in finalised.values_list("pay_head_data", flat=True).iterator():
        if isinstance(data, dict):
            used_allowances.update(
                row.get("allowance_id")
                for row in data.get("allowances", [])
                if isinstance(row, dict)
            )
    used_allowances.discard(None)
    loan_allowances = (
        Loan.objects.using(db).filter(allowance_id__isnull=False).values("allowance_id")
    )
    Allowance.objects.using(db).filter(pk__in=loan_allowances).exclude(
        pk__in=used_allowances
    ).update(is_taxable=False, if_condition="ge")


class Migration(migrations.Migration):
    dependencies = [("payroll", "0012_repair_installed_ghana_templates")]

    operations = [
        migrations.AddField(
            model_name="loanaccount",
            name="disbursed_externally",
            field=models.BooleanField(
                default=False,
                verbose_name="Already paid outside payroll",
                help_text="Enable if the employee has already received the money. Payroll will only collect repayments.",
            ),
        ),
        migrations.RunPython(correct_unreserved_components, migrations.RunPython.noop),
    ]

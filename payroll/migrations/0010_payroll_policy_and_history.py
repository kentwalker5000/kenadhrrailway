from datetime import date
from django.db import migrations, models
import django.db.models.deletion


def repair_templates(apps, schema_editor):
    Filing = apps.get_model("payroll", "FilingStatus")
    Bracket = apps.get_model("payroll", "TaxBracket")
    Deduction = apps.get_model("payroll", "Deduction")
    Structure = apps.get_model("payroll", "SalaryStructure")
    for item in Deduction.objects.filter(title="SSNIT (Employee 5.5%; Employer 13%)"):
        item.statutory_code = "ghana_pension"
        if item.maximum_amount == 316.25:
            item.maximum_amount = 3795
        if item.employer_maximum_amount == 747.5:
            item.employer_maximum_amount = 8970
        item.save()
    Structure.objects.filter(title="National Service — No Deductions").update(deductions_exempt=True)
    Filing.objects.filter(filing_status="National Service — No PAYE").update(payroll_policy="national_service")
    for filing in Filing.objects.filter(filing_status="Ghana PAYE (Resident, 2026)"):
        previous, _ = Filing.objects.get_or_create(
            company_id_id=filing.company_id_id, filing_status="Ghana PAYE (2024-Aug 2026)",
            defaults={"based_on": "taxable_gross_pay", "payroll_policy": "ghana_resident",
                      "effective_from": date(2024, 1, 1), "effective_to": date(2026, 8, 31)},
        )
        for lower, upper, rate in (
            (0, 5880, 0), (5880, 7200, 5), (7200, 8760, 10),
            (8760, 46760, 17.5), (46760, 238760, 25),
            (238760, 600000, 30), (600000, float("inf"), 35),
        ):
            Bracket.objects.get_or_create(filing_status_id=previous, min_income=lower,
                                         defaults={"max_income": upper, "tax_rate": rate})
        filing.payroll_policy = "ghana_resident"
        filing.effective_from = date(2026, 9, 1)
        filing.effective_to = date(2026, 12, 31)
        filing.previous_version = previous
        filing.save()


class Migration(migrations.Migration):
    dependencies = [("payroll", "0009_deduction_employer_maximum_amount")]
    operations = [
        migrations.AddField("filingstatus", "effective_from", models.DateField(null=True, blank=True)),
        migrations.AddField("filingstatus", "effective_to", models.DateField(null=True, blank=True)),
        migrations.AddField("filingstatus", "previous_version", models.ForeignKey(
            to="payroll.filingstatus", null=True, blank=True,
            on_delete=django.db.models.deletion.PROTECT, related_name="later_versions")),
        migrations.AddField("filingstatus", "payroll_policy", models.CharField(
            max_length=30, default="standard", choices=[("standard", "Standard"),
                ("ghana_resident", "Ghana resident"), ("national_service", "National Service - no deductions")])),
        migrations.AddField("salarystructure", "deductions_exempt", models.BooleanField(
            default=False, help_text="Exclude all deduction components and PAYE for assigned staff.")),
        migrations.AddField("deduction", "statutory_code", models.CharField(
            max_length=30, blank=True, default="", editable=False)),
    ]

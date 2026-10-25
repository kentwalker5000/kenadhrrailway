# Generated manually for the petty-cash cashbook.

import django.core.validators
import django.db.models.deletion
import horilla.models
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("base", "0016_seed_default_export_permission"),
        ("employee", "0005_alter_employee_phone_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PettyCashAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True, verbose_name="Created At")),
                ("is_active", models.BooleanField(default=True, verbose_name="Is Active")),
                ("name", models.CharField(max_length=120, verbose_name="Float name")),
                ("opening_balance", models.DecimalField(decimal_places=2, default=0, max_digits=12, validators=[django.core.validators.MinValueValidator(0)], verbose_name="Opening balance")),
                ("currency", models.CharField(choices=[("GHS", "GHS"), ("USD", "USD"), ("GBP", "GBP")], default="GHS", max_length=3)),
                ("notes", models.TextField(blank=True, verbose_name="Notes")),
                ("company_id", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="base.company", verbose_name="Company")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name="Created By")),
                ("custodian", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="petty_cash_accounts", to="employee.employee", verbose_name="Cash custodian")),
                ("modified_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified_by", to=settings.AUTH_USER_MODEL, verbose_name="Modified By")),
            ],
            options={"verbose_name": "Petty cash float", "verbose_name_plural": "Petty cash floats", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="PettyCashEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True, verbose_name="Created At")),
                ("is_active", models.BooleanField(default=True, verbose_name="Is Active")),
                ("transaction_date", models.DateField(verbose_name="Transaction date")),
                ("entry_type", models.CharField(choices=[("top_up", "Cash top-up"), ("expense", "Expense"), ("adjustment", "Adjustment")], default="expense", max_length=20)),
                ("direction", models.CharField(choices=[("in", "Cash in"), ("out", "Cash out")], default="out", max_length=3)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("category", models.CharField(blank=True, max_length=80, verbose_name="Expense category")),
                ("payee", models.CharField(blank=True, max_length=150, verbose_name="Payee / source")),
                ("description", models.TextField(verbose_name="Purpose / description")),
                ("reference", models.CharField(blank=True, max_length=80, verbose_name="Receipt or reference number")),
                ("receipt", models.FileField(blank=True, null=True, upload_to=horilla.models.upload_path, verbose_name="Receipt attachment")),
                ("status", models.CharField(choices=[("posted", "Posted"), ("void", "Void")], default="posted", max_length=12)),
                ("void_reason", models.CharField(blank=True, max_length=250, verbose_name="Void reason")),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="entries", to="petty_cash.pettycashaccount", verbose_name="Cash float")),
                ("company_id", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="base.company", verbose_name="Company")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name="Created By")),
                ("modified_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified_by", to=settings.AUTH_USER_MODEL, verbose_name="Modified By")),
                ("voided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="voided_petty_cash_entries", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Petty cash entry", "verbose_name_plural": "Petty cash entries", "ordering": ["-transaction_date", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="pettycashaccount",
            constraint=models.UniqueConstraint(fields=("company_id", "name"), name="unique_petty_cash_float_name"),
        ),
    ]

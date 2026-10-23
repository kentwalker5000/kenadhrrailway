"""Run data repair after schema changes commit, avoiding pending FK events."""
from importlib import import_module

from django.db import migrations

repair_templates = import_module(
    "payroll.migrations.0010_payroll_policy_and_history"
).repair_templates


class Migration(migrations.Migration):
    dependencies = [("payroll", "0011_lock_finalised_payslips")]
    operations = [migrations.RunPython(repair_templates, migrations.RunPython.noop)]

"""Protect financial history even through bulk updates and generic delete views."""
from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE FUNCTION payroll_guard_finalised() RETURNS trigger AS $$
        BEGIN
          IF OLD.status IN ('confirmed', 'paid') THEN
            IF TG_OP = 'DELETE' THEN
              RAISE EXCEPTION 'Confirmed or paid payslips cannot be deleted' USING ERRCODE = '23514';
            END IF;
            IF (OLD.status = 'paid' AND NEW.status IS DISTINCT FROM 'paid')
               OR NEW.status IS NULL OR NEW.status NOT IN ('confirmed', 'paid')
               OR ROW(OLD.employee_id_id, OLD.start_date, OLD.end_date, OLD.contract_wage,
                      OLD.basic_pay, OLD.gross_pay, OLD.deduction, OLD.net_pay, OLD.pay_head_data)
                  IS DISTINCT FROM
                  ROW(NEW.employee_id_id, NEW.start_date, NEW.end_date, NEW.contract_wage,
                      NEW.basic_pay, NEW.gross_pay, NEW.deduction, NEW.net_pay, NEW.pay_head_data)
            THEN
              RAISE EXCEPTION 'Confirmed or paid payslip financial history is locked' USING ERRCODE = '23514';
            END IF;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER payroll_finalised_guard BEFORE UPDATE OR DELETE ON payroll_payslip
        FOR EACH ROW EXECUTE FUNCTION payroll_guard_finalised();
    """)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP TRIGGER IF EXISTS payroll_finalised_guard ON payroll_payslip;")
        schema_editor.execute("DROP FUNCTION IF EXISTS payroll_guard_finalised();")


class Migration(migrations.Migration):
    dependencies = [("payroll", "0010_payroll_policy_and_history")]
    operations = [migrations.RunPython(install, uninstall)]

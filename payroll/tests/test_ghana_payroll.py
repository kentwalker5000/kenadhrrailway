"""Regression tests for the Ghana statutory payroll template."""

from datetime import date
import calendar
import json

from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.apps import apps
from importlib import import_module

from horilla.testkit import CompanyFilterTestMixin, make_company, make_employee, make_user
from horilla.horilla_middlewares import _thread_locals
from payroll.ghana import (
    GHANA_PAYE_BRACKETS_2026,
    GHANA_SSNIT_MONTHLY_EMPLOYEE_CAP,
    GHANA_SSNIT_MONTHLY_EMPLOYER_CAP,
    configure_ghana_payroll,
)
from payroll.methods.tax_calc import (
    annualise_income,
    calculate_taxable_amount,
    period_tax_from_yearly,
)
from payroll.methods.methods import calculate_employer_contribution
from payroll.models.models import Contract, Deduction, Payslip
from payroll.models.tax_models import TaxBracket
from payroll.methods.methods import save_payslip
from payroll.methods.policy import resolve_filing
from payroll.views.component_views import payroll_calculation


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class GhanaPayrollConfigurationTests(CompanyFilterTestMixin, TestCase):
    def setUp(self):
        self.clear_company_context()
        _thread_locals.request = None
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.company = make_company("Ghana Payroll Co")
        self.employee = make_employee(
            company=self.company, email="ghana-payroll@test.horilla",
            user=make_user("ghana-payroll-test"),
        )

    def test_configuration_is_repeatable_and_uses_2026_rules(self):
        first = configure_ghana_payroll(self.company)
        second = configure_ghana_payroll(self.company)

        self.assertEqual(first["settings"].currency_symbol, "GHS")
        self.assertEqual(first["filing_status"].pk, second["filing_status"].pk)
        self.assertEqual(len(first["brackets"]), len(GHANA_PAYE_BRACKETS_2026))
        self.assertEqual(first["ssnit"].rate, 5.5)
        self.assertEqual(first["ssnit"].employer_rate, 13.0)
        self.assertEqual(
            first["ssnit"].maximum_amount,
            GHANA_SSNIT_MONTHLY_EMPLOYEE_CAP,
        )
        self.assertEqual(
            first["ssnit"].employer_maximum_amount,
            GHANA_SSNIT_MONTHLY_EMPLOYER_CAP,
        )
        self.assertFalse(first["national_service_structure"].deductions.exists())
        no_paye_bracket = first["national_service_filing_status"].taxbracket_set.get()
        self.assertEqual(no_paye_bracket.tax_rate, 0)

    def test_monthly_resident_paye_uses_twelve_payrolls_not_calendar_days(self):
        config = configure_ghana_payroll(self.company)
        config["ssnit"].specific_employees.add(self.employee)
        contract = Contract._base_manager.get(employee_id=self.employee)
        contract.filing_status = config["filing_status"]
        contract.contract_start_date = date(2026, 1, 1)
        contract.wage = 10000
        contract.pay_frequency = "monthly"
        contract.contract_status = "active"
        contract.save()

        tax = calculate_taxable_amount(
            employee=self.employee,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
            basic_pay=10000,
            allowances={"allowances": []},
            total_allowance=0,
            day_dict=[],
        )

        # Employee contribution is 550, taxable pay is 9450.
        self.assertEqual(tax, 1967)

    def test_annualisation_uses_contract_frequency(self):
        self.assertEqual(annualise_income(1000, "monthly", 28, 365), 12000)
        self.assertEqual(annualise_income(1000, "semi_monthly", 15, 365), 24000)
        self.assertEqual(annualise_income(1000, "weekly", 7, 365), 52000)
        self.assertEqual(period_tax_from_yearly(12000, "monthly", 28, 365), 1000)

    def test_ssnit_employer_contribution_uses_its_own_cap(self):
        config = configure_ghana_payroll(self.company)
        data = {
            "pay_data": {
                "basic_pay": 100000,
                "start_date": "2026-10-01",
                "end_date": "2026-10-31",
                "pretax_deductions": [
                    {
                        "deduction_id": config["ssnit"].id,
                        "amount": GHANA_SSNIT_MONTHLY_EMPLOYEE_CAP,
                        "employer_contribution_rate": 13,
                    }
                ],
                "post_tax_deductions": [],
                "tax_deductions": [],
                "net_deductions": [],
            }
        }

        calculate_employer_contribution(data)

        self.assertEqual(
            data["pay_data"]["pretax_deductions"][0][
                "employer_contribution_amount"
            ],
            GHANA_SSNIT_MONTHLY_EMPLOYER_CAP,
        )

    def configure_contract(self, national_service=False, wage=6000):
        config = configure_ghana_payroll(self.company)
        contract = Contract._base_manager.get(employee_id=self.employee)
        contract.filing_status = config[
            "national_service_filing_status" if national_service else "filing_status"
        ]
        contract.set_salary_structure(config[
            "national_service_structure" if national_service else "salary_structure"
        ])
        contract.contract_start_date = date(2024, 1, 1)
        contract.contract_status = "active"
        contract.pay_frequency = "monthly"
        contract.wage = wage
        contract.save()
        return config

    def calculate(self, year=2026, month=9):
        days = calendar.monthrange(year, month)[1]
        return payroll_calculation(
            self.employee, date(year, month, 1), date(year, month, days),
            month_summary={"present": days, "pay_period_days": days},
        )

    def save_calculated(self, result, status="draft"):
        data = dict(
            employee=self.employee, start_date=result["start_date"],
            end_date=result["end_date"], status=status,
            contract_wage=result["contract_wage"], basic_pay=result["basic_pay"],
            gross_pay=result["gross_pay"], deduction=result["total_deductions"],
            net_pay=result["net_pay"], pay_data=json.loads(result["json_data"]),
            installments=result["installments"],
        )
        calculate_employer_contribution(data)
        return save_payslip(**data)

    def test_full_month_payslip_and_employer_cost(self):
        self.configure_contract()
        result = self.calculate()
        self.assertEqual(result["pretax_deductions"][0]["amount"], 330)
        self.assertEqual(result["federal_tax"], 1022)
        self.assertEqual(result["net_pay"], 4648)
        slip = self.save_calculated(result)
        self.assertEqual(slip.net_pay, 4648)
        self.assertEqual(slip.pay_head_data["pretax_deductions"][0]["employer_contribution_amount"], 780)

    def test_historical_tax_version_is_selected_by_payroll_date(self):
        self.configure_contract()
        self.assertEqual(self.calculate(month=8)["federal_tax"], 1016)
        self.assertEqual(self.calculate(month=9)["federal_tax"], 1022)

    def test_ceiling_is_monthly_and_selected_by_year(self):
        self.configure_contract(wage=100000)
        for year, expected in [(2024, 2860), (2025, 3355), (2026, 3795)]:
            with self.subTest(year=year):
                result = self.calculate(year=year)
                self.assertEqual(result["pretax_deductions"][0]["amount"], expected)

    def test_unknown_year_fails_instead_of_using_stale_rules(self):
        self.configure_contract()
        with self.assertRaises(ValidationError):
            self.calculate(year=2027)

    def test_period_crossing_tax_change_is_rejected(self):
        config = self.configure_contract()
        with self.assertRaises(ValidationError):
            resolve_filing(config["filing_status"], date(2026, 8, 1), date(2026, 9, 30))

    def test_adjacent_brackets_are_valid_but_overlaps_are_rejected(self):
        config = self.configure_contract()
        for bracket in config["brackets"]:
            bracket.clean()
        with self.assertRaises(ValidationError):
            TaxBracket(filing_status_id=config["filing_status"], min_income=1,
                       max_income=100, tax_rate=5).clean()

    def test_invalid_tax_date_range_and_version_cycle_are_rejected(self):
        filing = self.configure_contract()["filing_status"]
        filing.clean()
        filing.effective_to = date(2020, 1, 1)
        with self.assertRaises(ValidationError):
            filing.clean()
        filing.refresh_from_db()
        filing.previous_version = filing
        with self.assertRaises(ValidationError):
            filing.clean()

    def test_exemption_also_works_with_structure_only(self):
        config = self.configure_contract(national_service=True)
        contract = Contract._base_manager.get(employee_id=self.employee)
        contract.filing_status = config["filing_status"]
        contract.save()
        config["ssnit"].include_active_employees = True
        config["ssnit"].save()
        self.assertEqual(self.calculate()["net_pay"], 6000)

    def test_normal_employee_still_receives_global_deductions(self):
        self.configure_contract()
        Deduction.objects.create(title="Global after-tax", company_id=self.company,
                                 is_pretax=False, is_fixed=True, amount=100,
                                 include_active_employees=True)
        self.assertEqual(self.calculate()["net_pay"], 4548)

    def test_national_service_excludes_global_and_assigned_deductions(self):
        config = self.configure_contract(national_service=True)
        for extra in [
            {"is_pretax": True}, {"is_pretax": False}, {"is_tax": True},
            {"update_compensation": "basic_pay"},
            {"update_compensation": "gross_pay"},
            {"update_compensation": "net_pay"},
            {"is_fixed": False, "based_on": "net_pay", "rate": 10},
            {"is_installment": True, "one_time_date": date(2026, 9, 15)},
        ]:
            values = dict(title="Global deduction", company_id=self.company,
                          is_fixed=True, amount=100, include_active_employees=True)
            values.update(extra)
            deduction = Deduction.objects.create(**values)
            deduction.specific_employees.add(self.employee)
            config["national_service_structure"].deductions.add(deduction)
        result = self.calculate()
        self.assertEqual(result["net_pay"], 6000)
        self.assertEqual(result["federal_tax"], 0)
        self.assertEqual(result["total_deductions"], 0)
        self.assertFalse(result["installments"].exists())
        for key in ["pretax_deductions", "post_tax_deductions", "tax_deductions",
                    "net_deductions", "basic_pay_deductions", "gross_pay_deductions"]:
            self.assertEqual(result[key], [])

    def test_draft_can_regenerate_but_finalised_payslip_cannot(self):
        self.configure_contract()
        result = self.calculate()
        slip = self.save_calculated(result)
        self.assertEqual(self.save_calculated(result).pk, slip.pk)
        slip.status = "confirmed"
        slip.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            self.save_calculated(result)
        slip.status = "paid"
        slip.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            self.save_calculated(result)
        slip.refresh_from_db()
        self.assertEqual(slip.net_pay, 4648)
        self.assertEqual(slip.status, "paid")

    def test_finalised_model_edits_reopening_and_delete_are_blocked(self):
        self.configure_contract()
        slip = self.save_calculated(self.calculate(), status="paid")
        slip.net_pay = 1
        with self.assertRaises(ValidationError):
            slip.save()
        slip.refresh_from_db()
        slip.status = "draft"
        with self.assertRaises(ValidationError):
            slip.save(update_fields=["status"])
        with self.assertRaises(ProtectedError):
            Payslip.objects.filter(pk=slip.pk).delete()

    def test_database_blocks_bulk_financial_edits_and_reopening(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL trigger protection")
        self.configure_contract()
        slip = self.save_calculated(self.calculate(), status="paid")
        for changes in [{"net_pay": 1}, {"status": "draft"}, {"pay_head_data": {}}]:
            with self.subTest(changes=changes), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Payslip.objects.filter(pk=slip.pk).update(**changes)

    def test_bulk_status_changes_require_permission(self):
        self.configure_contract()
        slip = self.save_calculated(self.calculate())
        self.client.force_login(self.employee.employee_user_id)
        self.client.post(reverse("payslip-status-update-no-id"),
                         {"ids": json.dumps([slip.pk]), "status": "paid"},
                         HTTP_HX_REQUEST="true")
        slip.refresh_from_db()
        self.assertEqual(slip.status, "draft")

    def test_status_views_reject_reopening_without_server_error(self):
        self.configure_contract()
        slip = self.save_calculated(self.calculate(), status="paid")
        user = self.employee.employee_user_id
        user.is_superuser = True
        user.save()
        self.client.force_login(user)
        for url, data in [
            (reverse("payslip-status-update", args=[slip.pk]), {"status": "draft"}),
            (reverse("payslip-status-update-no-id"), {"ids": json.dumps([slip.pk]), "status": "draft"}),
        ]:
            with self.subTest(url=url):
                response = self.client.post(url, data, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 409)
        slip.refresh_from_db()
        self.assertEqual(slip.status, "paid")

    def test_new_tax_version_form_keeps_company_scope(self):
        from payroll.forms.tax_forms import FilingStatusForm
        config = self.configure_contract()
        self.set_company_context(self.company.pk)
        form = FilingStatusForm(data={
            "filing_status": "Next reviewed tax version", "based_on": "taxable_gross_pay",
            "payroll_policy": "ghana_resident", "effective_from": "2027-01-01",
            "effective_to": "2027-12-31", "previous_version": config["filing_status"].pk,
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.instance.company_id_id, self.company.pk)

    def test_data_repair_corrects_known_caps_without_rewriting_payslips(self):
        config = self.configure_contract()
        slip = self.save_calculated(self.calculate(), status="paid")
        original_data = slip.pay_head_data
        deduction = config["ssnit"]
        deduction.maximum_amount = 316.25
        deduction.employer_maximum_amount = 747.5
        deduction.save()
        repair = import_module("payroll.migrations.0010_payroll_policy_and_history").repair_templates
        repair(apps, None)
        deduction.refresh_from_db()
        slip.refresh_from_db()
        self.assertEqual(deduction.maximum_amount, 3795)
        self.assertEqual(deduction.employer_maximum_amount, 8970)
        self.assertEqual(slip.pay_head_data, original_data)
        self.assertEqual(slip.status, "paid")

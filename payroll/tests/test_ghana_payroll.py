"""Regression tests for the Ghana statutory payroll template."""

from datetime import date

from django.test import TestCase

from horilla.testkit import make_company, make_employee
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
from payroll.models.models import Contract


class GhanaPayrollConfigurationTests(TestCase):
    def setUp(self):
        self.company = make_company("Ghana Payroll Co")
        self.employee = make_employee(
            company=self.company, email="ghana-payroll@test.horilla"
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

        # The employee SSNIT amount is capped at GH¢316.25, so taxable income
        # is 9,683.75. Annual PAYE on 116,205 is 24,305.25, or GH¢2,025.4375.
        self.assertEqual(tax, 2025.4375)

    def test_annualisation_uses_contract_frequency(self):
        self.assertEqual(annualise_income(1000, "monthly", 28, 365), 12000)
        self.assertEqual(annualise_income(1000, "semi_monthly", 15, 365), 24000)
        self.assertEqual(annualise_income(1000, "weekly", 7, 365), 52000)
        self.assertEqual(period_tax_from_yearly(12000, "monthly", 28, 365), 1000)

    def test_ssnit_employer_contribution_uses_its_own_cap(self):
        config = configure_ghana_payroll(self.company)
        data = {
            "pay_data": {
                "basic_pay": 10000,
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

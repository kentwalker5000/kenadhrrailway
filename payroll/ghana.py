"""Ghana statutory payroll configuration for the generic payroll engine.

The values below implement the resident PAYE rates published by the Ghana
Revenue Authority, effective 1 September 2026, and the 2026 SSNIT rates and
maximum insurable earnings.  Keep this module versioned: a statutory change
should be introduced as a new configuration, not by rewriting old payslips.
"""

import math
from datetime import date

from django.db import transaction

from payroll.models.models import Deduction, FilingStatus, SalaryStructure
from payroll.models.tax_models import PayrollSettings, TaxBracket


GHANA_PAYE_NAME = "Ghana PAYE (Resident, 2026)"
GHANA_STRUCTURE_NAME = "Ghana Statutory Payroll (2026)"
GHANA_NATIONAL_SERVICE_STRUCTURE_NAME = "National Service — No Deductions"
GHANA_NATIONAL_SERVICE_FILING_STATUS_NAME = "National Service — No PAYE"
GHANA_SSNIT_NAME = "SSNIT (Employee 5.5%; Employer 13%)"

# Annual Ghana resident PAYE bands effective from 1 September 2026.
# Each tuple is (lower bound, upper bound, marginal rate as a percentage).
GHANA_PAYE_BRACKETS_2026 = (
    (0.00, 7056.00, 0.00),
    (7056.00, 8016.00, 5.00),
    (8016.00, 9216.00, 10.00),
    (9216.00, 44016.00, 17.50),
    (44016.00, 236016.00, 25.00),
    (236016.00, 600000.00, 30.00),
    (600000.00, math.inf, 35.00),
)

# SSNIT's 2026 maximum insurable earning is GH¢69,000 PER MONTH.
GHANA_SSNIT_EMPLOYEE_RATE = 5.50
GHANA_SSNIT_EMPLOYER_RATE = 13.00
GHANA_SSNIT_MONTHLY_EMPLOYEE_CAP = 3795.00
GHANA_SSNIT_MONTHLY_EMPLOYER_CAP = 8970.00

GHANA_PAYE_BRACKETS_2024 = (
    (0, 5880, 0), (5880, 7200, 5), (7200, 8760, 10),
    (8760, 46760, 17.5), (46760, 238760, 25),
    (238760, 600000, 30), (600000, math.inf, 35),
)


@transaction.atomic
def configure_ghana_payroll(company):
    """Create or update Ghana's standard resident payroll configuration.

    This intentionally does not assign the salary structure or filing status
    to contracts.  HR must first confirm each employee's residency, salary,
    allowances, reliefs, and Tier-2 trustee details.
    """

    settings, _ = PayrollSettings._base_manager.update_or_create(
        company_id=company,
        defaults={"currency_symbol": "GHS", "position": "postfix"},
    )
    previous, _ = FilingStatus._base_manager.update_or_create(
        company_id=company, filing_status="Ghana PAYE (2024-Aug 2026)",
        defaults={"based_on": "taxable_gross_pay", "use_py": False,
                  "payroll_policy": "ghana_resident",
                  "effective_from": date(2024, 1, 1), "effective_to": date(2026, 8, 31)},
    )
    for lower, upper, rate in GHANA_PAYE_BRACKETS_2024:
        TaxBracket.objects.update_or_create(
            filing_status_id=previous, min_income=lower,
            defaults={"max_income": upper, "tax_rate": rate},
        )
    filing_status, _ = FilingStatus._base_manager.update_or_create(
        company_id=company,
        filing_status=GHANA_PAYE_NAME,
        defaults={
            "based_on": "taxable_gross_pay",
            "use_py": False,
            "python_code": None,
            "payroll_policy": "ghana_resident",
            "effective_from": date(2026, 9, 1),
            "effective_to": date(2026, 12, 31),
            "previous_version": previous,
            "description": (
                "Resident individual PAYE bands effective 1 September 2026."
            ),
        },
    )

    brackets = []
    for min_income, max_income, tax_rate in GHANA_PAYE_BRACKETS_2026:
        bracket, _ = TaxBracket.objects.update_or_create(
            filing_status_id=filing_status,
            min_income=min_income,
            defaults={"max_income": max_income, "tax_rate": tax_rate},
        )
        brackets.append(bracket)

    ssnit, _ = Deduction._base_manager.update_or_create(
        company_id=company,
        title=GHANA_SSNIT_NAME,
        defaults={
            "is_tax": False,
            "is_pretax": True,
            "is_fixed": False,
            "amount": None,
            "based_on": "basic_pay",
            "rate": GHANA_SSNIT_EMPLOYEE_RATE,
            "employer_rate": GHANA_SSNIT_EMPLOYER_RATE,
            "employer_maximum_amount": GHANA_SSNIT_MONTHLY_EMPLOYER_CAP,
            "has_max_limit": True,
            "maximum_amount": GHANA_SSNIT_MONTHLY_EMPLOYEE_CAP,
            "include_active_employees": False,
            "statutory_code": "ghana_pension",
        },
    )
    structure, _ = SalaryStructure._base_manager.update_or_create(
        company_id=company,
        title=GHANA_STRUCTURE_NAME,
    )
    structure.deductions.add(ssnit)
    national_service_structure, _ = SalaryStructure._base_manager.update_or_create(
        company_id=company,
        title=GHANA_NATIONAL_SERVICE_STRUCTURE_NAME,
        defaults={"deductions_exempt": True},
    )
    national_service_filing_status, _ = FilingStatus._base_manager.update_or_create(
        company_id=company,
        filing_status=GHANA_NATIONAL_SERVICE_FILING_STATUS_NAME,
        defaults={
            "based_on": "basic_pay",
            "use_py": False,
            "python_code": None,
            "description": "Organisation-approved National Service no-PAYE policy.",
            "payroll_policy": "national_service",
        },
    )
    TaxBracket.objects.update_or_create(
        filing_status_id=national_service_filing_status,
        min_income=0,
        defaults={"max_income": math.inf, "tax_rate": 0},
    )

    return {
        "settings": settings,
        "filing_status": filing_status,
        "brackets": brackets,
        "ssnit": ssnit,
        "salary_structure": structure,
        "national_service_structure": national_service_structure,
        "national_service_filing_status": national_service_filing_status,
    }

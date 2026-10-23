"""Shared payroll policy gates; independent of editable display names."""

from django.core.exceptions import ValidationError
from django.db.models import Q

from payroll.models.models import Contract


def deductions_exempt(employee):
    return Contract._base_manager.filter(
        employee_id=employee, contract_status="active",
    ).filter(
        Q(salary_structure_id__deductions_exempt=True)
        | Q(filing_status__payroll_policy="national_service")
    ).exists()


def resolve_filing(filing, start, end):
    """Resolve the version covering the entire period; never silently use a newer law."""
    seen = set()
    company_id = filing.company_id_id
    while filing:
        if filing.pk in seen or filing.company_id_id != company_id:
            raise ValidationError("Invalid payroll tax version chain.")
        seen.add(filing.pk)
        if (not filing.effective_from or start >= filing.effective_from) and (
            not filing.effective_to or end <= filing.effective_to
        ):
            return filing
        filing = filing.previous_version
    raise ValidationError("No tax rules cover this period. Split periods at a tax-rule change or configure historical rates.")


def pension_ceiling(start, end):
    # Monthly limits: SSNIT public notices for 2024, 2025 and 2026.
    ceilings = {2024: 52000, 2025: 61000, 2026: 69000}
    if (start.year, start.month) != (end.year, end.month) or end < start:
        raise ValidationError("Ghana payroll must be calculated one calendar month at a time.")
    if start.year not in ceilings:
        raise ValidationError("Configure SSNIT limits for this payroll year before calculating payroll.")
    return ceilings[start.year]

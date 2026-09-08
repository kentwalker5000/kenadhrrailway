"""Shared workforce composition metrics for employee-facing dashboards."""

from django.db.models import Count


EMPLOYEE_TYPE_ALIASES = {
    "contractual": {"contract", "contractual", "contractor", "contractors"},
    "internships": {"intern", "interns", "internship", "internships"},
    "national_service": {"national service", "nss"},
}


def employee_type_category(label):
    """Map a free-text employee type to a workforce dashboard category."""
    normalized = " ".join(
        str(label or "").casefold().replace("-", " ").replace("_", " ").split()
    )
    for suffix in (
        " employees",
        " employee",
        " personnel",
        " members",
        " member",
        " workers",
        " worker",
        " staff",
    ):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()
            break

    # Keep National Service first so unusual labels stay mutually exclusive.
    for category in ("national_service", "contractual", "internships"):
        if normalized in EMPLOYEE_TYPE_ALIASES[category]:
            return category
    return None


def workforce_summary():
    """Return active headcount and priority employee-type composition."""
    from employee.models import Employee, EmployeeWorkInformation

    rows = (
        EmployeeWorkInformation.objects.filter(
            employee_id__is_active=True,
            employee_type_id__isnull=False,
        )
        .values("employee_type_id", "employee_type_id__employee_type")
        .annotate(count=Count("employee_id", distinct=True))
    )

    counts = {category: 0 for category in EMPLOYEE_TYPE_ALIASES}
    type_ids = {category: [] for category in EMPLOYEE_TYPE_ALIASES}
    for row in rows:
        category = employee_type_category(row["employee_type_id__employee_type"])
        if category:
            counts[category] += row["count"]
            type_ids[category].append(row["employee_type_id"])

    return {
        "headcount": Employee.objects.filter(is_active=True).count(),
        "contractual": counts["contractual"],
        "internships": counts["internships"],
        "national_service": counts["national_service"],
        "employee_type_ids": type_ids,
    }


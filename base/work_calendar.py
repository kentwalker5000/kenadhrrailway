"""Employee calendars shared by attendance summaries and payroll.

Roster entries override weekly-off rules for their date only. Holidays retain
priority. Draft/published roster treatment is unchanged: both are HR inputs.
"""

from datetime import timedelta

from django.db.models import Q

from base.methods import get_company_leave_dates
from base.models import CompanyLeaves, Holidays, Roster
from employee.models import EmployeeWorkInformation


def employee_work_calendars(employees, start_date, end_date):
    """Build calendars in batches, including company and assignment scope."""
    employees = list(employees)
    if not employees:
        return {}
    # Signals and bulk work-info updates can leave the Employee instance's
    # reverse-relation cache stale. Read current assignments once for the batch.
    work_info = {
        row["employee_id_id"]: row
        for row in EmployeeWorkInformation.objects.filter(
            employee_id__in=[emp.pk for emp in employees]
        ).values(
            "employee_id_id", "company_id_id", "department_id_id", "job_position_id_id"
        )
    }
    all_dates = {
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    }
    holidays = list(
        Holidays.objects.filter(
            Q(end_date__gte=start_date)
            | Q(end_date__isnull=True, start_date__gte=start_date),
            start_date__lte=end_date,
        ).prefetch_related("employees", "department", "job_position")
    )
    holiday_rules = []
    for holiday in holidays:
        first = max(start_date, holiday.start_date)
        last = min(end_date, holiday.end_date or holiday.start_date)
        holiday_rules.append(
            (
                holiday,
                {first + timedelta(days=i) for i in range((last - first).days + 1)},
                {emp.pk for emp in holiday.employees.all()},
                {dept.pk for dept in holiday.department.all()},
                {position.pk for position in holiday.job_position.all()},
            )
        )
    weekly_rules = [
        (rule, {company.pk for company in rule.company_id.all()})
        for rule in CompanyLeaves.objects.prefetch_related("company_id")
    ]
    roster_by_employee = {}
    for entry in Roster.objects.filter(
        employee_id__in=[emp.pk for emp in employees],
        date__range=(start_date, end_date),
    ).values("employee_id", "date", "is_off"):
        roster_by_employee.setdefault(entry["employee_id"], {})[entry["date"]] = entry[
            "is_off"
        ]

    company_week_offs = {}
    result = {}
    for employee in employees:
        info = work_info.get(employee.pk, {})
        company_id = info.get("company_id_id")
        if company_id not in company_week_offs:
            rules = [
                rule
                for rule, companies in weekly_rules
                if not companies or company_id in companies
            ]
            company_week_offs[company_id] = {
                day
                for year in range(start_date.year, end_date.year + 1)
                for day in get_company_leave_dates(year, company_leaves=rules)
                if day in all_dates
            }
        week_off = set(company_week_offs[company_id])
        for day, is_off in roster_by_employee.get(employee.pk, {}).items():
            if is_off:
                week_off.add(day)
            else:
                week_off.discard(day)
        holiday_dates = {}
        holiday_ids = set()
        for holiday, dates, assigned, departments, positions in holiday_rules:
            if (
                holiday.company_id_id is not None
                and holiday.company_id_id != company_id
            ):
                continue
            if not holiday.is_specific:
                applies = True
            elif holiday.assigning_type == "department":
                applies = info.get("department_id_id") in departments
            elif holiday.assigning_type == "job_position":
                applies = info.get("job_position_id_id") in positions
            else:
                applies = employee.pk in assigned
            if applies:
                holiday_dates.update({day: holiday.name for day in dates})
                holiday_ids.add(holiday.pk)
        result[employee.pk] = {
            "holidays": holiday_dates,
            "holiday_ids": holiday_ids,
            "week_off": week_off - holiday_dates.keys(),
            "working_dates": all_dates - holiday_dates.keys() - week_off,
        }
    return result


def employee_work_calendar(employee, start_date, end_date):
    return employee_work_calendars([employee], start_date, end_date)[employee.pk]

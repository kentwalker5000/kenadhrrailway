"""Quarter opening and guarded review submission shared by GET and POST."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from employee.models import Employee
from pms.models import Answer, Feedback, Period


@transaction.atomic
def open_period(period, company, template):
    period = Period.objects.select_for_update().get(pk=period.pk)
    if period.start_date > period.end_date or period.end_date < timezone.localdate():
        raise ValidationError("Choose a current or upcoming review period with valid dates.")
    if not template.question.exists():
        raise ValidationError("Add questions to the question template before opening reviews.")
    if period.company_id.exists() and not period.company_id.filter(pk=company.pk).exists():
        raise ValidationError("This company is not assigned to the review period.")
    if template.company_id.exists() and not template.company_id.filter(pk=company.pk).exists():
        raise ValidationError("The question template belongs to another company.")
    employees = list(Employee.objects.filter(is_active=True, employee_work_info__company_id=company).select_related("employee_work_info"))
    if not employees:
        raise ValidationError("No active employees are assigned to this company.")
    employee_ids = {employee.pk for employee in employees}
    created_count = 0
    for employee in employees:
        manager_id = employee.employee_work_info.reporting_manager_id_id
        if manager_id not in employee_ids or manager_id == employee.pk:
            manager_id = None
        feedback, created = Feedback.objects.get_or_create(
            period=period, employee_id=employee,
            defaults={"review_cycle": period.period_name[:100], "manager_id_id": manager_id,
                      "question_template_id": template, "start_date": period.start_date,
                      "end_date": period.end_date},
        )
        if created:
            feedback.subordinate_id.set([
                staff for staff in employees
                if staff.pk != employee.pk and staff.employee_work_info.reporting_manager_id_id == employee.pk
            ])
            created_count += 1
    period.company_id.add(company)
    period.is_open = True
    period.save(update_fields=["is_open"])
    return created_count


def review_access_error(feedback, employee):
    today = timezone.localdate()
    if employee is None or employee not in feedback.requested_employees():
        return "You are not assigned to review this employee."
    if feedback.archive or feedback.status == "Closed":
        return "This review is closed."
    if feedback.period_id and not feedback.period.is_open:
        return "HR has not opened this review period, or has closed it."
    start = feedback.period.start_date if feedback.period_id else feedback.start_date
    end = feedback.period.end_date if feedback.period_id else feedback.end_date
    if start > today or (end and end < today):
        return "Reviews can only be submitted during the review period."
    if Answer.objects.filter(feedback_id=feedback, employee_id=employee).exists():
        return "You have already submitted this review."
    return None


def validate_answers(questions, data):
    result = []
    for question in questions:
        value = str(data.get(f"answer{question.pk}", "")).strip()
        allowed = None
        if question.question_type == "2":
            allowed = {"1", "2", "3", "4", "5"}
        elif question.question_type == "3":
            allowed = {"yes", "no"}
        elif question.question_type == "5":
            allowed = {"Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"}
        elif question.question_type == "4":
            allowed = {option for row in question.question_options.all() for option in (row.option_a, row.option_b, row.option_c, row.option_d) if option}
        if not value or (allowed is not None and value not in allowed):
            raise ValidationError("Answer every question using one of its available options.")
        result.append((question, value))
    if not result:
        raise ValidationError("This review has no questions yet.")
    return result

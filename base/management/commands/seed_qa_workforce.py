"""Seed a clearly labelled, disposable workforce for local app testing."""

import calendar
import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from base.models import Company, Department, JobPosition
from employee.models import Employee, EmployeeBankDetails, EmployeeWorkInformation
from payroll.ghana import configure_ghana_payroll
from payroll.methods.methods import calculate_employer_contribution, save_payslip
from payroll.models.models import Contract
from payroll.views.component_views import payroll_calculation


PEOPLE = (
    ("Ama", "Mensah", "HR Officer", 4800),
    ("Kwame", "Asante", "Finance Officer", 6200),
    ("Akosua", "Owusu", "Program Officer", 5400),
    ("Kofi", "Boateng", "IT Officer", 7500),
    ("Adwoa", "Addo", "Communications Officer", 5800),
    ("Yaw", "Appiah", "Operations Officer", 6600),
    ("Esi", "Agyeman", "Research Officer", 6000),
    ("Kojo", "Darko", "Accounts Assistant", 4200),
    ("Afia", "Ofori", "Executive Assistant", 5200),
    ("Nana", "Bediako", "Projects Coordinator", 7200),
    ("Abena", "Frimpong", "Monitoring Officer", 5600),
    ("Emmanuel", "Osei", "Field Officer", 4600),
    ("Mabel", "Kwarteng", "Procurement Officer", 6800),
    ("Samuel", "Tetteh", "Administrative Officer", 5000),
    ("Patience", "Gyamfi", "Legal Officer", 8500),
    ("Isaac", "Nartey", "Data Analyst", 7800),
    ("Linda", "Amoako", "Membership Officer", 5300),
    ("Michael", "Sarpong", "Facilities Officer", 4500),
    ("Gladys", "Obeng", "Training Officer", 6400),
    ("Daniel", "Adu", "Chief Operations Officer", 12000),
    ("Ruth", "Quartey", "Graduate Intern", 2200),
    ("Felix", "Ofori", "Graduate Intern", 2200),
    ("Mercy", "Arthur", "National Service Personnel", 1800),
    ("Joseph", "Kusi", "National Service Personnel", 1800),
    ("Evelyn", "Baah", "National Service Personnel", 1800),
    ("Richard", "Amankwah", "Fixed-Term Project Officer", 5200),
    ("Janet", "Tawiah", "Fixed-Term Finance Officer", 5800),
    ("Peter", "Koranteng", "Fixed-Term IT Support Officer", 5000),
    ("Grace", "Nyarko", "Communications Intern", 2400),
    ("Victor", "Mensimah", "Programme Intern", 2400),
)


class Command(BaseCommand):
    help = (
        "Create or refresh 20 clearly marked QA employees, bank records, "
        "contracts, Ghana statutory payroll and draft payslips."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company-id",
            type=int,
            required=True,
            help="Company that will own the local QA data.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        company = Company.objects.filter(pk=options["company_id"]).first()
        if company is None:
            raise CommandError(f"Company {options['company_id']} does not exist.")

        department, _ = Department._base_manager.get_or_create(
            department="QA Operations (TEST DATA)"
        )
        department.company_id.add(company)
        payroll = configure_ghana_payroll(company)
        # A completed period makes the payslips valid under the model's
        # no-future-dates rule and keeps the figures stable during testing.
        period_start = date(2026, 9, 1)
        period_end = date(2026, 9, 30)
        days = calendar.monthrange(period_start.year, period_start.month)[1]

        created = 0
        positions = {}
        for number, (first_name, last_name, role, salary) in enumerate(PEOPLE, 1):
            employee, was_created = self._employee(number, first_name, last_name)
            created += int(was_created)
            position = positions.get(role)
            if position is None:
                position, _ = JobPosition._base_manager.get_or_create(
                    job_position=f"QA {role}", department_id=department
                )
                position.company_id.add(company)
                positions[role] = position

            EmployeeWorkInformation._base_manager.update_or_create(
                employee_id=employee,
                defaults={
                    "company_id": company,
                    "department_id": department,
                    "job_position_id": position,
                    "email": employee.email,
                    "mobile": employee.phone,
                    "date_joining": date(2024, (number % 12) + 1, min(number, 28)),
                    "basic_salary": salary,
                    "location": "Accra - QA test record",
                },
            )
            EmployeeBankDetails._base_manager.update_or_create(
                employee_id=employee,
                defaults={
                    "bank_name": "QA Test Bank (not real)",
                    "account_number": f"QA-ACCOUNT-{number:03d}",
                    "branch": "Accra QA Branch",
                    "address": "Test data only - do not use for payments",
                    "country": "Ghana",
                    "state": "Greater Accra",
                    "city": "Accra",
                    "any_other_code1": f"QA-BANK-{number:03d}",
                },
            )
            self._contract(employee, department, position, salary, payroll)
            self._payslip(employee, period_start, period_end, days)

        self.stdout.write(
            self.style.SUCCESS(
                f"QA workforce ready in {company.company}: {len(PEOPLE)} employees "
                f"({created} new), {len(PEOPLE)} active contracts, and {len(PEOPLE)} draft payslips "
                f"for {period_start:%d %b} - {period_end:%d %b %Y}."
            )
        )

    def _employee(self, number, first_name, last_name):
        email = f"qa.employee.{number:02d}@kenadhr.test"
        employee = Employee._base_manager.filter(email=email).first()
        created = employee is None
        if employee is None:
            employee = Employee(
                badge_id=f"QA-{number:03d}",
                employee_first_name=first_name,
                employee_last_name=last_name,
                email=email,
                phone=f"024555{number:04d}",
                address="QA test record - not a real address",
                country="Ghana",
                state="Greater Accra",
                city="Accra",
                zip="QA-0000",
                gender="female" if number % 2 else "male",
                marital_status="single",
                qualification="QA test record",
                experience=2 + (number % 8),
                is_active=True,
                additional_info={"qa_test_data": True, "remove_before_launch": True},
            )
        else:
            employee.badge_id = f"QA-{number:03d}"
            employee.is_active = True
            employee.additional_info = {"qa_test_data": True, "remove_before_launch": True}
        employee.save()
        employee.refresh_from_db()
        user = employee.employee_user_id
        if user is not None:
            user.set_unusable_password()
            user.is_active = False
            user.save(update_fields=["password", "is_active"])
        return employee, created

    def _contract(self, employee, department, position, salary, payroll):
        contract = Contract._base_manager.filter(employee_id=employee).order_by("pk").first()
        if contract is None:
            contract = Contract(employee_id=employee)
        contract.contract_name = f"QA TEST - {employee.get_full_name()} Employment Contract"
        contract.contract_start_date = date(2024, 1, 1)
        contract.contract_end_date = None
        contract.wage_type = "monthly"
        contract.pay_frequency = "monthly"
        contract.wage = salary
        contract.filing_status = payroll["filing_status"]
        contract.contract_status = "active"
        contract.department = department
        contract.job_position = position
        contract.deduct_leave_from_basic_pay = True
        contract.calculate_daily_leave_amount = True
        contract.save()
        contract.set_salary_structure(payroll["salary_structure"])

    def _payslip(self, employee, period_start, period_end, days):
        calculation = payroll_calculation(
            employee,
            period_start,
            period_end,
            month_summary={"present": days, "pay_period_days": days},
        )
        if calculation is None:
            raise CommandError(f"Could not calculate payroll for {employee.get_full_name()}.")
        payload = {
            "employee": employee,
            "start_date": calculation["start_date"],
            "end_date": calculation["end_date"],
            "status": "draft",
            "contract_wage": calculation["contract_wage"],
            "basic_pay": calculation["basic_pay"],
            "gross_pay": calculation["gross_pay"],
            "deduction": calculation["total_deductions"],
            "net_pay": calculation["net_pay"],
            "pay_data": json.loads(calculation["json_data"]),
            "installments": calculation["installments"],
            "group_name": "QA TEST DATA - OCT 2026",
        }
        calculate_employer_contribution(payload)
        save_payslip(**payload)

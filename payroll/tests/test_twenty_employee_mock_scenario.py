"""A realistic, disposable 20-person workforce for HR and payroll checks."""

import calendar
import json
from datetime import date

from django.test import TestCase

from base.models import Department, JobPosition
from employee.models import Employee, EmployeeWorkInformation
from horilla.testkit import CompanyFilterTestMixin, make_company, make_employee
from payroll.ghana import configure_ghana_payroll
from payroll.methods.methods import calculate_employer_contribution, save_payslip
from payroll.models.models import Contract, Payslip
from payroll.views.component_views import payroll_calculation


class TwentyEmployeeMockWorkforceTests(CompanyFilterTestMixin, TestCase):
    """Seed and exercise a representative 20-person Ghana payroll cohort.

    ``TestCase`` wraps the scenario in an isolated test database transaction.
    No employee, salary, payslip, or statutory setup leaks into the running
    application database.
    """

    PEOPLE = (
        ("Ama", "Mensah", "HR Officer", 4_800),
        ("Kwame", "Asante", "Finance Officer", 6_200),
        ("Akosua", "Owusu", "Program Officer", 5_400),
        ("Kofi", "Boateng", "IT Officer", 7_500),
        ("Adwoa", "Addo", "Communications Officer", 5_800),
        ("Yaw", "Appiah", "Operations Officer", 6_600),
        ("Esi", "Agyeman", "Research Officer", 6_000),
        ("Kojo", "Darko", "Accounts Assistant", 4_200),
        ("Afia", "Ofori", "Executive Assistant", 5_200),
        ("Nana", "Bediako", "Projects Coordinator", 7_200),
        ("Abena", "Frimpong", "Monitoring Officer", 5_600),
        ("Emmanuel", "Osei", "Field Officer", 4_600),
        ("Mabel", "Kwarteng", "Procurement Officer", 6_800),
        ("Samuel", "Tetteh", "Administrative Officer", 5_000),
        ("Patience", "Gyamfi", "Legal Officer", 8_500),
        ("Isaac", "Nartey", "Data Analyst", 7_800),
        ("Linda", "Amoako", "Membership Officer", 5_300),
        ("Michael", "Sarpong", "Facilities Officer", 4_500),
        ("Gladys", "Obeng", "Training Officer", 6_400),
        ("Daniel", "Adu", "Chief Operations Officer", 12_000),
    )

    def setUp(self):
        self.clear_company_context()
        self.company = make_company(
            "QA Workforce — Ghana",
            country="Ghana",
            city="Accra",
            address="100 QA Avenue, Accra",
        )
        self.department = Department.objects.create(department="QA Operations")
        self.department.company_id.add(self.company)
        self.positions = {}
        self.config = configure_ghana_payroll(self.company)
        self.period_start = date(2026, 10, 1)
        self.period_end = date(2026, 10, 31)

    def position_for(self, title):
        if title not in self.positions:
            position = JobPosition.objects.create(
                job_position=title, department_id=self.department
            )
            position.company_id.add(self.company)
            self.positions[title] = position
        return self.positions[title]

    def make_workforce(self):
        employees = []
        for number, (first_name, last_name, role, salary) in enumerate(self.PEOPLE, 1):
            employee = make_employee(
                company=self.company,
                first_name=first_name,
                last_name=last_name,
                email=f"qa.employee.{number:02d}@example.test",
                phone=f"024555{number:04d}",
                date_joining=date(2024, (number % 12) + 1, min(number, 28)),
            )
            EmployeeWorkInformation._base_manager.filter(employee_id=employee).update(
                department_id=self.department,
                job_position_id=self.position_for(role),
                email=employee.email,
            )
            contract = Contract._base_manager.get(employee_id=employee)
            contract.contract_name = f"{employee.get_full_name()} — QA Employment Contract"
            contract.contract_start_date = date(2024, 1, 1)
            contract.wage_type = "monthly"
            contract.pay_frequency = "monthly"
            contract.wage = salary
            contract.filing_status = self.config["filing_status"]
            contract.contract_status = "active"
            contract.save()
            contract.set_salary_structure(self.config["salary_structure"])
            employees.append(employee)
        return employees

    def test_twenty_employee_workforce_has_payroll_ready_salary_records(self):
        employees = self.make_workforce()
        days = calendar.monthrange(self.period_start.year, self.period_start.month)[1]

        for employee in employees:
            calculation = payroll_calculation(
                employee,
                self.period_start,
                self.period_end,
                month_summary={"present": days, "pay_period_days": days},
            )
            self.assertIsNotNone(calculation)
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
            }
            calculate_employer_contribution(payload)
            save_payslip(**payload)

        self.assertEqual(Employee._base_manager.filter(email__contains="@example.test").count(), 20)
        self.assertEqual(
            Contract._base_manager.filter(employee_id__in=employees, contract_status="active").count(),
            20,
        )
        payslips = Payslip._base_manager.filter(
            employee_id__in=employees,
            start_date=self.period_start,
            end_date=self.period_end,
        )
        self.assertEqual(payslips.count(), 20)
        self.assertTrue(all(slip.net_pay > 0 for slip in payslips))
        self.assertTrue(all(slip.pay_head_data.get("pretax_deductions") for slip in payslips))

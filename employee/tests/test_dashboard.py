"""Employee dashboard workforce KPI tests."""

import json

from django.test import RequestFactory, SimpleTestCase, TestCase

from base.models import EmployeeType
from employee.dashboard import _employee_type_category, employee_kpi_data
from employee.models import Employee, EmployeeWorkInformation
from horilla.testkit import CompanyFilterTestMixin, make_company, make_employee


class EmployeeTypeCategoryTests(SimpleTestCase):
    def test_common_employee_type_aliases_are_classified(self):
        aliases = {
            "Contractual Employees": "contractual",
            "Contractor": "contractual",
            "Internships": "internships",
            "Intern Staff": "internships",
            "National-Service Personnel": "national_service",
            "NSS": "national_service",
        }

        for label, expected in aliases.items():
            with self.subTest(label=label):
                self.assertEqual(_employee_type_category(label), expected)

    def test_unrelated_employee_type_is_not_classified(self):
        self.assertIsNone(_employee_type_category("Permanent"))
        self.assertIsNone(_employee_type_category(None))


class EmployeeDashboardKpiTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Dashboard Co")
        cls.viewer = make_employee(
            company=cls.company,
            email="dashboard-viewer@test.horilla",
            first_name="Dashboard",
            last_name="Viewer",
        )

        employee_types = {
            label: EmployeeType.objects.create(employee_type=label)
            for label in (
                "Contractual",
                "Internship",
                "National Service Personnel",
                "NSS",
                "Permanent",
            )
        }
        for employee_type in employee_types.values():
            employee_type.company_id.add(cls.company)

        typed_employees = []
        for index, label in enumerate(employee_types, start=1):
            employee = make_employee(
                company=cls.company,
                email=f"dashboard-{index}@test.horilla",
                first_name=f"Employee{index}",
            )
            EmployeeWorkInformation.objects.filter(employee_id=employee).update(
                employee_type_id=employee_types[label]
            )
            typed_employees.append(employee)

        inactive_contract = make_employee(
            company=cls.company,
            email="inactive-contract@test.horilla",
            first_name="Inactive",
            last_name="Contract",
        )
        EmployeeWorkInformation.objects.filter(employee_id=inactive_contract).update(
            employee_type_id=employee_types["Contractual"]
        )
        Employee.objects.filter(pk=inactive_contract.pk).update(is_active=False)

        other_company = make_company(
            "Other Dashboard Co",
            address="2 Test St",
            city="Accra",
            zip="GA100",
            hq=False,
        )
        other_contract_type = EmployeeType.objects.create(employee_type="Contractual")
        other_contract_type.company_id.add(other_company)
        other_contract = make_employee(
            company=other_company,
            email="other-company-contract@test.horilla",
            first_name="Other",
            last_name="Contract",
        )
        EmployeeWorkInformation.objects.filter(employee_id=other_contract).update(
            employee_type_id=other_contract_type
        )

        cls.employee_types = employee_types

    def setUp(self):
        self.factory = RequestFactory()
        self.set_company_context(self.company.pk)

    def test_kpi_returns_active_headcount_and_priority_categories(self):
        request = self.factory.get("/employee/dashboard/api/kpi/")
        request.user = self.viewer.employee_user_id

        response = employee_kpi_data(request)
        data = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["headcount"], 6)
        self.assertEqual(data["contractual"], 1)
        self.assertEqual(data["internships"], 1)
        self.assertEqual(data["national_service"], 2)
        self.assertCountEqual(
            data["employee_type_ids"]["national_service"],
            [
                self.employee_types["National Service Personnel"].pk,
                self.employee_types["NSS"].pk,
            ],
        )

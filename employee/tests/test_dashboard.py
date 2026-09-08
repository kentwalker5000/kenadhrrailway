"""Employee dashboard workforce KPI tests."""

import json
from pathlib import Path

from django.contrib.auth.models import Permission
from django.template import Engine
from django.test import RequestFactory, SimpleTestCase, TestCase

from attendance.models import AttendanceGeneralSetting
from base.models import EmployeeType
from base.ess_dashboard import ess_kpi_data
from employee.dashboard import employee_kpi_data
from employee.models import Employee, EmployeeWorkInformation
from employee.workforce import employee_type_category
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
                self.assertEqual(employee_type_category(label), expected)

    def test_unrelated_employee_type_is_not_classified(self):
        self.assertIsNone(employee_type_category("Permanent"))
        self.assertIsNone(employee_type_category(None))


class EssDashboardCustomizerTemplateTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_source = (
            Path(__file__).resolve().parents[2]
            / "base"
            / "templates"
            / "base"
            / "ess_dashboard.html"
        ).read_text(encoding="utf-8")

    def test_employee_dashboard_template_compiles(self):
        self.assertIsNotNone(Engine.get_default().from_string(self.template_source))

    def test_customizer_exposes_all_dashboard_sections(self):
        self.assertIn('id="essOpenCustomize"', self.template_source)
        self.assertIn('id="essCustomizePanel"', self.template_source)

        widget_ids = {
            "workforce_overview",
            "personal_overview",
            "leave_balance",
            "work_hours",
            "attendance_calendar",
            "recent_payslips",
            "goals",
            "recent_leave_requests",
            "announcements",
            "upcoming",
        }
        for widget_id in widget_ids:
            with self.subTest(widget_id=widget_id):
                self.assertEqual(
                    self.template_source.count(
                        f'data-ess-widget-id="{widget_id}"'
                    ),
                    1,
                )

    def test_preferences_are_versioned_and_scoped_to_the_signed_in_user(self):
        self.assertIn(
            "ess_dashboard_prefs_v1_{{ request.user.pk|escapejs }}",
            self.template_source,
        )
        self.assertIn("normalizeWidgetPrefs", self.template_source)
        self.assertNotIn("dashboard-save-prefs", self.template_source)


class EmployeeDashboardKpiTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Dashboard Co")
        cls.attendance_settings = AttendanceGeneralSetting.objects.create(
            company_id=cls.company,
            enable_check_in=True,
        )
        cls.viewer = make_employee(
            company=cls.company,
            email="dashboard-viewer@test.horilla",
            first_name="Dashboard",
            last_name="Viewer",
        )
        cls.viewer.employee_user_id.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="employee",
                codename="view_employee",
            )
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
        cls.unprivileged_employee = typed_employees[0]

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

    def test_ess_kpi_exposes_the_same_workforce_summary(self):
        request = self.factory.get("/ess/api/kpi/")
        request.user = self.viewer.employee_user_id

        response = ess_kpi_data(request)
        workforce = json.loads(response.content)["workforce"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(workforce["headcount"], 6)
        self.assertEqual(workforce["contractual"], 1)
        self.assertEqual(workforce["internships"], 1)
        self.assertEqual(workforce["national_service"], 2)

    def test_ess_kpi_hides_workforce_summary_without_employee_permission(self):
        request = self.factory.get("/ess/api/kpi/")
        request.user = self.unprivileged_employee.employee_user_id

        response = ess_kpi_data(request)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(json.loads(response.content)["workforce"])

    def test_ess_customizer_only_lists_workforce_for_authorized_users(self):
        common_widget = 'data-ess-widget-id="personal_overview"'
        workforce_widget = 'data-ess-widget-id="workforce_overview"'
        work_hours_widget = 'data-ess-widget-id="work_hours"'

        for employee, workforce_is_visible in (
            (self.viewer, True),
            (self.unprivileged_employee, False),
        ):
            with self.subTest(workforce_is_visible=workforce_is_visible):
                user = employee.employee_user_id
                user.is_new_employee = False
                user.save(update_fields=["is_new_employee"])
                self.client.force_login(user)
                session = self.client.session
                session["selected_company"] = str(self.company.pk)
                session.save()
                response = self.client.get("/ess/", HTTP_HOST="localhost")
                html = response.content.decode()

                self.assertEqual(
                    response.status_code,
                    200,
                    response.headers.get("Location", "unexpected response"),
                )
                self.assertIn('id="essOpenCustomize"', html)
                self.assertIn(common_widget, html)
                self.assertIn(work_hours_widget, html)
                self.assertEqual(workforce_widget in html, workforce_is_visible)
                self.assertIn(f"ess_dashboard_prefs_v1_{user.pk}", html)

        AttendanceGeneralSetting._base_manager.all().update(enable_check_in=False)
        self.client.force_login(self.viewer.employee_user_id)
        response = self.client.get("/ess/", HTTP_HOST="localhost")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(work_hours_widget, html)
        self.assertIn('data-ess-widget-id="attendance_calendar"', html)

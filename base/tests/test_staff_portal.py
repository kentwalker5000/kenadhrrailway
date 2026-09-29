"""Staff workspace access is personal and cannot reveal another employee's records."""

from datetime import date, time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from django.test import TestCase
from django.urls import reverse

from attendance.models import Attendance
from horilla.testkit import (
    CompanyFilterTestMixin,
    make_company,
    make_employee,
    make_user,
)
from horilla_documents.models import Document
from payroll.models.models import Payslip


class StaffPortalTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Staff Portal Company")
        cls.other_company = make_company(
            "Other Staff Portal Company", address="2 Other St"
        )
        cls.user = make_user("staff-portal-user")
        cls.employee = make_employee(
            company=cls.company,
            user=cls.user,
            email="staff-portal-user@example.test",
            first_name="Ama",
            last_name="Mensah",
        )
        cls.other_user = make_user("other-staff-user")
        cls.other_employee = make_employee(
            company=cls.other_company,
            user=cls.other_user,
            email="other-staff-user@example.test",
            first_name="Private",
            last_name="Colleague",
        )
        cls.own_document = Document.objects.create(
            title="Ama Passport", employee_id=cls.employee, status="requested"
        )
        cls.other_document = Document.objects.create(
            title="Private Colleague Passport",
            employee_id=cls.other_employee,
            status="approved",
        )
        cls.own_payslip = Payslip.objects.create(
            employee_id=cls.employee,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            pay_head_data={"synthetic": True},
            basic_pay=1200,
            gross_pay=1350,
            net_pay=1210,
            deduction=140,
            status="paid",
        )
        cls.other_payslip = Payslip.objects.create(
            employee_id=cls.other_employee,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            pay_head_data={"synthetic": True},
            basic_pay=9000,
            gross_pay=9200,
            net_pay=9001,
            deduction=199,
            status="paid",
        )
        cls.attendance = Attendance.objects.create(
            employee_id=cls.employee,
            attendance_date=date.today(),
            attendance_clock_in_date=date.today(),
            attendance_clock_in=time(8, 30),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_home_route_sends_a_regular_employee_to_staff_workspace(self):
        response = self.client.get(reverse("home-page"))
        self.assertRedirects(
            response, reverse("staff-platform"), fetch_redirect_response=False
        )

    def test_dashboard_route_returns_employee_to_the_same_workspace(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(
            response, reverse("staff-platform"), fetch_redirect_response=False
        )

    def test_personal_dashboard_remains_available_separately(self):
        response = self.client.get(reverse("ess-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "base/ess_dashboard.html")
        self.assertContains(response, "Personal Dashboard")

    def test_reporting_manager_keeps_the_analytics_dashboard(self):
        work_info = self.other_employee.employee_work_info
        work_info.company_id = self.company
        work_info.reporting_manager_id = self.employee
        work_info.save()
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard.html")

    def test_employee_can_still_explicitly_open_analytics(self):
        response = self.client.get(reverse("dashboard"), {"view": "analytics"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard.html")

    def test_workspace_renders_personal_workday_and_real_actions(self):
        response = self.client.get(reverse("staff-platform"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome back, Ama.")
        self.assertContains(response, "You are checked in.")
        self.assertContains(response, "Ama Passport")
        self.assertContains(response, "1,210.00")
        for route in (
            "staff-attendance",
            "staff-leave",
            "staff-payslips",
            "staff-documents",
            "staff-profile",
        ):
            self.assertContains(response, f'href="{reverse(route)}"')
        sidebar = BeautifulSoup(response.content, "html.parser")
        home_link = sidebar.select_one('a[data-menu="Dashboard"]')
        self.assertIsNotNone(home_link)
        self.assertEqual(home_link["href"], reverse("home-page"))
        self.assertIn(
            reverse("staff-platform"), home_link["data-match-prefixes"].split(",")
        )

    def test_workspace_never_leaks_another_company_employee_or_records(self):
        response = self.client.get(reverse("staff-platform"))
        for private_value in (
            self.other_company.company,
            self.other_employee.get_full_name(),
            self.other_document.title,
            "9,001.00",
        ):
            self.assertNotContains(response, private_value)

    def test_staff_payslips_are_scoped_to_the_signed_in_employee(self):
        response = self.client.get(reverse("staff-payslips"))
        self.assertContains(response, "1,210.00")
        self.assertNotContains(response, "9,001.00")
        self.assertContains(
            response,
            reverse("payslip-pdf", kwargs={"id": self.own_payslip.pk}),
        )
        self.assertNotContains(
            response,
            reverse("payslip-pdf", kwargs={"id": self.other_payslip.pk}),
        )

    def test_staff_documents_are_scoped_to_the_signed_in_employee(self):
        response = self.client.get(reverse("staff-documents"))
        self.assertContains(response, self.own_document.title)
        self.assertNotContains(response, self.other_document.title)
        self.assertNotContains(
            response, reverse("view-file", kwargs={"id": self.other_document.pk})
        )

    def test_workflow_links_lead_to_the_existing_self_scoped_pages(self):
        expected = {
            "staff-attendance": "view-my-attendance",
            "staff-leave": "user-request-view",
        }
        for source, destination in expected.items():
            response = self.client.get(reverse(source))
            self.assertRedirects(
                response, reverse(destination), fetch_redirect_response=False
            )

    def test_staff_pages_are_private_and_read_only_on_their_own_routes(self):
        self.client.logout()
        for route in ("staff-platform", "staff-payslips", "staff-documents"):
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(
                urlsplit(response.url).path.rstrip("/"), reverse("login").rstrip("/")
            )
        for route in ("staff-platform", "staff-payslips", "staff-documents"):
            response = self.client.post(reverse(route))
            self.assertEqual(response.status_code, 405)

    def test_a_stale_cross_company_session_is_corrected_before_rendering(self):
        session = self.client.session
        session["selected_company"] = str(self.other_company.pk)
        session.save()
        response = self.client.get(reverse("staff-platform"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["selected_company"], str(self.company.pk))
        self.assertNotContains(response, self.other_document.title)

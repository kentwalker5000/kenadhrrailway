"""Regression tests for the attendance overview dashboard API."""

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from attendance.models import Attendance
from attendance.views.dashboard import generate_data_set
from base.models import Department
from horilla.testkit import (
    CompanyFilterTestMixin,
    make_company,
    make_employee,
    make_user,
)


class DashboardAttendanceOverviewTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Dashboard Attendance Co")
        cls.department = Department.objects.create(department="Operations")
        cls.department.company_id.add(cls.company)
        cls.user = make_user("dashboard-attendance-hr")
        cls.employee = make_employee(
            company=cls.company,
            department=cls.department,
            user=cls.user,
            email="dashboard-attendance@example.test",
        )
        cls.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="attendance", codename="view_attendance"
            )
        )
        cls.attendance = Attendance.objects.create(
            employee_id=cls.employee,
            attendance_date=timezone.localdate(),
            attendance_clock_in_date=timezone.localdate(),
            attendance_clock_in="09:00",
            minimum_hour="08:00",
        )

    def test_overview_builds_a_dataset_for_a_department(self):
        self.set_company_context(str(self.company.pk))
        dataset = generate_data_set(
            None,
            timezone.localdate(),
            "date",
            timezone.localdate(),
            self.department,
        )

        self.assertEqual(dataset["label"], self.department.department)
        self.assertEqual(dataset["data"], [1, 0, 0])

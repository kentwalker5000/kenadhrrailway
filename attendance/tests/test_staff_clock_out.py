"""Tests for HR-controlled staff clock-out."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from attendance.models import Attendance, AttendanceActivity
from horilla.testkit import CompanyFilterTestMixin, make_company, make_employee, make_user


class StaffClockOutTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Attendance Company")
        cls.hr_user = make_user("attendance-hr")
        cls.hr = make_employee(
            company=cls.company,
            user=cls.hr_user,
            email="hr@example.test",
        )
        cls.hr_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="attendance", codename="change_attendance"
            )
        )
        cls.staff_user = make_user("attendance-staff")
        cls.staff = make_employee(
            company=cls.company,
            user=cls.staff_user,
            email="staff@example.test",
        )

    def setUp(self):
        self.set_company_context(str(self.company.pk))
        self.now = timezone.localtime().replace(second=0, microsecond=0)
        self.attendance = Attendance.objects.create(
            employee_id=self.staff,
            attendance_date=self.now.date(),
            attendance_clock_in_date=self.now.date(),
            attendance_clock_in=(self.now - timedelta(hours=2)).time(),
            minimum_hour="00:00",
        )
        self.activity = AttendanceActivity.objects.create(
            employee_id=self.staff,
            attendance_date=self.now.date(),
            clock_in_date=self.now.date(),
            clock_in=(self.now - timedelta(hours=2)).time(),
            in_datetime=self.now - timedelta(hours=2),
        )

    @property
    def url(self):
        return reverse("staff-clock-out", kwargs={"attendance_id": self.attendance.pk})

    def test_hr_can_clock_out_an_active_staff_attendance(self):
        self.client.force_login(self.hr_user)

        with patch("attendance.views.clock_in_out.timezone.localtime", return_value=self.now):
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, 204)
        self.attendance.refresh_from_db()
        self.activity.refresh_from_db()
        self.assertEqual(self.attendance.attendance_clock_out_date, self.now.date())
        self.assertEqual(self.attendance.attendance_clock_out, self.now.time())
        self.assertEqual(self.activity.clock_out_date, self.now.date())
        self.assertEqual(self.activity.clock_out, self.now.time())

    def test_staff_member_cannot_clock_out_another_staff_member(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.clock_out)

    def test_older_open_attendance_requires_edit_instead_of_clock_out_now(self):
        self.attendance.attendance_date = self.now.date() - timedelta(days=2)
        self.attendance.attendance_clock_in_date = self.attendance.attendance_date
        self.attendance.save()
        self.activity.attendance_date = self.attendance.attendance_date
        self.activity.clock_in_date = self.attendance.attendance_date
        self.activity.save()
        self.client.force_login(self.hr_user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 409)
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.clock_out)

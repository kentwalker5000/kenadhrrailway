from datetime import date, time
import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from attendance.models import Attendance, AttendanceActivity, AttendanceGeneralSetting, AttendanceOverTime, AttendanceValidationCondition
from attendance.permissions import can_manage_attendance
from attendance.views.requests import apply_attendance_correction, reconcile_corrected_activity
from attendance.views.views import attendance_validate
from employee.models import EmployeeWorkInformation
from geofencing.checks import check_location
from geofencing.models import GeoFencing
from horilla.testkit import make_company, make_employee, make_user


class AttendanceSafeguardsTests(TestCase):
    def setUp(self):
        self.company = make_company("Safeguards Company")
        self.manager = make_employee(company=self.company, email="mgr@attendance.test", user=make_user("safe-manager"))
        self.staff = make_employee(company=self.company, email="staff@attendance.test", user=make_user("safe-staff"))
        self.other = make_employee(company=self.company, email="other@attendance.test", user=make_user("safe-other"))
        EmployeeWorkInformation.objects.filter(employee_id=self.staff).update(reporting_manager_id=self.manager)
        self.attendance = Attendance.objects.create(employee_id=self.staff, attendance_date=date(2026, 10, 19),
            attendance_clock_in_date=date(2026, 10, 19), attendance_clock_in=time(9),
            attendance_clock_out_date=date(2026, 10, 19), attendance_clock_out=time(17),
            attendance_worked_hour="08:00", minimum_hour="08:00")

    def test_manager_can_only_manage_own_direct_report(self):
        self.assertTrue(can_manage_attendance(self.manager.employee_user_id, self.attendance))
        self.assertFalse(can_manage_attendance(self.other.employee_user_id, self.attendance))
        self.assertFalse(can_manage_attendance(self.staff.employee_user_id, self.attendance))

    def test_manager_cannot_approve_another_team(self):
        EmployeeWorkInformation.objects.filter(employee_id=self.staff).update(reporting_manager_id=self.other)
        # Still a manager, but of an unrelated person.
        EmployeeWorkInformation.objects.filter(employee_id=self.other).update(reporting_manager_id=self.manager)
        self.client.force_login(self.manager.employee_user_id)
        response = self.client.post(reverse("approve-validate-attendance-request", args=[self.attendance.pk]))
        self.assertEqual(response.status_code, 403)

    def test_minimum_hours_are_required(self):
        with patch("attendance.views.views.AttendanceValidationCondition.objects") as conditions:
            conditions.all.return_value.exists.return_value = False
            self.attendance.attendance_worked_hour = "08:00"
            self.assertFalse(attendance_validate(self.attendance))
            self.attendance.attendance_worked_hour = "09:00"
            self.assertTrue(attendance_validate(self.attendance))

    def test_location_requires_valid_coordinates_inside_radius(self):
        GeoFencing.objects.create(company_id=self.company, latitude=5.60362, longitude=-0.17743, radius_in_meters=100, start=True)
        self.assertIsNone(check_location(self.staff, {"latitude": 5.60362, "longitude": -0.17743}))
        self.assertIsNotNone(check_location(self.staff, {}))
        self.assertIsNotNone(check_location(self.staff, {"latitude": 5.7, "longitude": -0.17743}))
        self.assertIsNotNone(check_location(self.staff, {"latitude": "nan", "longitude": 0}))

    def test_browser_clock_in_does_not_bypass_location(self):
        GeoFencing.objects.create(company_id=self.company, latitude=5.60362, longitude=-0.17743, radius_in_meters=100, start=True)
        AttendanceGeneralSetting.objects.update_or_create(company_id=self.company, defaults={"enable_check_in": True})
        self.client.force_login(self.staff.employee_user_id)
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()
        before = AttendanceActivity.objects.filter(employee_id=self.staff).count()
        response = self.client.get(reverse("clock-in"), HTTP_HX_REQUEST="true")
        self.assertEqual(AttendanceActivity.objects.filter(employee_id=self.staff).count(), before)
        from django.contrib.messages import get_messages
        self.assertTrue(any("valid location" in str(message).lower() for message in get_messages(response.wsgi_request)))

    def test_corrected_clock_events_match_attendance(self):
        activity = AttendanceActivity.objects.create(employee_id=self.staff, attendance_date=date(2026,10,19),
            clock_in_date=date(2026,10,19), clock_in=time(9), clock_out_date=date(2026,10,19), clock_out=time(17))
        self.attendance.requested_data = json.dumps({"attendance_clock_in": "08:30:00", "attendance_clock_out": "17:30:00", "attendance_worked_hour": "09:00"})
        previous = self.attendance.attendance_date
        apply_attendance_correction(self.attendance)
        reconcile_corrected_activity(self.attendance, previous)
        activity.refresh_from_db()
        self.assertEqual(activity.clock_in, time(8,30))
        self.assertEqual(activity.clock_out, time(17,30))
        self.assertEqual(self.attendance.attendance_worked_hour, "09:00")

    def test_correction_to_another_month_moves_worked_hours(self):
        self.attendance.requested_data = json.dumps({
            "attendance_date": "2026-11-02", "attendance_clock_in_date": "2026-11-02",
            "attendance_clock_out_date": "2026-11-02",
        })
        apply_attendance_correction(self.attendance)
        october = AttendanceOverTime.objects.get(employee_id=self.staff, year=2026, month="october")
        november = AttendanceOverTime.objects.get(employee_id=self.staff, year=2026, month="november")
        self.assertEqual(october.hour_account_second, 0)
        self.assertEqual(november.hour_account_second, 8 * 3600)

    @patch("attendance.views.requests.notify.send")
    def test_reject_new_request_removes_placeholder(self, notify):
        self.attendance.request_type = "create_request"
        self.attendance.is_validate_request = True
        self.attendance.save()
        pk = self.attendance.pk
        self.client.force_login(self.manager.employee_user_id)
        self.client.post(reverse("cancel-validate-attendance-request", args=[pk]))
        self.assertFalse(Attendance.objects.filter(pk=pk).exists())

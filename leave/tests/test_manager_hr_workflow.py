from datetime import timedelta
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone
from employee.models import EmployeeWorkInformation
from horilla.testkit import make_company, make_employee, make_user
from horilla.testkit.factories import make_leave_type, make_leave_request, make_available_leave
from leave.approval_workflow import approve_leave
from leave.models import LeaveManagerReview


class ManagerHRApprovalTests(TestCase):
    def setUp(self):
        company = make_company("Leave workflow test")
        self.staff = make_employee(company=company, email="staff@leave.test", user=make_user("leave-staff"))
        self.manager = make_employee(company=company, email="manager@leave.test", user=make_user("leave-manager"))
        self.hr = make_employee(company=company, email="hr@leave.test", user=make_user("leave-hr"))
        self.other = make_employee(company=company, email="other@leave.test", user=make_user("leave-other"))
        self.hr.employee_user_id.user_permissions.add(Permission.objects.get(codename="final_approve_leaverequest"))
        EmployeeWorkInformation.objects.filter(employee_id=self.staff).update(reporting_manager_id=self.manager)
        leave_type = make_leave_type("Workflow annual leave")
        self.balance = make_available_leave(employee=self.staff, leave_type=leave_type, available=10)
        day = timezone.localdate()+timedelta(days=10)
        self.leave = make_leave_request(employee=self.staff, leave_type=leave_type, start_date=day, end_date=day, status="requested")

    def test_hr_cannot_skip_manager_review(self):
        with self.assertRaises(PermissionDenied):
            approve_leave(self.leave.pk, self.hr.employee_user_id)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.available_days, 10)

    def test_review_then_final_approval_deducts_once(self):
        leave, _ = approve_leave(self.leave.pk, self.manager.employee_user_id)
        self.assertEqual(leave.status, "requested")
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.available_days, 10)
        leave, _ = approve_leave(self.leave.pk, self.hr.employee_user_id)
        self.assertEqual(leave.status, "approved")
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.available_days, 10-leave.requested_days)
        with self.assertRaises(ValidationError):
            approve_leave(self.leave.pk, self.hr.employee_user_id)

    def test_unrelated_staff_and_self_cannot_review(self):
        for actor in (self.staff, self.other):
            with self.assertRaises(PermissionDenied):
                approve_leave(self.leave.pk, actor.employee_user_id)
        self.assertFalse(LeaveManagerReview.objects.exists())

    def test_manager_cannot_finalize_even_with_hr_permission(self):
        self.manager.employee_user_id.user_permissions.add(Permission.objects.get(codename="final_approve_leaverequest"))
        approve_leave(self.leave.pk, self.manager.employee_user_id)
        with self.assertRaises(PermissionDenied):
            approve_leave(self.leave.pk, self.manager.employee_user_id)

    def test_changed_dates_need_fresh_manager_review(self):
        approve_leave(self.leave.pk, self.manager.employee_user_id)
        self.leave.end_date += timedelta(days=1)
        self.leave.save()
        with self.assertRaises(PermissionDenied):
            approve_leave(self.leave.pk, self.hr.employee_user_id)

    def test_other_company_hr_cannot_approve(self):
        approve_leave(self.leave.pk, self.manager.employee_user_id)
        EmployeeWorkInformation.objects.filter(employee_id=self.hr).update(company_id=make_company("Other company"))
        with self.assertRaises(PermissionDenied):
            approve_leave(self.leave.pk, self.hr.employee_user_id)

    def test_insufficient_balance_preserves_pending_request(self):
        approve_leave(self.leave.pk, self.manager.employee_user_id)
        self.balance.available_days = 0
        self.balance.save()
        with self.assertRaises(ValidationError):
            approve_leave(self.leave.pk, self.hr.employee_user_id)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, "requested")

    def test_ceo_reviews_and_finally_approves_hr_own_leave(self):
        from base.models import Department, JobPosition
        from leave.approval_workflow import can_approve, approval_stage
        department = Department.objects.create(department="Executive")
        position = JobPosition.objects.create(job_position="Chief Executive Officer", department_id=department)
        EmployeeWorkInformation.objects.filter(employee_id=self.manager).update(job_position_id=position)
        EmployeeWorkInformation.objects.filter(employee_id=self.hr).update(reporting_manager_id=self.manager)
        leave_type = self.leave.leave_type_id
        balance = make_available_leave(employee=self.hr, leave_type=leave_type, available=10)
        day = timezone.localdate() + timedelta(days=10)
        hr_leave = make_leave_request(employee=self.hr, leave_type=leave_type, start_date=day, end_date=day, status="requested")
        leave, _ = approve_leave(hr_leave.pk, self.manager.employee_user_id)
        self.assertEqual(leave.status, "requested")
        self.assertEqual(approval_stage(leave), "Awaiting CEO approval")
        self.assertTrue(can_approve(leave, self.manager.employee_user_id))
        leave, _ = approve_leave(hr_leave.pk, self.manager.employee_user_id)
        self.assertEqual(leave.status, "approved")
        balance.refresh_from_db()
        self.assertEqual(balance.available_days, 10 - leave.requested_days)

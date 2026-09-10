"""Real attendance/leave records through payroll calculation and draft creation."""

from datetime import date, timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase, override_settings
from django.urls import reverse

from attendance.views.summary import build_monthly_summary
from attendance.models import AttendanceSummaryHours
from employee.models import Employee
from horilla.testkit import clear_selected_company, make_company, make_employee
from horilla.testkit.factories import make_attendance, make_leave_request
from leave.models import LeaveType
from payroll.forms.component_forms import GeneratePayslipForm
from payroll.methods.methods import compute_salary_on_period, get_attendance
from payroll.models.models import Contract, Payslip
from payroll.views.component_views import payroll_calculation


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class AttendanceLeavePayrollHandoffTests(TestCase):
    def setUp(self):
        clear_selected_company()
        self.addCleanup(clear_selected_company)
        media = TemporaryDirectory(prefix="payroll-test-")
        self.addCleanup(media.cleanup)
        settings_override = override_settings(MEDIA_ROOT=media.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.company = make_company("Payroll Handoff Co")
        self.start = date(2024, 1, 8)
        self.end = date(2024, 1, 11)
        self.employee = make_employee(
            company=self.company, email="payroll-flow@test.horilla"
        )
        self.contract = self.activate(self.employee)
        self.paid = LeaveType.objects.create(
            name="Paid Handoff", payment="paid", payment_type="paid", total_days=20
        )
        self.unpaid = LeaveType.objects.create(
            name="Unpaid Handoff",
            payment="unpaid",
            payment_type="unpaid",
            total_days=20,
        )

    def activate(self, employee, **overrides):
        Contract.objects.filter(employee_id=employee).delete()
        fields = {
            "contract_name": f"Contract {employee.pk}",
            "employee_id": employee,
            "contract_start_date": self.start,
            "contract_status": "active",
            "wage_type": "daily",
            "wage": 100,
            "deduct_leave_from_basic_pay": True,
            "calculate_daily_leave_amount": True,
        }
        fields.update(overrides)
        return Contract.objects.create(**fields)

    def attendance(self, day, employee=None, validated=True):
        return make_attendance(
            employee=employee or self.employee, attendance_date=day, validated=validated
        )

    def leave(self, day, paid=False, status="approved"):
        return make_leave_request(
            employee=self.employee,
            leave_type=self.paid if paid else self.unpaid,
            start_date=day,
            end_date=day,
            status=status,
        )

    def summary(self):
        return build_monthly_summary(
            self.start, self.end, Employee.objects.filter(pk=self.employee.pk)
        )[0][0]

    def mixed_days(self):
        self.attendance(self.start)
        self.attendance(self.start + timedelta(days=1))
        self.leave(self.start + timedelta(days=2), paid=True)
        self.leave(self.end)

    def test_approved_leave_reaches_summary_and_is_deducted_only_once(self):
        self.mixed_days()
        summary = self.summary()
        self.assertEqual(
            (summary["present"], summary["paid_leave"], summary["unpaid_leave"]),
            (2, 1, 1),
        )
        salary = compute_salary_on_period(
            self.employee, self.start, self.end, month_summary=summary
        )
        self.assertEqual(salary["paid_days"], 3)
        self.assertEqual(salary["loss_of_pay"], 100)
        self.assertEqual(salary["basic_pay"], 300)

    def test_loss_as_separate_deduction_has_the_same_net_pay(self):
        self.mixed_days()
        self.contract.deduct_leave_from_basic_pay = False
        self.contract.save()
        result = payroll_calculation(
            self.employee, self.start, self.end, month_summary=self.summary()
        )
        self.assertEqual(result["basic_pay"], 400)
        self.assertEqual(result["loss_of_pay"], 100)
        self.assertEqual(result["net_pay"], 300)

    def test_monthly_loss_of_pay_is_not_deducted_again_from_net_pay(self):
        self.mixed_days()
        self.contract.wage_type = "monthly"
        self.contract.wage = 400
        self.contract.save()
        for deduct_from_basic in (True, False):
            with self.subTest(deduct_from_basic=deduct_from_basic):
                self.contract.deduct_leave_from_basic_pay = deduct_from_basic
                self.contract.save()
                result = payroll_calculation(
                    self.employee, self.start, self.end, month_summary=self.summary()
                )
                self.assertEqual(result["net_pay"], 300)
                self.assertEqual(
                    result["total_deductions"], 0 if deduct_from_basic else 100
                )
                self.assertEqual(
                    result["loss_of_pay_deducted_from_basic"], deduct_from_basic
                )

    def test_requested_and_rejected_leave_do_not_count_as_approved_leave(self):
        self.leave(self.start, paid=True, status="requested")
        self.leave(self.end, paid=True, status="rejected")
        summary = self.summary()
        self.assertEqual(summary["paid_leave"], 0)
        self.assertEqual(summary["unpaid_leave"], 0)
        self.assertEqual(summary["absent"], 4)

    def test_present_dates_are_not_missing_attendance_conflicts(self):
        self.attendance(self.start)
        data = get_attendance(self.employee, self.start, self.end)
        self.assertNotIn(self.start, data["conflict_dates"])
        self.assertIn(self.end, data["conflict_dates"])

    def test_payroll_summary_counts_only_validated_attendance(self):
        self.attendance(self.start, validated=False)
        self.attendance(self.end)
        rows, _, _ = build_monthly_summary(
            self.start,
            self.end,
            Employee.objects.filter(pk=self.employee.pk),
            validated_only=True,
        )
        self.assertEqual(rows[0]["present"], 1)
        self.assertEqual(rows[0]["absent"], 3)
        # The ordinary attendance page still shows entries awaiting validation.
        self.assertEqual(self.summary()["present"], 2)

    def test_payroll_does_not_overwrite_attendance_page_hours(self):
        self.attendance(self.start, validated=False)
        self.attendance(self.end)
        self.summary()
        hours = AttendanceSummaryHours.objects.get(
            employee_id=self.employee, from_date=self.start, to_date=self.end
        )
        original_hours = hours.hours_second
        build_monthly_summary(
            self.start,
            self.end,
            Employee.objects.filter(pk=self.employee.pk),
            validated_only=True,
        )
        hours.refresh_from_db()
        self.assertEqual(hours.hours_second, original_hours)

    def test_generation_form_handles_missing_dates(self):
        for data in (
            {},
            {"start_date": str(self.start)},
            {"end_date": str(self.end)},
            {"start_date": "invalid", "end_date": str(self.end)},
        ):
            with self.subTest(data=data):
                form_data = QueryDict("", mutable=True)
                form_data.update(data)
                form_data.setlist("employee_id", [str(self.employee.pk)])
                form = GeneratePayslipForm(data=form_data)
                self.assertFalse(form.is_valid())
                self.assertTrue(
                    "start_date" in form.errors or "end_date" in form.errors
                )

    def login_hr(self):
        user = get_user_model().objects.create_superuser(
            username="payroll-hr",
            email="payroll-hr@test.horilla",
            password="Test-password-only!",
        )
        make_employee(company=self.company, email=user.email, user=user)
        self.client.force_login(user)

    def generate(self, employees):
        return self.client.post(
            reverse("generate-payslip"),
            {
                "employee_id": [employee.pk for employee in employees],
                "start_date": str(self.start),
                "end_date": str(self.end),
                "group_name": "Integration test",
            },
        )

    def test_generated_draft_has_correct_leave_deduction(self):
        self.mixed_days()
        self.login_hr()
        self.assertEqual(self.generate([self.employee]).status_code, 302)
        payslip = Payslip.objects.get(employee_id=self.employee)
        self.assertEqual(payslip.status, "draft")
        self.assertEqual(payslip.basic_pay, 300)
        self.assertEqual(payslip.net_pay, 300)
        self.assertEqual(payslip.pay_head_data["unpaid_days"], 1)
        detail = self.client.get(
            reverse("view-created-payslip", kwargs={"payslip_id": payslip.pk})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Already deducted from basic pay")

    def test_generation_excludes_unvalidated_attendance(self):
        self.attendance(self.start, validated=False)
        self.attendance(self.end)
        self.login_hr()
        self.assertEqual(self.generate([self.employee]).status_code, 302)
        payslip = Payslip.objects.get(employee_id=self.employee)
        self.assertEqual(payslip.net_pay, 100)
        self.assertEqual(len(payslip.pay_head_data["pending_attendance"]), 1)

    def test_contract_dates_do_not_spill_into_the_next_employee(self):
        other = make_employee(company=self.company, email="second-payroll@test.horilla")
        self.employee.employee_first_name = "A Later Starter"
        self.employee.save()
        other.employee_first_name = "Z Full Period"
        other.save()
        self.activate(other)
        # Force the later starter to be first in the same ordering as the form.
        selected = list(GeneratePayslipForm().fields["employee_id"].queryset)
        first, second = selected[:2]
        first_contract = Contract.objects.get(
            employee_id=first, contract_status="active"
        )
        first_contract.contract_start_date = self.start + timedelta(days=2)
        first_contract.save()
        for employee in (first, second):
            for offset in range(4):
                self.attendance(self.start + timedelta(days=offset), employee=employee)
        self.login_hr()
        self.assertEqual(self.generate([first, second]).status_code, 302)
        first_slip = Payslip.objects.get(employee_id=first)
        second_slip = Payslip.objects.get(employee_id=second)
        self.assertEqual(first_slip.start_date, self.start + timedelta(days=2))
        self.assertEqual(first_slip.net_pay, 200)
        self.assertEqual(second_slip.start_date, self.start)
        self.assertEqual(second_slip.net_pay, 400)

    def test_monthly_contract_window_is_prorated_within_the_pay_period(self):
        self.contract.wage_type = "monthly"
        self.contract.wage = 400
        self.contract.contract_start_date = self.start + timedelta(days=2)
        self.contract.save()
        self.attendance(self.start + timedelta(days=2))
        self.attendance(self.end)
        self.login_hr()
        self.assertEqual(self.generate([self.employee]).status_code, 302)
        self.assertEqual(Payslip.objects.get(employee_id=self.employee).net_pay, 200)

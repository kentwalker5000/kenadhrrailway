"""Real attendance/leave records through payroll calculation and draft creation."""

from datetime import date, timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase, override_settings
from django.urls import reverse

from attendance.views.summary import _build_calendar_context, build_monthly_summary
from attendance.models import (
    AttendanceConflictResolution,
    AttendanceSummaryHours,
    WorkRecords,
)
from base.models import Holidays
from employee.models import Employee
from horilla.testkit import clear_selected_company, make_company, make_employee
from horilla.testkit.factories import make_attendance, make_leave_request
from leave.models import LeaveRequest, LeaveType
from payroll.forms.component_forms import GeneratePayslipForm
from payroll.methods.methods import (
    compute_salary_on_period,
    get_attendance,
    get_daily_salary,
    get_leaves,
)
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

    def fractional_leave(self, leave_type, day=None, end=None, half="first_half"):
        day = day or self.start
        return LeaveRequest.objects.create(
            employee_id=self.employee,
            leave_type_id=leave_type,
            start_date=day,
            end_date=end or day,
            start_date_breakdown=half,
            end_date_breakdown=half,
            description="Fractional leave test",
            status="approved",
        )

    def half_attendance(self, day=None):
        record = self.attendance(day or self.start)
        record.attendance_worked_hour = "04:00"
        record.attendance_clock_in = "14:00:00"
        record.minimum_hour = "08:00"
        record.save()
        record.refresh_from_db()
        self.assertEqual(record.at_work_second, 14400)
        return record

    def custom_type(self, percentage=50):
        # Deliberately stale legacy value: the new payment configuration wins.
        return LeaveType.objects.create(
            name="Partially Paid Handoff",
            payment="unpaid",
            payment_type="custom",
            payment_percentage=percentage,
            total_days=20,
        )

    def fill_remaining_days(self):
        for offset in range(1, 4):
            self.attendance(self.start + timedelta(days=offset))

    def test_half_paid_leave_combines_with_half_attendance(self):
        self.fractional_leave(self.paid)
        self.half_attendance()
        self.fill_remaining_days()
        summary = self.summary()
        self.assertEqual(summary["present"], 3.5)
        self.assertEqual(summary["paid_leave"], 0.5)
        self.assertEqual(summary["absent"], 0)
        self.assertEqual(summary["unresolved_conflicts"], 0)
        self.assertEqual(
            get_leaves(self.employee, self.start, self.end)["paid_leave"], 0.5
        )
        self.assertEqual(
            payroll_calculation(
                self.employee,
                self.start,
                self.end,
                month_summary=summary,
            )["net_pay"],
            400,
        )

    def test_half_unpaid_leave_deducts_half_a_day(self):
        self.fractional_leave(self.unpaid)
        self.half_attendance()
        self.fill_remaining_days()
        summary = self.summary()
        self.assertEqual(summary["unpaid_leave"], 0.5)
        self.assertEqual(summary["unresolved_conflicts"], 0)
        for use_summary in (True, False):
            for from_basic in (True, False):
                with self.subTest(summary=use_summary, from_basic=from_basic):
                    self.contract.deduct_leave_from_basic_pay = from_basic
                    self.contract.save()
                    result = payroll_calculation(
                        self.employee,
                        self.start,
                        self.end,
                        month_summary=summary if use_summary else None,
                    )
                    self.assertEqual(result["loss_of_pay"], 50)
                    self.assertEqual(result["net_pay"], 350)

    def test_unworked_half_is_absent_not_extra_paid_leave(self):
        self.fractional_leave(self.paid)
        self.fill_remaining_days()
        summary = self.summary()
        self.assertEqual(summary["paid_leave"], 0.5)
        self.assertEqual(summary["absent"], 0.5)
        self.assertEqual(
            payroll_calculation(
                self.employee,
                self.start,
                self.end,
                month_summary=summary,
            )["net_pay"],
            350,
        )

    def test_two_complementary_half_leaves_keep_both_payment_types(self):
        self.fractional_leave(self.paid)
        self.fractional_leave(self.unpaid, half="second_half")
        summary = self.summary()
        self.assertEqual((summary["paid_leave"], summary["unpaid_leave"]), (0.5, 0.5))
        self.assertEqual(
            get_leaves(self.employee, self.start, self.end)["total_leaves"], 1
        )

    def test_full_attendance_and_half_leave_still_need_review(self):
        self.fractional_leave(self.paid)
        self.attendance(self.start)
        self.assertEqual(self.summary()["unresolved_conflicts"], 1)

    def test_custom_full_day_reduces_pay_by_percentage_only(self):
        self.fractional_leave(self.custom_type(75), half="full_day")
        self.fill_remaining_days()
        for wage_type, wage in (("daily", 100), ("monthly", 400)):
            for from_basic in (True, False):
                with self.subTest(wage_type=wage_type, from_basic=from_basic):
                    self.contract.wage_type = wage_type
                    self.contract.wage = wage
                    self.contract.deduct_leave_from_basic_pay = from_basic
                    self.contract.save()
                    result = payroll_calculation(
                        self.employee,
                        self.start,
                        self.end,
                        month_summary=self.summary(),
                    )
                    self.assertEqual(result["unpaid_days"], 0)
                    self.assertEqual(result["partial_pay_days"], 1)
                    self.assertEqual(result["custom_leave_deduction"], 25)
                    self.assertEqual(result["loss_of_pay"], 25)
                    self.assertEqual(result["net_pay"], 375)

    def test_custom_half_day_uses_fraction_for_both_calculation_paths(self):
        self.fractional_leave(self.custom_type(50))
        self.half_attendance()
        self.fill_remaining_days()
        for use_summary in (True, False):
            with self.subTest(use_summary=use_summary):
                result = payroll_calculation(
                    self.employee,
                    self.start,
                    self.end,
                    month_summary=self.summary() if use_summary else None,
                )
                self.assertEqual(result["partial_pay_days"], 0.5)
                self.assertEqual(result["loss_of_pay"], 25)
                self.assertEqual(result["net_pay"], 375)
                self.assertEqual(result["custom_leave_breakdown"][0]["days"], 0.5)
                self.assertEqual(
                    result["custom_leave_breakdown"][0]["deduction_amount"], 25
                )

    def test_custom_half_day_uses_fixed_contract_deduction_basis(self):
        self.fractional_leave(self.custom_type(50))
        self.half_attendance()
        self.fill_remaining_days()
        self.contract.calculate_daily_leave_amount = False
        self.contract.deduction_for_one_leave_amount = 80
        self.contract.save()
        result = payroll_calculation(
            self.employee,
            self.start,
            self.end,
            month_summary=self.summary(),
        )
        self.assertEqual(result["loss_of_pay"], 20)
        self.assertEqual(result["net_pay"], 380)

    def test_custom_leave_on_holiday_has_no_extra_deduction(self):
        self.fractional_leave(self.custom_type(50), half="full_day")
        Holidays.objects.create(
            name="Test holiday", start_date=self.start, end_date=self.start
        )
        self.fill_remaining_days()
        summary = self.summary()
        self.assertEqual(summary["holiday"], 1)
        self.assertEqual(summary["custom_leave_data"]["partial_pay_days"], 0)
        self.assertEqual(
            payroll_calculation(
                self.employee,
                self.start,
                self.end,
                month_summary=summary,
            )["net_pay"],
            400,
        )

    def test_hr_override_does_not_reapply_custom_leave_deduction(self):
        self.fractional_leave(self.custom_type(50), half="full_day")
        self.fill_remaining_days()
        AttendanceConflictResolution.objects.create(
            employee_id=self.employee,
            date=self.start,
            resolution="full_present",
            conflict_type="paid_leave",
        )
        result = payroll_calculation(
            self.employee,
            self.start,
            self.end,
            month_summary=self.summary(),
        )
        self.assertEqual(result["partial_pay_days"], 0)
        self.assertEqual(result["loss_of_pay"], 0)
        self.assertEqual(result["net_pay"], 400)

    def test_clipped_leave_preserves_original_half_day_boundaries(self):
        self.fractional_leave(self.unpaid, end=self.end)
        self.assertEqual(
            get_leaves(self.employee, self.start, self.end)["unpaid_leaves"], 3
        )
        self.assertEqual(
            get_leaves(self.employee, self.start, self.start)["unpaid_leaves"], 0.5
        )
        self.assertEqual(
            get_leaves(self.employee, self.end, self.end)["unpaid_leaves"], 0.5
        )
        self.assertEqual(
            get_leaves(
                self.employee,
                self.start + timedelta(days=1),
                self.end - timedelta(days=1),
            )["unpaid_leaves"],
            2,
        )

    def test_legacy_null_end_half_day_is_counted_once(self):
        request = self.fractional_leave(self.unpaid)
        LeaveRequest.objects.filter(pk=request.pk).update(end_date=None)
        self.assertEqual(
            get_leaves(self.employee, self.start, self.end)["unpaid_leaves"], 0.5
        )
        self.assertEqual(self.summary()["unpaid_leave"], 0.5)

    def test_half_day_custom_leave_reaches_saved_payslip(self):
        self.fractional_leave(self.custom_type(50))
        self.half_attendance()
        self.fill_remaining_days()
        self.login_hr()
        self.assertEqual(self.generate([self.employee]).status_code, 302)
        payslip = Payslip.objects.get(employee_id=self.employee)
        self.assertEqual(payslip.net_pay, 375)
        self.assertEqual(payslip.pay_head_data["partial_pay_days"], 0.5)
        self.assertEqual(payslip.pay_head_data["custom_leave_deduction"], 25)
        detail = self.client.get(
            reverse("view-created-payslip", kwargs={"payslip_id": payslip.pk})
        )
        self.assertContains(detail, "Partially Paid Handoff")
        self.assertContains(detail, "Included in Loss of Pay above")

    def test_calendar_agrees_with_fractional_leave_and_does_not_write_hours(self):
        self.fractional_leave(self.paid)
        self.half_attendance()
        self.fill_remaining_days()
        context = _build_calendar_context(self.employee, self.start, self.end)
        self.assertEqual(context["cal_summary"]["paid_leave"], 0.5)
        self.assertEqual(context["cal_summary"]["absent"], 0)
        self.assertEqual(context["cal_summary"]["conflict"], 0)
        cells = [
            cell
            for month in context["months"]
            for week in month["weeks"]
            for cell in week
            if cell and cell["date"] == self.start
        ]
        self.assertFalse(cells[0]["is_conflict"])
        self.assertIsNone(cells[0]["conflict_with"])
        self.assertIn("0.5", cells[0]["detail"])
        self.assertFalse(
            AttendanceSummaryHours.objects.filter(employee_id=self.employee).exists()
        )

    def detail(self, metric):
        return self.client.get(
            reverse("attendance-monthly-summary-detail"),
            {
                "employee_id": self.employee.pk,
                "from_date": str(self.start),
                "to_date": str(self.end),
                "metric": metric,
            },
            HTTP_HX_REQUEST="true",
        )

    def test_half_day_absence_appears_in_attendance_details(self):
        self.fractional_leave(self.paid)
        self.fill_remaining_days()
        self.login_hr()
        response = self.detail("absent")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["records"][0]["days"], 0.5)
        self.assertContains(response, "0.5 day(s)")

    def test_half_day_work_and_leave_are_not_listed_as_conflict(self):
        self.fractional_leave(self.paid)
        self.half_attendance()
        self.login_hr()
        response = self.detail("conflict")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["records"], [])

    def test_custom_payment_type_appears_in_paid_not_unpaid_details(self):
        self.fractional_leave(self.custom_type(50))
        self.login_hr()
        paid = self.detail("paid_leave")
        unpaid = self.detail("unpaid_leave")
        self.assertContains(paid, "Partially Paid Handoff")
        self.assertNotContains(unpaid, "Partially Paid Handoff")

    def test_both_half_day_choices_create_valid_work_records(self):
        for offset, half in enumerate(("first_half", "second_half")):
            day = self.start + timedelta(days=offset)
            self.fractional_leave(self.paid, day=day, half=half)
            record = WorkRecords.objects.get(employee_id=self.employee, date=day)
            self.assertEqual(record.day_percentage, 0.5)
            self.assertEqual(record.work_record_type, "CONF")
            self.assertLessEqual(len(record.message), 30)

    def test_monthly_fallback_keeps_unpaid_and_custom_half_fractions(self):
        self.contract.wage_type = "monthly"
        self.contract.wage = 3100
        self.contract.save()
        baseline = payroll_calculation(self.employee, self.start, self.end)["net_pay"]
        day_rate = get_daily_salary(3100, self.start)["day_wage"]
        self.fractional_leave(self.unpaid)
        self.fractional_leave(self.custom_type(50), day=self.end)
        result = payroll_calculation(self.employee, self.start, self.end)
        self.assertAlmostEqual(result["loss_of_pay"], day_rate * 0.75, places=2)
        self.assertAlmostEqual(result["net_pay"], baseline - day_rate * 0.75, places=2)
        self.assertEqual(result["unpaid_days"], 0.5)
        self.assertEqual(result["partial_pay_days"], 0.5)

    def test_custom_zero_and_full_percentage_are_not_double_charged(self):
        leave_type = self.custom_type(0)
        self.fractional_leave(leave_type, half="full_day")
        self.fill_remaining_days()
        for percentage, expected_pay in ((0, 300), (100, 400)):
            with self.subTest(percentage=percentage):
                leave_type.payment_percentage = percentage
                leave_type.save()
                result = payroll_calculation(
                    self.employee,
                    self.start,
                    self.end,
                    month_summary=self.summary(),
                )
                self.assertEqual(result["net_pay"], expected_pay)

    def test_nonapproved_custom_half_day_has_no_leave_deduction(self):
        request = self.fractional_leave(self.custom_type(50))
        for status in ("requested", "rejected"):
            with self.subTest(status=status):
                request.status = status
                request.save()
                data = get_leaves(self.employee, self.start, self.end)
                self.assertEqual(data["partial_pay_days"], 0)
                self.assertEqual(data["custom_leave_units"], [])
                self.assertEqual(self.summary()["paid_leave"], 0)

    def test_conflict_hold_does_not_charge_custom_leave_again(self):
        self.fractional_leave(self.paid)
        self.attendance(self.start)  # Full attendance overlaps leave: needs review.
        self.fractional_leave(self.custom_type(50), day=self.end, half="full_day")
        for wage_type, wage in (("daily", 100), ("monthly", 400)):
            with self.subTest(wage_type=wage_type):
                self.contract.wage_type = wage_type
                self.contract.wage = wage
                self.contract.save()
                result = payroll_calculation(
                    self.employee,
                    self.start,
                    self.end,
                    month_summary=self.summary(),
                )
                self.assertEqual(result["loss_of_pay"], 400)
                self.assertEqual(result["net_pay"], 0)
                self.assertEqual(result["custom_leave_deduction"], 0)

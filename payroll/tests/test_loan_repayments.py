"""Real payroll records; no live employee data or payments are used."""

import calendar
import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings

from horilla.horilla_middlewares import _thread_locals
from horilla.testkit import (
    CompanyFilterTestMixin,
    make_company,
    make_employee,
    make_user,
)
from payroll.ghana import configure_ghana_payroll
from payroll.methods.methods import save_payslip
from payroll.methods.loans import change_installment_amount
from payroll.models.models import Contract, Deduction, LoanAccount, Payslip
from payroll.scheduler import generate_payslip
from payroll.templatetags.payrollfilters import paid_amount, balance_amount
from payroll.views.component_views import payroll_calculation


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class LoanRepaymentTests(CompanyFilterTestMixin, TestCase):
    def setUp(self):
        self.clear_company_context()
        _thread_locals.request = None
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.company = make_company("Loan tests")
        self.employee = make_employee(
            company=self.company, email="loan@test.horilla", user=make_user("loan-test")
        )
        config = configure_ghana_payroll(self.company)
        contract = Contract._base_manager.get(employee_id=self.employee)
        contract.filing_status = config["filing_status"]
        contract.set_salary_structure(config["salary_structure"])
        contract.contract_start_date = date(2026, 1, 1)
        contract.contract_status = "active"
        contract.pay_frequency = "monthly"
        contract.wage = 6000
        contract.save()

    def loan(self, **overrides):
        data = dict(
            title=f"Loan {LoanAccount._base_manager.count()}",
            employee_id=self.employee,
            loan_amount=600,
            installments=3,
            provided_date=date(2026, 9, 1),
            installment_start_date=date(2026, 9, 30),
            disbursed_externally=True,
        )
        data.update(overrides)
        return LoanAccount.objects.create(**data)

    def calculate(self, month=9, start=None, end=None):
        start = start or date(2026, month, 1)
        end = end or date(2026, month, calendar.monthrange(2026, month)[1])
        days = (end - start).days + 1
        return payroll_calculation(
            self.employee,
            start,
            end,
            month_summary={"present": days, "pay_period_days": days},
        )

    def save_result(self, result, status="draft"):
        return save_payslip(
            employee=self.employee,
            start_date=result["start_date"],
            end_date=result["end_date"],
            status=status,
            contract_wage=result["contract_wage"],
            basic_pay=result["basic_pay"],
            gross_pay=result["gross_pay"],
            deduction=result["total_deductions"],
            net_pay=result["net_pay"],
            pay_data=json.loads(result["json_data"]),
            installments=result["installments"],
        )

    def test_first_save_builds_schedule_for_loans_advances_and_fines(self):
        for kind in ("loan", "advanced_salary", "fine"):
            with self.subTest(kind=kind):
                loan = self.loan(type=kind, disbursed_externally=False)
                self.assertEqual(loan.deduction_ids.count(), 3)
                self.assertEqual(loan.installment_amount, 200)
                self.assertFalse(loan.deduction_ids.filter(is_pretax=True).exists())
                if kind == "fine":
                    self.assertIsNone(loan.allowance_id)
                else:
                    self.assertFalse(loan.allowance_id.is_taxable)
                    self.assertEqual(loan.allowance_id.amount, 600)

    def test_schedule_rounds_exactly_and_preserves_month_end_anchor(self):
        loan = self.loan(
            loan_amount=100,
            provided_date=date(2026, 1, 1),
            installment_start_date=date(2026, 1, 31),
        )
        deductions = list(loan.deduction_ids.order_by("one_time_date"))
        self.assertEqual([d.amount for d in deductions], [33.33, 33.33, 33.34])
        self.assertEqual(
            [d.one_time_date for d in deductions],
            [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)],
        )
        self.assertEqual(
            sum(Decimal(str(d.amount)) for d in deductions), Decimal("100")
        )

    def test_external_advance_reduces_take_home_without_changing_tax(self):
        before = self.calculate()
        loan = self.loan(type="advanced_salary")
        after = self.calculate()
        self.assertIsNone(loan.allowance_id)
        self.assertEqual(after["gross_pay"], before["gross_pay"])
        self.assertEqual(after["federal_tax"], before["federal_tax"])
        self.assertEqual(after["net_pay"], before["net_pay"] - 200)

    def test_payroll_payout_is_not_taxed_or_repeated_on_another_slip(self):
        before = self.calculate()
        self.loan(disbursed_externally=False)
        result = self.calculate()
        self.assertEqual(result["federal_tax"], before["federal_tax"])
        self.assertEqual(result["net_pay"], before["net_pay"] + 600 - 200)
        slip = self.save_result(result)
        self.assertEqual(self.save_result(self.calculate()).pk, slip.pk)
        overlapping = self.calculate(start=date(2026, 9, 1), end=date(2026, 9, 15))
        self.assertFalse(overlapping["allowances"])

    def test_draft_reserves_but_only_paid_slip_counts_as_repayment(self):
        loan = self.loan()
        slip = self.save_result(self.calculate())
        deductions = list(loan.deduction_ids.all())
        self.assertEqual(loan.installment_paid(), 0)
        self.assertEqual(paid_amount(deductions), 0)
        self.assertEqual(balance_amount(600, deductions), 600)
        slip.status = "confirmed"
        slip.save(update_fields=["status"])
        self.assertEqual(loan.installment_paid(), 0)
        slip.status = "paid"
        slip.save(update_fields=["status"])
        self.assertEqual(loan.installment_paid(), 1)
        self.assertEqual(loan.paid_amount(), 200)

    def test_completed_loan_is_settled_and_save_cannot_restart_schedule(self):
        loan = self.loan(installments=1)
        ids = set(loan.deduction_ids.values_list("pk", flat=True))
        slip = self.save_result(self.calculate(), status="paid")
        loan.refresh_from_db()
        self.assertTrue(loan.settled)
        self.assertEqual(loan.installment_ratio(), 100)
        settled_at = loan.settled_date
        loan.description = "Repaid"
        loan.save()
        self.assertEqual(set(loan.deduction_ids.values_list("pk", flat=True)), ids)
        self.assertEqual(loan.settled_date, settled_at)
        self.assertFalse(self.calculate(month=10)["installments"].exists())
        with self.assertRaises(ValidationError), transaction.atomic():
            slip.installment_ids.clear()

    def test_arrears_are_collected_once_and_multi_installment_slip_counts_each(self):
        loan = self.loan()
        result = self.calculate(month=10)
        self.assertEqual(result["installments"].count(), 2)
        self.assertEqual(sum(d["amount"] for d in result["post_tax_deductions"]), 400)
        self.save_result(result, status="paid")
        self.assertEqual(loan.installment_paid(), 2)
        self.assertEqual(loan.paid_amount(), 400)
        self.assertEqual(self.calculate(month=11)["installments"].count(), 1)

    def test_overlapping_period_cannot_claim_reserved_installment(self):
        self.loan()
        self.save_result(self.calculate())
        result = self.calculate(start=date(2026, 9, 15), end=date(2026, 9, 30))
        self.assertFalse(result["installments"].exists())
        self.assertFalse(result["post_tax_deductions"])

    def test_stale_calculation_is_rejected_after_another_slip_reserves_it(self):
        self.loan()
        stale = self.calculate(start=date(2026, 9, 15), end=date(2026, 9, 30))
        self.save_result(self.calculate())
        with self.assertRaisesMessage(ValidationError, "another payslip"):
            self.save_result(stale)
        self.assertEqual(Payslip.objects.count(), 1)

    def test_deleted_draft_releases_installment_for_later_payroll(self):
        self.loan()
        self.save_result(self.calculate()).delete()
        self.assertEqual(self.calculate(month=10)["installments"].count(), 2)

    def test_zero_salary_does_not_consume_installment(self):
        self.loan()
        contract = Contract._base_manager.get(employee_id=self.employee)
        contract.wage = 0
        contract.save()
        with self.assertRaisesMessage(ValidationError, "exceed available pay"):
            self.calculate()
        self.assertEqual(Payslip.objects.count(), 0)

    def test_used_loan_financial_terms_and_deletion_are_protected(self):
        loan = self.loan()
        self.save_result(self.calculate())
        loan.loan_amount = 900
        with self.assertRaises(ValidationError):
            loan.save()
        loan.refresh_from_db()
        with self.assertRaises(ProtectedError):
            loan.delete()
        self.assertEqual(loan.deduction_ids.count(), 3)

    def test_reserved_deduction_cannot_be_edited_or_deleted_directly(self):
        loan = self.loan()
        slip = self.save_result(self.calculate())
        deduction = slip.installment_ids.get()
        deduction.amount = 1
        with self.assertRaisesMessage(ValidationError, "cannot be changed"):
            deduction.save()
        with self.assertRaises(ProtectedError), transaction.atomic():
            Deduction.objects.filter(pk=deduction.pk).delete()
        self.assertEqual(loan.deduction_ids.count(), 3)

    def test_negative_or_nonfinite_amounts_and_zero_installments_are_rejected(self):
        for data in (
            {"loan_amount": -1},
            {"loan_amount": float("nan")},
            {"loan_amount": 1.001},
            {"installments": 0},
        ):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                self.loan(**data)

    def test_edit_redistributes_unreserved_balance_exactly(self):
        loan = self.loan(loan_amount=100)
        first = loan.deduction_ids.order_by("one_time_date").first()
        change_installment_amount(loan, first.pk, "20.01")
        self.assertEqual(
            list(
                loan.deduction_ids.order_by("one_time_date").values_list(
                    "amount", flat=True
                )
            ),
            [20.01, 40, 39.99],
        )
        loan.refresh_from_db()
        ids = set(loan.deduction_ids.values_list("pk", flat=True))
        loan.description = "Edited schedule"
        loan.save()
        self.assertEqual(set(loan.deduction_ids.values_list("pk", flat=True)), ids)

    def test_deferring_an_installment_does_not_mark_zero_payment_as_paid(self):
        loan = self.loan(installments=1)
        first = loan.deduction_ids.get()
        change_installment_amount(loan, first.pk, "0")
        new = loan.deduction_ids.get()
        self.assertEqual(new.one_time_date, date(2026, 10, 30))
        self.assertEqual(new.amount, 600)
        self.assertFalse(self.calculate()["installments"].exists())

    def test_edit_cannot_change_any_later_reserved_installment(self):
        loan = self.loan()
        first = loan.deduction_ids.order_by("one_time_date").first()
        self.save_result(self.calculate(month=10))
        with self.assertRaisesMessage(ValidationError, "already included in payroll"):
            change_installment_amount(loan, first.pk, "100")

    def test_stale_calculation_rejected_after_schedule_changes(self):
        loan = self.loan()
        result = self.calculate()
        first = loan.deduction_ids.order_by("one_time_date").first()
        change_installment_amount(loan, first.pk, "100")
        with self.assertRaisesMessage(ValidationError, "amount changed"):
            self.save_result(result)

    def test_invalid_edit_leaves_schedule_unchanged(self):
        loan = self.loan()
        first = loan.deduction_ids.order_by("one_time_date").first()
        for amount in ("-1", "nan", "inf", "600.01", "1.001"):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                change_installment_amount(loan, first.pk, amount)
        self.assertEqual(sum(loan.deduction_ids.values_list("amount", flat=True)), 600)

    def test_manual_settlement_stops_both_payout_and_future_recovery(self):
        loan = self.loan(disbursed_externally=False)
        loan.settled = True
        loan.save()
        result = self.calculate()
        self.assertFalse(result["installments"].exists())
        self.assertFalse(result["allowances"])

    def test_legacy_duplicate_schedule_cannot_overcollect_principal(self):
        from payroll.methods.deductions import create_deductions

        loan = self.loan(installments=1)
        duplicate = create_deductions(loan, 600, date(2026, 9, 29))
        loan.deduction_ids.add(duplicate)
        with self.assertRaisesMessage(ValidationError, "outstanding balance"):
            self.save_result(self.calculate())
        self.assertEqual(Payslip.objects.count(), 0)

    def test_bulk_paid_transition_settles_loans(self):
        from django.contrib.auth.models import Permission
        from django.test import RequestFactory
        from payroll.views.views import update_payslip_status_no_id

        user = self.employee.employee_user_id
        user.user_permissions.add(Permission.objects.get(codename="change_payslip"))
        loan = self.loan(installments=1)
        slip = self.save_result(self.calculate())
        request = RequestFactory().post(
            "/payroll/payslip-status-update-no-id/",
            {"ids": json.dumps([slip.pk]), "status": "paid"},
            HTTP_HX_REQUEST="true",
        )
        request.user = user
        request.session = {}
        response = update_payslip_status_no_id(request)
        self.assertEqual(response.status_code, 200)
        loan.refresh_from_db()
        self.assertTrue(loan.settled)

    def test_migration_preserves_finalised_snapshots_and_corrects_editable_components(
        self,
    ):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection

        loan = self.loan(disbursed_externally=False)
        slip = self.save_result(self.calculate(), status="confirmed")
        saved_data = slip.pay_head_data.copy()
        scheduled = list(loan.deduction_ids.order_by("one_time_date"))
        Deduction._base_manager.filter(pk__in=[d.pk for d in scheduled]).update(
            is_pretax=True
        )
        migration = import_module("payroll.migrations.0013_loan_repayment_safeguards")
        with connection.schema_editor(atomic=False) as editor:
            migration.correct_unreserved_components(apps, editor)
        for item in scheduled:
            item.refresh_from_db()
        self.assertTrue(scheduled[0].is_pretax)
        self.assertFalse(scheduled[1].is_pretax)
        slip.refresh_from_db()
        self.assertEqual(slip.pay_head_data, saved_data)

    def test_external_disbursement_option_is_available_in_form(self):
        from payroll.forms.component_forms import LoanAccountForm

        form = LoanAccountForm(
            data={
                "title": "External advance",
                "employee_id": self.employee.pk,
                "loan_amount": "100",
                "installments": "3",
                "type": "advanced_salary",
                "provided_date": "2026-09-01",
                "installment_start_date": "2026-09-30",
                "disbursed_externally": "on",
                "description": "Already paid",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        loan = form.save()
        self.assertIsNone(loan.allowance_id)
        self.assertEqual(loan.deduction_ids.count(), 3)

    def test_scheduled_run_uses_previous_calendar_month_and_same_deductions(self):
        self.loan()
        real_calculation = payroll_calculation

        def full_attendance(employee, start, end):
            days = (end - start).days + 1
            return real_calculation(
                employee,
                start,
                end,
                month_summary={"present": days, "pay_period_days": days},
            )

        with patch(
            "payroll.scheduler.payroll_calculation", side_effect=full_attendance
        ):
            generate_payslip(date(2026, 10, 25), [self.company], False)
            generate_payslip(date(2026, 10, 25), [self.company], False)
        slip = Payslip.objects.get(employee_id=self.employee)
        self.assertEqual(
            (slip.start_date, slip.end_date), (date(2026, 9, 1), date(2026, 9, 30))
        )
        self.assertEqual(slip.status, "draft")
        self.assertEqual(slip.installment_ids.count(), 1)
        self.assertEqual(slip.net_pay, self.calculate()["net_pay"])

    def test_scheduler_does_not_overlap_an_existing_partial_period(self):
        self.save_result(self.calculate(start=date(2026, 9, 15), end=date(2026, 9, 30)))
        with patch("payroll.scheduler.payroll_calculation") as calculate:
            generate_payslip(date(2026, 10, 25), [self.company], False)
        calculate.assert_not_called()
        self.assertEqual(Payslip.objects.count(), 1)

    def test_raw_fixture_can_restore_finalised_installment_links(self):
        loan = self.loan(installments=1)
        slip = Payslip(
            employee_id=self.employee,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            status="paid",
            pay_head_data={},
        )
        slip.save_base(raw=True)
        slip.installment_ids.set(loan.deduction_ids.all())
        self.assertEqual(slip.installment_ids.count(), 1)
        loan.refresh_from_db()
        self.assertFalse(
            loan.settled
        )  # Preserve fixture state, without repayment side effects.

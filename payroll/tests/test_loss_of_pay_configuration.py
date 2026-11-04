"""Company configuration, authorization and its effect on payroll amounts."""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from employee.models import EmployeeWorkInformation
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import (
    clear_selected_company,
    make_company,
    make_employee,
    make_user,
)
from horilla.testkit.factories import make_leave_request
from leave.models import LeaveType
from payroll.forms.forms import LossOfPayPolicyForm
from payroll.methods.methods import compute_custom_leave_deduction, loss_of_pay_for_days
from payroll.models.models import Contract, LossOfPayPolicy
from payroll.views.component_views import payroll_calculation
from payroll.views.loss_of_pay import loss_of_pay_settings


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LossOfPayConfigurationTests(TestCase):
    def setUp(self):
        clear_selected_company()
        self.addCleanup(clear_selected_company)
        _thread_locals.request = None
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.company = make_company("Policy Company")
        self.other = make_company("Other Company")
        self.user = make_user("policy-admin", is_superuser=True)
        self.employee = make_employee(
            company=self.company, email=self.user.email, user=self.user
        )
        Contract.objects.filter(employee_id=self.employee).delete()
        self.contract = Contract.objects.create(
            contract_name="Policy contract",
            employee_id=self.employee,
            contract_start_date=date(2024, 1, 8),
            contract_status="active",
            wage_type="daily",
            wage=100,
            deduct_leave_from_basic_pay=True,
        )
        self.url = reverse("loss-of-pay-settings")
        self.factory = RequestFactory()

    def request(self, data=None):
        request = (
            self.factory.get(self.url)
            if data is None
            else self.factory.post(self.url, data)
        )
        request.user = self.user
        request.session = SessionStore()
        request.session.create()
        return loss_of_pay_settings(request)

    def policy(self, **fields):
        return LossOfPayPolicy._base_manager.update_or_create(
            company=self.company, defaults=fields
        )[0]

    def fresh_contract(self):
        return Contract._base_manager.get(pk=self.contract.pk)

    def test_configuration_contains_controls_and_get_does_not_save(self):
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("payroll-settings-view")), self.url)
        tabs = self.client.get(reverse("payroll-settings-tab-view"), HTTP_HX_REQUEST="true")
        self.assertContains(tabs, self.url)
        self.assertContains(tabs, "Loss of Pay")
        response = self.request()
        self.assertContains(response, 'name="enabled"')
        self.assertContains(response, 'name="fixed_amount"')
        self.assertContains(response, "Policy Company")
        self.assertFalse(LossOfPayPolicy._base_manager.exists())

    def test_save_uses_home_company_and_updates_existing_policy(self):
        set_selected_company(self.other.pk)
        response = self.request(
            {
                "enabled": "on",
                "rate_source": "fixed",
                "fixed_amount": "80",
                "company": self.other.pk,
            }
        )
        self.assertContains(response, "settings saved")
        policy = LossOfPayPolicy._base_manager.get(company=self.company)
        self.assertEqual(policy.fixed_amount, Decimal("80"))
        self.assertFalse(
            LossOfPayPolicy._base_manager.filter(company=self.other).exists()
        )
        self.request({"rate_source": "fixed", "fixed_amount": "80"})
        policy.refresh_from_db()
        self.assertFalse(policy.enabled)
        self.assertEqual(LossOfPayPolicy._base_manager.count(), 1)

    def test_view_only_permission_cannot_change_policy(self):
        self.user.is_superuser = False
        self.user.save()
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_payslipautogenerate")
        )
        self.assertContains(self.request(), "disabled")
        self.assertEqual(
            self.request({"enabled": "on", "rate_source": "calculated"}).status_code,
            403,
        )
        self.assertFalse(LossOfPayPolicy._base_manager.exists())

    def test_missing_home_company_is_rejected(self):
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee).update(
            company_id=None
        )
        self.assertEqual(self.request().status_code, 403)
        self.assertFalse(LossOfPayPolicy._base_manager.exists())

    def test_fixed_amount_validation_and_zero(self):
        for amount in ("", "-1", "NaN", "Infinity"):
            with self.subTest(amount=amount):
                form = LossOfPayPolicyForm(
                    {"enabled": "on", "rate_source": "fixed", "fixed_amount": amount}
                )
                self.assertFalse(form.is_valid())
                self.assertIn("fixed_amount", form.errors)
        self.assertTrue(
            LossOfPayPolicyForm(
                {"enabled": "on", "rate_source": "fixed", "fixed_amount": "0"}
            ).is_valid()
        )
        self.assertTrue(
            LossOfPayPolicyForm({"rate_source": "fixed", "fixed_amount": ""}).is_valid()
        )
        self.request({"enabled": "on", "rate_source": "fixed", "fixed_amount": "-1"})
        self.assertFalse(LossOfPayPolicy._base_manager.exists())

    def test_company_policy_overrides_contract_and_preserves_legacy_fallback(self):
        self.contract.calculate_daily_leave_amount = False
        self.contract.deduction_for_one_leave_amount = 25
        self.contract.save()
        self.assertEqual(loss_of_pay_for_days(self.fresh_contract(), 1, 100), 25)
        self.policy(enabled=False, rate_source="fixed", fixed_amount=80)
        self.assertEqual(loss_of_pay_for_days(self.fresh_contract(), 1, 100), 0)
        self.contract.enable_loss_of_pay = False
        self.contract.save()
        for source, expected in (("fixed", 80), ("calculated", 100), ("contract", 25)):
            self.policy(enabled=True, rate_source=source, fixed_amount=80)
            self.assertEqual(
                loss_of_pay_for_days(self.fresh_contract(), 1, 100), expected
            )

    def test_policy_isolation_and_fractional_leave(self):
        self.policy(enabled=True, rate_source="fixed", fixed_amount=80)
        LossOfPayPolicy._base_manager.create(company=self.other, enabled=False)
        set_selected_company(self.other.pk)
        contract = self.fresh_contract()
        self.assertEqual(loss_of_pay_for_days(contract, 0.5, 100), 40)
        amount, breakdown = compute_custom_leave_deduction(
            {
                "custom_leave_units": [(date(2024, 1, 8), 75, 0.5)],
                "custom_leave_breakdown": [{"percentage": 75, "days": 0.5}],
            },
            contract,
            100,
        )
        self.assertEqual(amount, 10)
        self.assertEqual(breakdown[0]["deduction_amount"], 10)
        self.policy(enabled=False)
        self.assertEqual(
            compute_custom_leave_deduction(
                {
                    "custom_leave_units": [(date(2024, 1, 8), 75, 0.5)],
                },
                self.fresh_contract(),
                100,
            )[0],
            0,
        )

    def test_daily_monthly_and_separate_deduction_obey_saved_changes(self):
        for wage_type, wage in (("daily", 100), ("monthly", 400)):
            for from_basic in (True, False):
                self.contract.wage_type = wage_type
                self.contract.wage = wage
                self.contract.deduct_leave_from_basic_pay = from_basic
                self.contract.save()
                for enabled, source, expected in (
                    (True, "fixed", 320),
                    (False, "fixed", 400),
                    (True, "calculated", 300),
                ):
                    with self.subTest(
                        wage_type=wage_type,
                        from_basic=from_basic,
                        enabled=enabled,
                        source=source,
                    ):
                        self.policy(
                            enabled=enabled, rate_source=source, fixed_amount=80
                        )
                        result = payroll_calculation(
                            self.employee,
                            date(2024, 1, 8),
                            date(2024, 1, 11),
                            month_summary={
                                "present": 3,
                                "unpaid_leave": 1,
                                "pay_period_days": 4,
                                "custom_leave_data": {},
                            },
                        )
                        self.assertEqual(result["net_pay"], expected)
                        self.assertEqual(result["unpaid_days"], 1)

    def test_standard_calculation_uses_company_policy_for_approved_leave(self):
        leave_type = LeaveType.objects.create(
            name="Policy unpaid",
            payment="unpaid",
            payment_type="unpaid",
            total_days=20,
        )
        make_leave_request(
            employee=self.employee,
            leave_type=leave_type,
            start_date=date(2024, 1, 9),
            end_date=date(2024, 1, 9),
        )
        for wage_type, wage in (("daily", 100), ("monthly", 400)):
            self.contract.wage_type = wage_type
            self.contract.wage = wage
            self.contract.save()
            for enabled, expected in ((True, 80), (False, 0)):
                with self.subTest(wage_type=wage_type, enabled=enabled):
                    self.policy(enabled=enabled, rate_source="fixed", fixed_amount=80)
                    result = payroll_calculation(
                        self.employee, date(2024, 1, 8), date(2024, 1, 11)
                    )
                    self.assertEqual(result["loss_of_pay"], expected)

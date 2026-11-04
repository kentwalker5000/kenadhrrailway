"""Top-earner totals include estimates without crossing company boundaries."""

import json
from datetime import date
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from employee.models import Employee
from horilla.horilla_middlewares import _thread_locals
from horilla.testkit import (
    CompanyFilterTestMixin,
    make_company,
    make_employee,
    make_user,
)
from payroll.dashboard import payroll_top_earners
from payroll.models.models import Payslip


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class TopEarnersDashboardTests(CompanyFilterTestMixin, TestCase):
    def setUp(self):
        self.clear_company_context()
        _thread_locals.request = None
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.company = make_company("Earners company")
        self.other_company = make_company("Other company")
        self.user = make_user("earners-admin", is_superuser=True)
        self.first = make_employee(company=self.company, email="earner1@example.test")
        self.second = make_employee(company=self.company, email="earner2@example.test")
        self.other = make_employee(
            company=self.other_company, email="earner3@example.test"
        )
        self.factory = RequestFactory()
        self.url = reverse("payroll-dashboard-earners")

    def slip(self, employee, day, net, status):
        return Payslip.objects.create(
            employee_id=employee,
            start_date=date(2024, 1, day),
            end_date=date(2024, 1, day),
            pay_head_data={},
            net_pay=net,
            gross_pay=net + 10,
            status=status,
        )

    def request(self, **params):
        request = self.factory.get(self.url, params)
        request.user = self.user
        return payroll_top_earners(request)

    def test_sums_and_ranks_draft_review_and_final_payslips(self):
        self.slip(self.first, 1, 100, "paid")
        self.slip(self.first, 2, 90, "draft")
        self.slip(self.second, 1, 150, "confirmed")
        self.slip(self.second, 2, 75, "review_ongoing")
        self.slip(self.other, 1, 10000, "paid")
        self.set_company_context(self.company.pk)
        data = json.loads(
            self.request(from_date="2024-01-01", to_date="2024-01-31").content
        )
        self.assertEqual(
            [item["id"] for item in data["earners"]], [self.second.pk, self.first.pk]
        )
        self.assertEqual([item["net"] for item in data["earners"]], [225, 190])
        self.assertEqual([item["gross"] for item in data["earners"]], [245, 210])
        self.assertTrue(all(item["estimated"] for item in data["earners"]))
        self.assertEqual(data["month"], "January 2024")

    def test_final_only_is_not_estimated_and_period_is_respected(self):
        self.slip(self.first, 1, 100, "confirmed")
        self.slip(self.first, 20, 80, "draft")
        self.set_company_context(self.company.pk)
        data = json.loads(
            self.request(from_date="2024-01-01", to_date="2024-01-10").content
        )
        self.assertEqual(data["earners"][0]["net"], 100)
        self.assertFalse(data["earners"][0]["estimated"])
        empty = json.loads(
            self.request(from_date="2024-02-01", to_date="2024-02-29").content
        )
        self.assertEqual(empty["earners"], [])

    def test_errors_are_not_reported_as_an_empty_result(self):
        self.slip(self.first, 1, 100, "draft")
        self.set_company_context(self.company.pk)
        with patch.object(
            Employee, "get_avatar", side_effect=RuntimeError("storage unavailable")
        ):
            with self.assertRaises(RuntimeError):
                self.request(from_date="2024-01-01", to_date="2024-01-31")

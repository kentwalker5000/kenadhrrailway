"""Permission and tenancy checks for deleting employee mail logs."""

from django.test import TestCase
from django.urls import reverse

from base.models import EmailLog
from horilla.testkit import CompanyFilterTestMixin, make_company, make_employee, make_user


class MailLogDeletionTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Mail Log Company")
        cls.manager_user = make_user("mail-log-manager", is_superuser=True)
        cls.manager = make_employee(
            company=cls.company,
            user=cls.manager_user,
            email="manager@example.test",
        )
        cls.employee = make_employee(
            company=cls.company,
            email="employee@example.test",
        )
        cls.other_employee = make_employee(
            company=cls.company,
            email="other@example.test",
        )
        cls.log = EmailLog.objects.create(
            subject="Staff update",
            body="A mail log entry",
            from_email="hr@example.test",
            to=cls.employee.email,
            status="sent",
            company_id=cls.company,
        )
        cls.other_log = EmailLog.objects.create(
            subject="Other staff update",
            body="A different mail log entry",
            from_email="hr@example.test",
            to=cls.other_employee.email,
            status="sent",
            company_id=cls.company,
        )

    def setUp(self):
        self.set_company_context(str(self.company.pk))
        self.client.force_login(self.manager_user)

    @property
    def delete_url(self):
        return reverse("individual-email-log-delete")

    def test_manager_can_delete_the_selected_employees_mail_log(self):
        response = self.client.post(
            self.delete_url,
            {"employee_id": self.employee.pk, "log_id": self.log.pk},
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(EmailLog._base_manager.filter(pk=self.log.pk).exists())

    def test_cannot_delete_a_log_that_belongs_to_another_employee(self):
        response = self.client.post(
            self.delete_url,
            {"employee_id": self.employee.pk, "log_id": self.other_log.pk},
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(EmailLog._base_manager.filter(pk=self.other_log.pk).exists())

    def test_employee_without_hr_access_cannot_delete_a_mail_log(self):
        user = make_user("mail-log-employee")
        employee = make_employee(
            company=self.company,
            user=user,
            email="self-service@example.test",
        )
        log = EmailLog.objects.create(
            subject="Self service mail",
            body="A protected mail log entry",
            from_email="hr@example.test",
            to=employee.email,
            status="sent",
            company_id=self.company,
        )
        self.client.force_login(user)

        response = self.client.post(
            self.delete_url,
            {"employee_id": employee.pk, "log_id": log.pk},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(EmailLog._base_manager.filter(pk=log.pk).exists())

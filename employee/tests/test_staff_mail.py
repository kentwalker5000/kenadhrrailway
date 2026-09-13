"""Tests for the employee-page mail workflow."""

from inspect import unwrap
from unittest.mock import ANY, patch

from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from base.models import DynamicEmailConfiguration, HorillaMailTemplate
from employee.models import Employee
from employee.not_in_out_dashboard import send_mail_to_employee
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user


class StaffMailTests(TestCase):
    """The UI must report the same outcome that the mail backend receives."""

    @classmethod
    def setUpTestData(cls):
        cls.company = make_company()
        cls.sender_user = make_user("mail-manager", is_superuser=True)
        cls.sender = make_employee(
            company=cls.company,
            email="manager@example.test",
            first_name="Mail",
            last_name="Manager",
            user=cls.sender_user,
        )
        cls.recipient = make_employee(
            company=cls.company,
            email="recipient@example.test",
            first_name="Mail",
            last_name="Recipient",
        )
        cls.attachment_template = HorillaMailTemplate.objects.create(
            title="Mail attachment", body="<p>Attachment body</p>", company_id=cls.company
        )
        cls.email_configuration = DynamicEmailConfiguration.objects.create(
            company_id=cls.company,
            host="smtp.example.test",
            port=465,
            username="mailer@example.test",
            password="synthetic-only-password",
            from_email="mailer@example.test",
            display_name="KenadHr",
            use_ssl=True,
            use_tls=False,
            fail_silently=False,
            is_primary=True,
        )

    def setUp(self):
        set_selected_company(self.company.pk)
        self.factory = RequestFactory()
        self.send_view = unwrap(send_mail_to_employee)

    def tearDown(self):
        set_selected_company(None)

    def request(self, **data):
        request = self.factory.post(
            "/employee/send-mail/", data, HTTP_REFERER="/employee/employee-view/"
        )
        SessionMiddleware(lambda current_request: None).process_request(request)
        request.session.save()
        request.user = self.sender_user
        request._messages = FallbackStorage(request)
        return request

    @staticmethod
    def messages_for(request):
        return [str(message) for message in get_messages(request)]

    def test_sends_valid_mail_and_reports_success(self):
        request = self.request(
            id=str(self.recipient.pk), subject="Hello", body="<p>Test message</p>"
        )

        with patch("employee.not_in_out_dashboard.EmailMessage") as email_class:
            email_class.return_value.send.return_value = 1
            self.send_view(request)

        email_class.assert_called_once_with(
            subject="Hello",
            body="<p>Test message</p>",
            from_email="KenadHr <mailer@example.test>",
            to=["recipient@example.test"],
            reply_to=["mailer@example.test"],
            connection=ANY,
        )
        email_class.return_value.send.assert_called_once()
        self.assertIn("Mail sent to Mail Recipient.", self.messages_for(request))

    def test_rejects_invalid_recipient_before_attempting_delivery(self):
        Employee._base_manager.filter(pk=self.recipient.pk).update(email="not-an-email")
        request = self.request(
            id=str(self.recipient.pk), subject="Hello", body="<p>Test message</p>"
        )

        with patch("employee.not_in_out_dashboard.EmailMessage.send") as send:
            self.send_view(request)

        send.assert_not_called()
        self.assertIn(
            "Set a valid email address for: Mail Recipient.", self.messages_for(request)
        )

    def test_does_not_send_when_requested_pdf_attachment_cannot_be_generated(self):
        request = self.request(
            id=str(self.recipient.pk),
            subject="Hello",
            body="<p>Test message</p>",
            template_attachments=[str(self.attachment_template.pk)],
        )

        with (
            patch(
                "employee.not_in_out_dashboard.generate_pdf",
                return_value=HttpResponse(status=500),
            ),
            patch("employee.not_in_out_dashboard.EmailMessage.send") as send,
        ):
            self.send_view(request)

        send.assert_not_called()
        self.assertIn(
            "The requested PDF attachment could not be generated. The email was not sent.",
            self.messages_for(request),
        )

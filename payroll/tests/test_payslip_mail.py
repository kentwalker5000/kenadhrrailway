"""Payslip delivery uses synthetic records and a mocked SMTP transport only."""

import smtplib
import io
import os
from collections import defaultdict
from datetime import date
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from django.contrib import messages
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from pypdf import PdfReader
from rest_framework.test import APIRequestFactory, force_authenticate

from base.models import DynamicEmailConfiguration, EmailLog
from employee.models import EmployeeWorkInformation
from horilla.horilla_middlewares import _thread_locals, get_selected_company
from horilla.testkit import CompanyFilterTestMixin, make_company, make_employee, make_user
from payroll.models.models import Payslip
from payroll.threadings.mail import MailSendThread


@override_settings(WHITE_LABELLING=False)
class PayslipMailTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Payslip Mail Co")
        cls.other_company = make_company("Other Payslip Mail Co")
        cls.user = make_user("payslip-mail-admin", is_superuser=True)
        make_employee(company=cls.company, user=cls.user, email="hr-admin@example.com")
        cls.employee_a = make_employee(company=cls.company, email="personal-a@example.com")
        cls.employee_b = make_employee(company=cls.company, email="personal-b@example.com")
        cls.other_employee = make_employee(company=cls.other_company, email="other@example.com")
        EmployeeWorkInformation._base_manager.filter(employee_id=cls.employee_a).update(
            email="work-a@example.com"
        )
        cls.slip_a = cls.make_slip(cls.employee_a, 1)
        cls.slip_a2 = cls.make_slip(cls.employee_a, 2)
        cls.slip_b = cls.make_slip(cls.employee_b, 1)
        cls.other_slip = cls.make_slip(cls.other_employee, 1)
        config = dict(
            host="smtp.example.com", port=465, username="payroll@example.com",
            password="synthetic-only-password", from_email="payroll@example.com",
            display_name="KenadHr Payroll", use_ssl=True, use_tls=False,
            timeout=30, fail_silently=False,
        )
        cls.config = DynamicEmailConfiguration.objects.create(company_id=cls.company, **config)
        cls.other_config = DynamicEmailConfiguration.objects.create(company_id=cls.other_company, **config)

    @classmethod
    def make_slip(cls, employee, month):
        return Payslip.objects.create(
            employee_id=employee, start_date=date(2026, month, 1),
            end_date=date(2026, month, 28), pay_head_data={"synthetic": True},
            basic_pay=100, gross_pay=100, net_pay=100, deduction=0,
        )

    def setUp(self):
        self.clear_company_context()
        _thread_locals.request = None
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.request = RequestFactory().post("/payroll/send-slip/")
        self.request.user = self.user
        self.request.session = {}
        self.pdf = self.start_patch(
            "payroll.threadings.mail.payslip_pdf",
            return_value=HttpResponse(b"%PDF-1.4\nSynthetic fixture", content_type="application/pdf"),
        )
        self.mail_body = self.start_patch(
            "payroll.threadings.mail.render_to_string", return_value="<p>Synthetic payslip</p>"
        )
        # Exercise the actual ConfiguredEmailBackend logging without opening SMTP.
        self.smtp = self.start_patch(
            "django.core.mail.backends.smtp.EmailBackend.send_messages", autospec=True, return_value=1
        )
        # Most worker tests run synchronously in TestCase's open transaction.
        self.start_patch("payroll.threadings.mail.close_old_connections")
        self.start_patch("payroll.threadings.mail.connections.close_all")

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def worker(self, slips):
        records = defaultdict(lambda: {"instances": [], "count": 0})
        for slip in slips:
            record = records[slip.employee_id_id]
            record["employee_id"] = slip.employee_id
            record["instances"].append(slip)
            record["count"] += 1
        return MailSendThread(
            self.request, records, [slip.pk for slip in slips],
            company_id=self.company.pk, configuration=self.config,
        )

    def assert_sent(self, slip, expected):
        slip.refresh_from_db()
        self.assertEqual(slip.sent_to_employee, expected)

    def test_success_uses_configured_sender_connection_and_work_email(self):
        worker = self.worker([self.slip_a, self.slip_a2])
        worker.run()
        self.smtp.assert_called_once()
        email = self.smtp.call_args.args[1][0]
        self.assertEqual(email.from_email, "KenadHr Payroll <payroll@example.com>")
        self.assertEqual(email.to, ["work-a@example.com"])
        self.assertEqual(email.reply_to, ["payroll@example.com"])
        self.assertEqual(email.connection.configuration.pk, self.config.pk)
        self.assertFalse(email.connection.fail_silently)
        self.assertEqual(len(email.attachments), 2)
        self.assertTrue(all(item[1].startswith(b"%PDF-") for item in email.attachments))
        self.assert_sent(self.slip_a, True)
        self.assert_sent(self.slip_a2, True)
        self.assert_sent(self.slip_b, False)
        self.assert_sent(self.other_slip, False)
        self.assertEqual(worker.accepted_count, 2)
        self.assertEqual(EmailLog.objects.get().company_id_id, self.company.pk)

    def test_zero_result_does_not_mark_any_payslip_as_sent(self):
        self.smtp.return_value = 0
        worker = self.worker([self.slip_a, self.slip_b])
        worker.run()
        self.assert_sent(self.slip_a, False)
        self.assert_sent(self.slip_b, False)
        self.assertEqual(worker.failed_count, 2)

    def test_real_pdf_can_be_attached_without_wkhtmltopdf(self):
        from django.template.loader import render_to_string
        from payroll.models.tax_models import PayrollSettings
        from payroll.views.views import payslip_pdf

        PayrollSettings.objects.create(company_id=self.company, currency_symbol="GHS")
        data = {
            "start_date": "2026-01-01", "end_date": "2026-01-28",
            "basic_pay": 100, "gross_pay": 120, "net_pay": 115,
            "paid_days": 28, "unpaid_days": 0, "loss_of_pay": 0,
            "total_deductions": 5, "federal_tax": 5,
            "allowances": [{"title": "Transport", "amount": 20}],
        }
        for key in ("basic_pay_deductions", "gross_pay_deductions", "pretax_deductions",
                    "post_tax_deductions", "tax_deductions", "net_deductions"):
            data[key] = []
        Payslip._base_manager.filter(pk=self.slip_a.pk).update(pay_head_data=data)
        responses = []

        def real_pdf(request, pk):
            response = payslip_pdf(request, pk)
            responses.append(response)
            return response

        self.pdf.side_effect = real_pdf
        body_errors = []

        def real_body(*args, **kwargs):
            try:
                return render_to_string(*args, **kwargs)
            except Exception as error:
                body_errors.append(str(error))
                raise

        self.mail_body.side_effect = real_body
        with patch("socket.create_connection", side_effect=AssertionError("PDF must not fetch network assets")):
            self.worker([self.slip_a]).run()
        self.assertEqual(responses[0].status_code, 200, responses[0].content[:300])
        self.assertEqual(self.smtp.call_count, 1, body_errors)
        email = self.smtp.call_args.args[1][0]
        self.assertIn("Your Payslips are ready", email.body)
        self.assertIn("kenadhr-wordmark.png", email.body)
        content = email.attachments[0][1]
        reader = PdfReader(io.BytesIO(content))
        self.assertEqual(len(reader.pages), 1)
        text = " ".join(page.extract_text() for page in reader.pages)
        self.assertIn("Payslip Mail Co", text)
        self.assertIn("Transport", text)
        self.assertIn("115.00", text)
        # Optional QA artifact, generated from this synthetic fixture only.
        output = os.environ.get("PAYSLIP_PDF_QA_OUTPUT")
        if output:
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

    def test_partial_batch_success_marks_only_the_accepted_employee(self):
        self.smtp.side_effect = [1, 0]
        self.worker([self.slip_a, self.slip_b]).run()
        self.assert_sent(self.slip_a, True)
        self.assert_sent(self.slip_b, False)

    def test_authentication_error_does_not_abort_other_employees_or_mark_failed_slips(self):
        self.smtp.side_effect = [smtplib.SMTPAuthenticationError(535, b"synthetic failure"), 1]
        self.worker([self.slip_a, self.slip_b]).run()
        self.assert_sent(self.slip_a, False)
        self.assert_sent(self.slip_b, True)

    def test_error_response_cannot_be_mailed_as_a_pdf(self):
        self.pdf.return_value = HttpResponse("PDF generation error", status=500)
        self.worker([self.slip_a]).run()
        self.smtp.assert_not_called()
        self.assert_sent(self.slip_a, False)

    def test_html_disguised_as_a_pdf_is_not_sent(self):
        self.pdf.return_value = HttpResponse(b"<html>Permission denied</html>", content_type="application/pdf")
        self.worker([self.slip_a]).run()
        self.smtp.assert_not_called()
        self.assert_sent(self.slip_a, False)

    def test_one_failed_attachment_stops_that_employees_whole_email(self):
        self.pdf.side_effect = [
            HttpResponse(b"%PDF-1.4\nSynthetic", content_type="application/pdf"),
            HttpResponse("error", status=500),
        ]
        self.worker([self.slip_a, self.slip_a2]).run()
        self.smtp.assert_not_called()
        self.assert_sent(self.slip_a, False)
        self.assert_sent(self.slip_a2, False)

    def test_blank_work_email_falls_back_to_personal_email(self):
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee_b).update(email=" ")
        self.worker([self.slip_b]).run()
        self.assertEqual(self.smtp.call_args.args[1][0].to, ["personal-b@example.com"])

    def test_invalid_recipient_is_not_sent(self):
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee_a).update(email="not-an-address")
        self.worker([self.slip_a]).run()
        self.smtp.assert_not_called()
        self.assert_sent(self.slip_a, False)

    def test_worker_rechecks_employee_company(self):
        worker = self.worker([self.slip_a])
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee_a).update(company_id=self.other_company)
        worker.run()
        self.smtp.assert_not_called()
        self.assert_sent(self.slip_a, False)

    def test_missing_config_does_not_use_another_companys_primary(self):
        worker = self.worker([self.slip_a])
        DynamicEmailConfiguration._base_manager.filter(pk=self.config.pk).delete()
        DynamicEmailConfiguration._base_manager.filter(pk=self.other_config.pk).update(is_primary=True)
        worker.run()
        self.smtp.assert_not_called()
        self.assert_sent(self.slip_a, False)

    def test_get_does_not_queue_email(self):
        self.client.force_login(self.user)
        with patch("payroll.views.component_views.MailSendThread") as worker:
            response = self.client.get(reverse("send-slip"), {"id": self.slip_a.pk})
        self.assertEqual(response.status_code, 405)
        worker.assert_not_called()

    def test_valid_post_queues_the_selected_company_after_commit(self):
        self.client.force_login(self.user)
        with patch("payroll.views.component_views.MailSendThread") as worker:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("send-slip"), {"id": [self.slip_a.pk, self.slip_a.pk]})
                worker.return_value.start.assert_not_called()
            worker.return_value.start.assert_called_once()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(worker.call_args.kwargs["ids"], [self.slip_a.pk])
        self.assertEqual(worker.call_args.kwargs["company_id"], self.company.pk)
        self.assertEqual(worker.call_args.kwargs["configuration"].pk, self.config.pk)
        feedback = list(get_messages(response.wsgi_request))
        self.assertTrue(any(item.level == messages.INFO and "queued" in str(item) for item in feedback))
        self.assert_sent(self.slip_a, False)

    def test_mixed_company_selection_is_rejected_before_queueing(self):
        self.client.force_login(self.user)
        with patch("payroll.views.component_views.MailSendThread") as worker:
            response = self.client.post(reverse("send-slip"), {"id": [self.slip_a.pk, self.other_slip.pk]})
        self.assertEqual(response.status_code, 404)
        worker.assert_not_called()

    def test_htmx_post_accepts_query_ids_with_valid_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        token = "a" * 32
        client.cookies["csrftoken"] = token
        with patch("payroll.views.component_views.MailSendThread") as worker:
            with self.captureOnCommitCallbacks(execute=True):
                response = client.post(
                    f"{reverse('send-slip')}?id={self.slip_a.pk}",
                    HTTP_HX_REQUEST="true", HTTP_X_CSRFTOKEN=token,
                )
        self.assertEqual(response.status_code, 302)
        worker.return_value.start.assert_called_once()

    def test_missing_company_mail_configuration_does_not_queue(self):
        self.client.force_login(self.user)
        DynamicEmailConfiguration._base_manager.filter(pk=self.config.pk).delete()
        DynamicEmailConfiguration._base_manager.filter(pk=self.other_config.pk).update(is_primary=True)
        with patch("payroll.views.component_views.MailSendThread") as worker:
            response = self.client.post(reverse("send-slip"), {"id": self.slip_a.pk})
        self.assertEqual(response.status_code, 302)
        worker.assert_not_called()
        self.assertTrue(any(
            item.level == messages.ERROR for item in get_messages(response.wsgi_request)
        ))

    def test_empty_or_invalid_selection_does_not_queue_email(self):
        self.client.force_login(self.user)
        with patch("payroll.views.component_views.MailSendThread") as worker:
            for ids in ([], ["bad"], ["0"]):
                self.assertEqual(self.client.post(reverse("send-slip"), {"id": ids}).status_code, 400)
        worker.assert_not_called()

    def test_post_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        with patch("payroll.views.component_views.MailSendThread") as worker:
            response = client.post(reverse("send-slip"), {"id": self.slip_a.pk})
        self.assertEqual(response.status_code, 403)
        worker.assert_not_called()

    def api_post(self, ids, user=None):
        from horilla_api.api_views.payroll.views import PayslipSendMailView

        request = APIRequestFactory().post("/api/payroll/payslip-send-mail/", {"id": ids}, format="json")
        force_authenticate(request, user=user or self.user)
        return PayslipSendMailView.as_view()(request)

    def test_api_queues_with_explicit_company_and_reports_queued_not_sent(self):
        with patch("horilla_api.api_views.payroll.views.MailSendThread") as worker:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.api_post([self.slip_a.pk])
                worker.return_value.start.assert_not_called()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], "queued")
        worker.return_value.start.assert_called_once()
        self.assertEqual(worker.call_args.kwargs["company_id"], self.company.pk)
        self.assertEqual(worker.call_args.kwargs["configuration"].pk, self.config.pk)

    def test_api_rejects_mixed_company_selection(self):
        with patch("horilla_api.api_views.payroll.views.MailSendThread") as worker:
            response = self.api_post([self.slip_a.pk, self.other_slip.pk])
        self.assertEqual(response.status_code, 404)
        worker.assert_not_called()

    def test_api_requires_payroll_permissions(self):
        with patch("horilla_api.api_views.payroll.views.MailSendThread") as worker:
            response = self.api_post([self.slip_a.pk], user=self.employee_a.employee_user_id)
        self.assertEqual(response.status_code, 403)
        worker.assert_not_called()

    def test_api_rejects_invalid_selection(self):
        with patch("horilla_api.api_views.payroll.views.MailSendThread") as worker:
            for ids in ([], "1", ["bad"], [0], [True]):
                self.assertEqual(self.api_post(ids).status_code, 400)
        worker.assert_not_called()


class PayslipThreadContextTests(CompanyFilterTestMixin, SimpleTestCase):
    def test_real_thread_gets_company_context_without_leaking_into_caller(self):
        self.clear_company_context()
        _thread_locals.request = None
        request = SimpleNamespace(get_host=lambda: "testserver", is_secure=lambda: False)
        worker = MailSendThread(request, {}, [], company_id=42, configuration=SimpleNamespace(pk=1))
        observed = []
        with patch.object(worker, "_deliver", side_effect=lambda: observed.append(
            (get_selected_company(), _thread_locals.request is request)
        )), patch("payroll.threadings.mail.close_old_connections"), patch(
            "payroll.threadings.mail.connections.close_all"
        ) as close:
            worker.start()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(observed, [("42", True)])
        self.assertIsNone(get_selected_company())
        self.assertIsNone(_thread_locals.request)
        close.assert_called_once()

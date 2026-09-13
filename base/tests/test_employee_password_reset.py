"""Synthetic account recovery; SMTP is mocked and no real passwords are changed."""

import re
import smtplib
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

from base.email_redaction import REDACTED
from base.models import DynamicEmailConfiguration, EmailLog
from base.password_reset import (
    employee_reset_token, reset_employee, reset_origin, reset_request_allowed,
    send_employee_reset_link,
)
from employee.models import Employee, EmployeeWorkInformation
from horilla.horilla_middlewares import _thread_locals, get_selected_company
from horilla.testkit import CompanyFilterTestMixin, make_company, make_employee, make_user


@override_settings(
    PASSWORD_RESET_BASE_URL="https://www.kenadhr.com", PASSWORD_RESET_TIMEOUT=3600,
    WHITE_LABELLING=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class EmployeePasswordResetTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Reset Company")
        cls.other_company = make_company("Other Reset Company")
        cls.admin = make_user("reset-admin", is_superuser=True)
        make_employee(company=cls.company, user=cls.admin, email="hr@example.com")
        cls.user = make_user("reset-employee", password="Old-Test-Password-938!")
        cls.employee = make_employee(company=cls.company, user=cls.user, email="personal@example.com")
        EmployeeWorkInformation._base_manager.filter(employee_id=cls.employee).update(email="work@example.com")
        cls.colleague = make_employee(company=cls.company, email="colleague@example.com")
        cls.other_employee = make_employee(company=cls.other_company, email="other@example.com")
        config = dict(host="smtp.example.com", port=465, username="sender@example.com",
                      password="synthetic-only", from_email="sender@example.com",
                      display_name="KenadHr", use_ssl=True, use_tls=False, fail_silently=False)
        cls.config = DynamicEmailConfiguration.objects.create(company_id=cls.company, **config)
        cls.other_config = DynamicEmailConfiguration.objects.create(company_id=cls.other_company, is_primary=True, **config)

    def setUp(self):
        cache.clear()
        self.clear_company_context()
        _thread_locals.request = None
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.smtp = self.start_patch(
            "django.core.mail.backends.smtp.EmailBackend.send_messages", autospec=True, return_value=1
        )
        self.worker_start = self.start_patch("base.views.PasswordResetMailThread.start", autospec=True)
        self.start_patch("base.password_reset.close_old_connections")
        self.start_patch("base.password_reset.connections.close_all")

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def sent_message(self):
        return self.smtp.call_args.args[1][0]

    def send_link(self):
        self.assertTrue(send_employee_reset_link(reset_employee(self.user)))
        return re.search(r"https://www\.kenadhr\.com/accounts/reset/[^/\s]+/[^/\s]+/", self.sent_message().body).group()

    def public_request(self, username, path=None):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(path or reverse("forgot-password"), {"email": username})
        return response

    def test_public_flow_sets_password_once_then_signs_in_to_same_company(self):
        response = self.public_request(self.user.username)
        self.assertRedirects(response, reverse("reset-send-success"))
        self.smtp.assert_not_called()
        worker = self.worker_start.call_args.args[0]
        worker.run()
        message = self.sent_message()
        link = re.search(r"https://www\.kenadhr\.com/accounts/reset/[^/\s]+/[^/\s]+/", message.body).group()
        path = urlsplit(link).path
        old_session = Client()
        old_session.force_login(self.user)
        # Login changes last_login and invalidates the previous token. Issue a
        # fresh link after creating the session that should later be revoked.
        path = urlsplit(self.send_link()).path
        response = self.client.get(path, follow=True)
        self.assertContains(response, "Choose a new password")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])
        form_path = response.wsgi_request.path
        new_password = "New-Strong-Password-752!"
        response = self.client.post(form_path, {"new_password1": new_password, "new_password2": new_password})
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertFalse(old_session.get("/").wsgi_request.user.is_authenticated)
        invalid = self.client.get(path, follow=True)
        self.assertContains(invalid, "This reset link is no longer valid")
        self.assertNotContains(invalid, 'name="new_password1"')
        login = self.client.post(reverse("login"), {"username": self.user.username, "password": new_password})
        self.assertEqual(login.status_code, 302)
        # Company middleware binds the newly logged-in account on its next request.
        self.client.get(reverse("password_reset_complete"))
        self.assertEqual(str(self.client.session["selected_company"]), str(self.company.pk))

    def test_company_sender_registered_work_address_and_redacted_log(self):
        link = self.send_link()
        message = self.sent_message()
        self.assertEqual(message.to, ["work@example.com"])
        self.assertEqual(message.from_email, "KenadHr <sender@example.com>")
        self.assertEqual(message.reply_to, ["sender@example.com"])
        self.assertEqual(message.connection.configuration.pk, self.config.pk)
        self.assertIn("60 minutes", message.body)
        self.assertIn(link, message.alternatives[0][0])
        log = EmailLog.objects.get()
        self.assertEqual(log.company_id_id, self.company.pk)
        self.assertEqual(log.body, REDACTED)
        self.assertIsNone(get_selected_company())

    def test_blank_work_email_uses_personal_address(self):
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee).update(email=" ")
        self.send_link()
        self.assertEqual(self.sent_message().to, ["personal@example.com"])

    def test_no_fallback_to_another_company_mail_server(self):
        DynamicEmailConfiguration._base_manager.filter(pk=self.config.pk).delete()
        with self.assertRaises(ImproperlyConfigured):
            send_employee_reset_link(reset_employee(self.user))
        self.smtp.assert_not_called()

    def test_unknown_and_known_user_get_identical_public_response(self):
        known = self.public_request(self.user.username)
        unknown = self.public_request("does-not-exist")
        self.assertEqual((known.status_code, known.url), (unknown.status_code, unknown.url))
        self.assertEqual(self.worker_start.call_count, 2)
        self.worker_start.call_args.args[0].run()
        self.smtp.assert_not_called()

    def test_django_alias_uses_same_public_policy(self):
        response = self.public_request(self.user.username, reverse("password_reset"))
        self.assertEqual(response.status_code, 302)
        self.worker_start.assert_called_once()
        self.assertEqual(resolve(reverse("password_reset")).func.view_class.__name__, "HorillaPasswordResetView")

    def test_public_request_requires_csrf(self):
        response = Client(enforce_csrf_checks=True).post(reverse("forgot-password"), {"email": self.user.username})
        self.assertEqual(response.status_code, 403)
        self.worker_start.assert_not_called()

    def test_hr_action_requires_login_post_and_csrf(self):
        url = reverse("employee-reset-password")
        self.assertEqual(self.client.post(url, {"employee_id": self.employee.pk}).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(url, {"employee_id": self.employee.pk}).status_code, 403)
        self.smtp.assert_not_called()

    def test_hr_can_send_only_for_own_company(self):
        self.client.force_login(self.admin)
        url = reverse("employee-reset-password")
        self.assertEqual(self.client.post(url, {"employee_id": self.other_employee.pk}).status_code, 404)
        self.smtp.assert_not_called()
        self.assertEqual(self.client.post(url, {"employee_id": self.employee.pk}).status_code, 302)
        self.smtp.assert_called_once()
        self.assertEqual(self.sent_message().to, ["work@example.com"])

    def test_employee_cannot_send_for_unrelated_colleague(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("employee-reset-password"), {"employee_id": self.colleague.pk})
        self.assertEqual(response.status_code, 403)
        self.smtp.assert_not_called()

    def test_employee_can_request_own_reset_from_profile(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("employee-reset-password"), {"employee_id": self.employee.pk})
        self.assertEqual(response.status_code, 302)
        self.smtp.assert_called_once()

    def test_hr_zero_send_and_smtp_errors_are_not_reported_as_success(self):
        from django.contrib.messages import get_messages

        self.client.force_login(self.admin)
        for result in (0, smtplib.SMTPAuthenticationError(535, b"private server reply")):
            self.smtp.side_effect = result if isinstance(result, Exception) else None
            self.smtp.return_value = result
            response = self.client.post(reverse("employee-reset-password"), {"employee_id": self.employee.pk})
            feedback = " ".join(str(item) for item in get_messages(response.wsgi_request))
            self.assertIn("could not be sent", feedback)
            self.assertNotIn("private server reply", feedback)

    def test_inactive_user_archived_employee_and_unusable_password_get_no_email(self):
        user_model = get_user_model()
        user_model._base_manager.filter(pk=self.user.pk).update(is_active=False)
        self.assertFalse(send_employee_reset_link(reset_employee(self.user)))
        user_model._base_manager.filter(pk=self.user.pk).update(is_active=True)
        Employee._base_manager.filter(pk=self.employee.pk).update(is_active=False)
        self.assertFalse(send_employee_reset_link(reset_employee(self.user)))
        Employee._base_manager.filter(pk=self.employee.pk).update(is_active=True)
        self.user.set_unusable_password()
        self.user.save()
        self.assertFalse(send_employee_reset_link(reset_employee(self.user)))
        self.smtp.assert_not_called()

    def test_expired_link_has_a_recovery_action_and_no_password_fields(self):
        path = urlsplit(self.send_link()).path
        with patch.object(employee_reset_token, "_now", return_value=employee_reset_token._now() + timedelta(seconds=3601)):
            response = self.client.get(path, follow=True)
        self.assertContains(response, "Request a new link")
        self.assertNotContains(response, 'name="new_password1"')

    def test_password_validation_rejects_mismatch_and_weak_password(self):
        response = self.client.get(urlsplit(self.send_link()).path, follow=True)
        form_path = response.wsgi_request.path
        for first, second in (("12345678", "12345678"), ("Strong-Password-372!", "Different-Password-835!")):
            response = self.client.post(form_path, {"new_password1": first, "new_password2": second})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Old-Test-Password-938!"))

    def test_token_invalidates_when_actual_delivery_address_or_company_changes(self):
        token = employee_reset_token.make_token(self.user)
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee).update(email="new@example.com")
        self.assertFalse(employee_reset_token.check_token(self.user, token))
        token = employee_reset_token.make_token(self.user)
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee).update(company_id=self.other_company)
        self.assertFalse(employee_reset_token.check_token(self.user, token))

    def test_blocked_account_cannot_use_previously_issued_link(self):
        path = urlsplit(self.send_link()).path
        get_user_model()._base_manager.filter(pk=self.user.pk).update(is_active=False)
        self.assertContains(self.client.get(path, follow=True), "This reset link is no longer valid")

    def test_limits_are_shared_between_hr_and_public_requests(self):
        for _ in range(6):
            self.public_request(self.user.username)
        self.assertEqual(self.worker_start.call_count, 5)
        self.client.force_login(self.admin)
        self.client.post(reverse("employee-reset-password"), {"employee_id": self.employee.pk})
        self.smtp.assert_not_called()

    def test_ip_limit_covers_different_usernames_and_ignores_forwarded_header(self):
        request = RequestFactory().post("/", REMOTE_ADDR="192.0.2.10", HTTP_X_FORWARDED_FOR="spoofed")
        for index in range(20):
            self.assertTrue(reset_request_allowed(request, f"unknown-{index}"))
        self.assertFalse(reset_request_allowed(request, "unknown-21"))

    def test_origin_is_explicit_and_production_requires_https(self):
        self.assertEqual(reset_origin(), "https://www.kenadhr.com")
        for origin in ("", "http://www.kenadhr.com", "https://user:pass@example.com", "https://example.com/path", "https://example.com?next=evil"):
            with self.subTest(origin=origin), override_settings(DEBUG=False, PASSWORD_RESET_BASE_URL=origin):
                with self.assertRaises(ImproperlyConfigured):
                    reset_origin()

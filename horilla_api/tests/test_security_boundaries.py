"""Regression tests for company ownership, activation and API two-factor gates."""

from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from employee.models import EmployeeWorkInformation
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee, make_user

LOGIN = "/api/v1/auth/login/"
PROBE = "/api/v1/employee/list/employees/"
BULK = "/api/v1/employee/employee-bulk-update/"


@override_settings(
    TWO_FACTORS_AUTHENTICATION=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ApiSecurityBoundaryTests(TestCase):
    def setUp(self):
        cache.clear()
        _thread_locals.request = None
        set_selected_company(None)
        self.addCleanup(set_selected_company, None)
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.company = make_company("Security A")
        self.foreign = make_company("Security B", hq=False)
        self.user = make_user(
            "security-owner", password="test-password-123", is_superuser=True
        )
        self.employee = make_employee(
            company=self.company, email="security@test.horilla", user=self.user
        )
        self.other = make_employee(company=self.foreign, email="foreign@test.horilla")
        self.client = APIClient()

    def login(self, **fields):
        return self.client.post(
            LOGIN,
            {
                "username": self.user.username,
                "password": "test-password-123",
                **fields,
            },
            format="json",
        )

    def token(self):
        response = self.login()
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["access"]

    def bulk(self, **fields):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.token())
        return self.client.put(
            BULK, {"ids": [self.employee.pk], **fields}, format="json"
        )

    def test_company_cannot_be_reassigned_by_bulk_api(self):
        response = self.bulk(employee_work_info={"company_id": self.foreign.pk})
        self.assertEqual(response.status_code, 400, response.data)
        self.employee.employee_work_info.refresh_from_db()
        self.assertEqual(self.employee.employee_work_info.company_id, self.company)

    def test_identity_fields_are_rejected(self):
        for field in ("employee_user_id", "employee_user_id_id", "id"):
            with self.subTest(field=field):
                response = self.bulk(employee_data={field: self.other.pk})
                self.assertEqual(response.status_code, 400, response.data)

    def test_foreign_relation_is_rejected(self):
        response = self.bulk(employee_work_info={"reporting_manager_id": self.other.pk})
        self.assertEqual(response.status_code, 400, response.data)

    def test_mixed_company_update_is_atomic(self):
        response = self.bulk(
            ids=[self.employee.pk, self.other.pk], employee_data={"city": "Changed"}
        )
        self.assertEqual(response.status_code, 404, response.data)
        self.employee.refresh_from_db()
        self.assertNotEqual(self.employee.city, "Changed")

    def test_valid_personal_and_work_updates_still_work(self):
        response = self.bulk(
            employee_data={"city": "Accra"}, employee_work_info={"location": "Office"}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.city, "Accra")
        self.assertEqual(self.employee.employee_work_info.location, "Office")

    def test_empty_ids_or_non_object_fields_are_rejected(self):
        for fields in (
            {"ids": []},
            {"employee_data": []},
            {"employee_work_info": "invalid"},
        ):
            response = self.bulk(**fields)
            self.assertEqual(response.status_code, 400, response.data)

    def test_work_updates_need_work_permission(self):
        self.user.is_superuser = False
        self.user.save(update_fields=["is_superuser"])
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="employee",
                codename="change_employee",
            )
        )
        response = self.bulk(employee_work_info={"location": "Office"})
        self.assertEqual(response.status_code, 403, response.data)

    def test_pending_activation_cannot_login_or_reuse_token(self):
        token = self.token()
        self.user.is_new_employee = True
        self.user.save(update_fields=["is_new_employee"])
        self.assertEqual(self.login().status_code, 403)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(self.client.get(PROBE).status_code, 403)

    def test_disabled_company_revokes_access(self):
        token = self.token()
        self.company.is_active = False
        self.company.save(update_fields=["is_active"])
        self.assertEqual(self.login().status_code, 403)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(self.client.get(PROBE).status_code, 403)

    def test_company_change_revokes_token(self):
        token = self.token()
        _thread_locals.request = None
        set_selected_company(None)
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee).update(
            company_id=self.foreign
        )
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(self.client.get(PROBE).status_code, 403)

    @override_settings(TWO_FACTORS_AUTHENTICATION=True)
    @patch("horilla_api.mfa.send_code")
    def test_otp_is_required_single_use_and_mints_verified_token(self, send):
        response = self.login()
        self.assertEqual(response.status_code, 202, response.data)
        self.assertNotIn("access", response.data)
        challenge = response.data["challenge_id"]
        code = send.call_args.args[1]
        verified = self.login(challenge_id=challenge, otp=code)
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertTrue(AccessToken(verified.data["access"])["mfa_verified"])
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + verified.data["access"])
        self.assertEqual(self.client.get(PROBE).status_code, 200)
        self.assertEqual(self.login(challenge_id=challenge, otp=code).status_code, 400)

    @override_settings(TWO_FACTORS_AUTHENTICATION=True)
    @patch("horilla_api.mfa.send_code", side_effect=RuntimeError("SMTP unavailable"))
    def test_unavailable_mail_fails_closed(self, send):
        self.assertEqual(self.login().status_code, 503)

    @override_settings(TWO_FACTORS_AUTHENTICATION=True)
    @patch("horilla_api.mfa.send_code")
    def test_code_attempts_and_resends_are_limited(self, send):
        challenge = self.login().data["challenge_id"]
        self.assertEqual(self.login().status_code, 429)
        code = send.call_args.args[1]
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(
                self.login(challenge_id=challenge, otp=wrong).status_code, 400
            )
        self.assertEqual(self.login(challenge_id=challenge, otp=code).status_code, 400)

    @patch("horilla_api.mfa.send_code")
    def test_challenges_expire_and_password_change_invalidates_them(self, send):
        from horilla_api.mfa import TTL, issue_challenge, verify_challenge

        challenge = issue_challenge(self.user)
        code = send.call_args.args[1]
        import time

        with patch("horilla_api.mfa.time.time", return_value=time.time() + TTL + 1):
            self.assertFalse(verify_challenge(self.user, challenge, code))
        self.user.set_password("changed-password-123")
        self.assertFalse(verify_challenge(self.user, challenge, code))

    def test_enabling_mfa_revokes_unverified_token(self):
        token = self.token()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        with override_settings(TWO_FACTORS_AUTHENTICATION=True):
            self.assertEqual(self.client.get(PROBE).status_code, 403)

    def test_legacy_token_without_company_binding_requires_new_login(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(self.client.get(PROBE).status_code, 403)

    @patch(
        "django.core.mail.backends.smtp.EmailBackend.send_messages",
        autospec=True,
        return_value=1,
    )
    def test_mfa_uses_home_company_mail_and_redacts_code(self, smtp):
        from base.email_redaction import REDACTED
        from base.models import DynamicEmailConfiguration, EmailLog
        from horilla_api.mfa import send_code

        configuration = dict(
            host="smtp.example.com",
            port=465,
            username="sender@example.com",
            password="synthetic-only",
            from_email="sender@example.com",
            display_name="KenadHr",
            use_ssl=True,
            use_tls=False,
        )
        DynamicEmailConfiguration.objects.create(
            company_id=self.company, **configuration
        )
        DynamicEmailConfiguration.objects.create(
            company_id=self.foreign, is_primary=True, **configuration
        )
        send_code(self.user, "123456")
        smtp.assert_called_once()
        message = smtp.call_args.args[1][0]
        self.assertEqual(message.to, [self.employee.email])
        self.assertIn("123456", message.body)
        log = EmailLog._base_manager.get(subject="KenadHr verification code")
        self.assertEqual(log.company_id, self.company)
        self.assertEqual(log.body, REDACTED)

"""New accounts use password-reset activation, not predictable credentials."""

from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from base.forms import ChangePasswordForm, ResetPasswordForm
from base.middleware import ForcePasswordChangeMiddleware, TwoFactorAuthMiddleware
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee, make_user


class AccountSecurityTests(TestCase):
    def setUp(self):
        _thread_locals.request = None
        set_selected_company(None)
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.addCleanup(set_selected_company, None)
        self.company = make_company("Activation Co")

    def test_new_employee_password_is_not_phone_and_is_reset_eligible(self):
        employee = make_employee(
            company=self.company, email="activation@test.horilla", phone="0234567890"
        )
        user = employee.employee_user_id
        self.assertFalse(user.check_password(employee.phone))
        self.assertTrue(user.has_usable_password())
        self.assertTrue(user.is_new_employee)
        password = "Fresh!ActivationPassword-219"
        form = ResetPasswordForm(
            user, data={"new_password1": password, "new_password2": password}
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        user.refresh_from_db()
        self.assertFalse(user.is_new_employee)
        self.assertTrue(user.check_password(password))

    def test_historical_phone_password_command_is_dry_run_until_applied(self):
        import io

        from django.core.management import call_command

        user = make_user("legacy-staff", password="0234567890")
        make_employee(
            company=self.company,
            email="legacy@test.horilla",
            phone="0234567890",
            user=user,
        )
        output = io.StringIO()
        call_command("secure_initial_passwords", stdout=output)
        user.refresh_from_db()
        self.assertTrue(user.check_password("0234567890"))
        call_command("secure_initial_passwords", apply=True, stdout=output)
        user.refresh_from_db()
        self.assertFalse(user.check_password("0234567890"))
        self.assertTrue(user.is_new_employee)
        self.assertTrue(user.has_usable_password())

    def test_password_change_rejects_weak_password(self):
        user = make_user("password-test", password="old-password")
        form = ChangePasswordForm(
            user,
            data={
                "old_password": "old-password",
                "new_password": "kenad",
                "confirm_password": "kenad",
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("new_password", form.errors)

    def test_htmx_header_cannot_skip_password_change(self):
        user = make_user("pending-user")
        user.is_new_employee = True
        request = RequestFactory().get(
            "/employee/employee-view/",
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL="http://testserver/change-password/",
        )
        request.user = user
        request.session = {}
        request._messages = FallbackStorage(request)
        response = ForcePasswordChangeMiddleware(lambda r: HttpResponse("private"))(
            request
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], "/change-password/")

    def test_pending_employee_password_page_has_no_protected_background_requests(self):
        user = make_user("pending-staff")
        make_employee(company=self.company, email="pending@test.horilla", user=user)
        user.is_new_employee = True
        user.save(update_fields=["is_new_employee"])
        self.client.force_login(user)
        response = self.client.get("/change-password/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/kenadhr_auth_base.html")
        self.assertTemplateNotUsed(response, "index.html")

    @override_settings(TWO_FACTORS_AUTHENTICATION=True)
    def test_no_mail_configuration_does_not_skip_web_mfa(self):
        request = RequestFactory().get("/")
        request.user = make_user("mfa-user")
        request.session = {}
        response = TwoFactorAuthMiddleware(lambda r: HttpResponse("private"))(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/two-factor")
        request.path = "/change-password/"
        response = TwoFactorAuthMiddleware(lambda r: HttpResponse("private"))(request)
        self.assertEqual(response.status_code, 302)

    @override_settings(KENADHR_PLATFORM_DEVELOPER_USERNAMES=["password-developer"])
    def test_platform_developer_can_complete_required_password_change(self):
        user = make_user(
            "password-developer", password="old-password", is_superuser=True
        )
        user.is_new_employee = True
        user.save(update_fields=["is_new_employee"])
        self.client.force_login(user)
        self.assertEqual(self.client.get("/change-password/").status_code, 200)
        response = self.client.post(
            "/change-password/",
            {
                "old_password": "old-password",
                "new_password": "Violet!Canoe-7391-Quartz",
                "confirm_password": "Violet!Canoe-7391-Quartz",
            },
        )
        self.assertEqual(
            response.status_code,
            302,
            response.context and response.context.get("form").errors,
        )
        user.refresh_from_db()
        self.assertFalse(user.is_new_employee)
        self.assertTrue(user.check_password("Violet!Canoe-7391-Quartz"))

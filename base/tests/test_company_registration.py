"""Exercise public signup with real middleware and company-scoped permissions."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from base.auth_backends import get_account_companies, get_home_company_id
from base.models import Company, CompanyGroupAssignment
from base.views import initialize_database_condition
from employee.models import Employee, EmployeeWorkInformation
from horilla.horilla_middlewares import set_selected_company


@override_settings(KENADHR_COMPANY_REGISTRATION=True, COMPANY_SCOPED_PERMISSIONS=True,
                   TWO_FACTORS_AUTHENTICATION=False, KENADHR_REGISTRATION_HOURLY_LIMIT=20,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CompanyRegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        set_selected_company(None)
        self.url = reverse("company-register")
        self.data = {
            "company": "New Company", "country": "Ghana", "city": "Accra",
            "address": "21 Test Street", "first_name": "Ama", "last_name": "Mensah",
            "email": "ama@example.com", "phone": "+233244123456",
            "password1": "Rivers!Flow79Across", "password2": "Rivers!Flow79Across",
        }

    def tearDown(self):
        cache.clear()
        set_selected_company(None)

    def test_registration_creates_owner_company_and_membership_then_signs_in(self):
        response = self.client.post(self.url, self.data)
        self.assertRedirects(response, reverse("company-registration-complete"))
        user = get_user_model().objects.get(username=self.data["email"])
        company = Company.objects.get(company=self.data["company"])
        self.assertTrue(user.check_password(self.data["password1"]))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(company.created_by_id, user.pk)
        self.assertEqual(get_home_company_id(user), company.pk)
        self.assertEqual(self.client.session["selected_company"], str(company.pk))
        self.assertEqual(CompanyGroupAssignment.objects.get(user=user).company_id, company.pk)
        self.assertTrue(user.has_perm("employee.add_employee"))
        self.assertTrue(user.has_perm("base.add_department"))
        self.assertFalse(user.has_perm("auth.change_group"))
        self.assertFalse(initialize_database_condition())
        dashboard = self.client.get("/", follow=True)
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.redirect_chain[0][0], reverse("dashboard"))
        self.assertContains(dashboard, "New Company")

    def test_second_company_registers_after_first_and_is_isolated(self):
        self.client.post(self.url, self.data)
        first = get_user_model().objects.get(username=self.data["email"])
        company_a = get_home_company_id(first)
        second_client = Client()
        response = second_client.post(self.url, {
            **self.data, "company": "Another Company", "email": "owner@example.net", "address": "22 Test Street",
        })
        self.assertEqual(response.status_code, 302)
        second = get_user_model().objects.get(username="owner@example.net")
        company_b = get_home_company_id(second)
        self.assertNotEqual(company_a, company_b)
        self.assertEqual(list(get_account_companies(second).values_list("pk", flat=True)), [company_b])
        session = second_client.session
        session["selected_company"] = str(company_a)
        session.save()
        second_client.get("/")
        self.assertEqual(second_client.session["selected_company"], str(company_b))
        # Queryset isolation is also enforced, independent of menu filtering.
        set_selected_company(company_b)
        self.assertEqual(list(Employee.objects.values_list("employee_user_id", flat=True)), [second.pk])
        self.assertNotEqual(CompanyGroupAssignment.objects.get(user=first).group_id,
                            CompanyGroupAssignment.objects.get(user=second).group_id)
        self.assertNotEqual(second_client.get("/developer/").status_code, 200)

    def test_invalid_password_phone_and_mismatch_create_nothing(self):
        for values in ({"password2": "Mismatch"}, {"password1": "12345678", "password2": "12345678"},
                       {"phone": "bad"}, {"email": "invalid"}, {"website": "spam"}):
            with self.subTest(values=values):
                response = self.client.post(self.url, {**self.data, **values})
                self.assertContains(response, "Please check the details below.")
                self.assertFalse(get_user_model().objects.filter(username=self.data["email"]).exists())
                self.assertFalse(Company.objects.filter(company=self.data["company"]).exists())
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_duplicate_case_variant_email_is_a_form_error(self):
        self.client.post(self.url, self.data)
        response = Client().post(self.url, {**self.data, "company": "Duplicate", "email": "AMA@EXAMPLE.COM"})
        self.assertContains(response, "An account already uses this email")
        self.assertEqual(get_user_model().objects.filter(username__iexact=self.data["email"]).count(), 1)
        self.assertFalse(Company.objects.filter(company="Duplicate").exists())

    def test_duplicate_company_does_not_create_orphan_user(self):
        self.client.post(self.url, self.data)
        response = Client().post(self.url, {**self.data, "email": "another@example.com"})
        self.assertContains(response, "already registered")
        self.assertFalse(get_user_model().objects.filter(username="another@example.com").exists())

    def test_failure_rolls_back_all_registration_records(self):
        counts = [model.objects.count() for model in (Company, get_user_model(), Employee, EmployeeWorkInformation)]
        with patch("base.registration.CompanyGroupAssignment.objects.create", side_effect=IntegrityError("test")):
            response = self.client.post(self.url, self.data)
        self.assertContains(response, "We could not create the account")
        self.assertEqual(counts, [model.objects.count() for model in (Company, get_user_model(), Employee, EmployeeWorkInformation)])
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotContains(response, self.data["password1"])

    def test_csrf_is_required(self):
        response = Client(enforce_csrf_checks=True).post(self.url, self.data)
        self.assertEqual(response.status_code, 403)

    @override_settings(KENADHR_COMPANY_REGISTRATION=False)
    def test_registration_can_be_closed(self):
        self.assertEqual(self.client.post(self.url, self.data).status_code, 503)
        self.assertNotContains(self.client.get("/login/"), 'href="/register/"')

    @override_settings(COMPANY_SCOPED_PERMISSIONS=False)
    def test_registration_fails_closed_without_company_permissions(self):
        self.assertEqual(self.client.post(self.url, self.data).status_code, 503)

    @override_settings(KENADHR_REGISTRATION_HOURLY_LIMIT=1)
    def test_registration_rate_is_limited(self):
        self.client.post(self.url, {})
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "3600")
        self.assertFalse(Company.objects.filter(company=self.data["company"]).exists())

    def test_existing_owner_can_log_out_and_back_in(self):
        self.client.post(self.url, self.data)
        self.client.logout()
        response = self.client.post(reverse("login"), {"username": self.data["email"], "password": self.data["password1"]})
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_public_links_and_no_company_content_on_registration_page(self):
        Company.objects.create(company="Confidential Tenant", country="GH", city="Accra", address="Secret Street", state="", zip="")
        self.assertContains(self.client.get("/"), 'href="/register/"')
        self.assertContains(self.client.get("/login/"), 'href="/register/"')
        response = self.client.get(self.url)
        self.assertContains(response, "Set up your company")
        self.assertNotContains(response, "Confidential Tenant")

    def test_signed_in_owner_cannot_create_a_second_company_with_the_same_account(self):
        self.client.post(self.url, self.data)
        response = self.client.post(self.url, {**self.data, "company": "Extra Company", "email": "extra@example.com"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Company.objects.filter(company="Extra Company").exists())

    def test_submitted_privilege_flags_are_ignored(self):
        self.client.post(self.url, {**self.data, "is_staff": "true", "is_superuser": "true", "selected_company": "all"})
        user = get_user_model().objects.get(username=self.data["email"])
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(self.client.session["selected_company"], str(get_home_company_id(user)))

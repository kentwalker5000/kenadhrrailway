"""Company settings expose one editable profile, including for administrators."""

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from base.models import Company
from employee.models import Employee
from horilla.horilla_middlewares import _thread_locals
from horilla.testkit import make_company, make_employee, make_user


class CompanySettingsTests(TestCase):
    def setUp(self):
        self.company = make_company("Assigned Company")
        self.other_company = make_company("Unrelated Company")
        self.user = make_user("company-admin", is_superuser=True)
        make_employee(company=self.company, email="company-admin@test.horilla", user=self.user)
        self.client.force_login(self.user)
        self.data = {
            "company": "Updated Company", "address": "1 Updated Street",
            "country": "Ghana", "state": "Greater Accra", "city": "Accra",
            "zip": "00233",
        }

    def test_settings_and_old_list_show_only_the_company_profile(self):
        for route in ("company-view", "company-list"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route), HTTP_HX_REQUEST="true")
                self.assertContains(response, "Assigned Company")
                self.assertContains(response, "Edit company")
                self.assertNotContains(response, "Unrelated Company")
                self.assertNotContains(response, reverse("company-create-form"))
                self.assertNotContains(response, "Is Hq")
                self.assertNotContains(response, 'id="selectedInstance"')

    def test_editor_needs_change_permission_and_can_save_own_details(self):
        self.user.is_superuser = False
        self.user.save()
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="base", codename__in=["view_company", "change_company"]
        ))
        url = reverse("company-update-form", kwargs={"pk": self.company.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.company.company)
        self.assertNotContains(response, 'name="hq"')
        response = self.client.post(url, self.data, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Redirect"), reverse("company-view"))
        self.company.refresh_from_db()
        self.assertEqual(self.company.company, "Updated Company")
        self.assertTrue(self.company.hq)

    def test_both_create_routes_refuse_even_a_superuser(self):
        for route in ("company-create", "company-create-form"):
            for method in (self.client.get, self.client.post):
                response = method(reverse(route), self.data, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 403)
        self.assertEqual(Company.objects.count(), 2)

    def test_both_edit_routes_refuse_another_company(self):
        for route, key in (("company-update", "id"), ("company-update-form", "pk")):
            for method in (self.client.get, self.client.post):
                response = method(
                    reverse(route, kwargs={key: self.other_company.pk}), self.data,
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(response.status_code, 404)
        self.other_company.refresh_from_db()
        self.assertEqual(self.other_company.company, "Unrelated Company")

    def test_company_delete_routes_refuse_before_deleting_related_records(self):
        for company in (self.company, self.other_company):
            url = reverse("generic-delete") + f"?model=base.Company&pk={company.pk}"
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {
                "action": "on", "revert": "on", "confirm": "on"
            }).status_code, 403)
            response = self.client.post(reverse("company-delete", kwargs={"obj_id": company.pk}))
            self.assertEqual(response.status_code, 403)
        self.assertEqual(Company.objects.count(), 2)
        self.assertTrue(Employee.objects.filter(employee_user_id=self.user).exists())

    def test_model_guards_other_company_changes_through_alternate_forms(self):
        request = RequestFactory().get("/")
        request.user = self.user
        _thread_locals.request = request
        try:
            with self.assertRaises(ValidationError):
                make_company("Forbidden company")
            with self.assertRaises(ValidationError):
                self.other_company.save()
            with self.assertRaises(PermissionDenied):
                self.other_company.delete()
        finally:
            _thread_locals.request = None

    def test_company_api_reads_and_updates_only_the_assigned_company(self):
        client = APIClient()
        refresh = RefreshToken.for_user(self.user)
        refresh["company_id"] = self.company.pk
        token = str(refresh.access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        listing_url = reverse("api-companies_detail")
        own_url = reverse("api-companies_detail_with_pk", kwargs={"pk": self.company.pk})
        other_url = reverse("api-companies_detail_with_pk", kwargs={"pk": self.other_company.pk})
        response = client.get(listing_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Assigned Company", str(response.data))
        self.assertNotIn("Unrelated Company", str(response.data))
        self.assertEqual(client.get(other_url).status_code, 404)
        self.assertEqual(client.put(other_url, self.data, format="json").status_code, 404)
        self.assertEqual(client.post(listing_url, self.data, format="json").status_code, 403)
        self.assertEqual(client.delete(own_url).status_code, 403)
        self.assertEqual(client.delete(other_url).status_code, 403)
        response = client.put(own_url, self.data, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.company.refresh_from_db()
        self.assertEqual(self.company.company, "Updated Company")

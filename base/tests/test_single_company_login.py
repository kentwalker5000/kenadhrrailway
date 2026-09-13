"""HR accounts must never select another company's tenant context."""

from django.test import RequestFactory, TestCase
from django.urls import reverse

from base.auth_backends import get_allowed_company_ids
from base.context_processors import get_companies
from horilla.testkit import make_company, make_employee, make_user


class SingleCompanyLoginTests(TestCase):
    def setUp(self):
        self.company_a = make_company("Tenant A")
        self.company_b = make_company("Tenant B", address="2 Tenant Way")
        self.user = make_user("tenant-hr")
        make_employee(
            company=self.company_a,
            email="tenant-hr@test.horilla",
            user=self.user,
        )
        self.user.refresh_from_db()
        self.client.force_login(self.user)

    def test_login_scope_comes_from_employee_company_not_session(self):
        session = self.client.session
        session["selected_company"] = str(self.company_b.id)
        session.save()

        self.client.get("/")

        self.assertEqual(self.client.session["selected_company"], str(self.company_a.id))

    def test_switch_endpoint_cannot_select_another_company(self):
        self.client.get("/")
        response = self.client.get(
            reverse("update-selected-company"),
            {"company_id": self.company_b.id},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["selected_company"], str(self.company_a.id))

    def test_only_home_company_is_available_to_hr_user(self):
        self.client.get("/")
        request = RequestFactory().get("/")
        request.user = self.user
        request.session = {"selected_company": str(self.company_a.id)}

        self.assertEqual(get_allowed_company_ids(self.user), {self.company_a.id})
        self.assertFalse(get_companies(request)["show_company_switcher"])

"""The platform developer console must remain separate from company tenancy."""

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from base.models import Company
from horilla.testkit import make_company, make_employee, make_user


@override_settings(KENADHR_PLATFORM_DEVELOPER_USERNAMES=("kenadhr-developer",))
class DeveloperDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("First Registered Company")
        cls.other_company = make_company(
            "Archived Company", address="2 Archive Street", is_active=False
        )
        cls.developer = make_user("kenadhr-developer", is_superuser=True)
        cls.owner = make_user("first-owner", is_superuser=True)
        cls.owner.first_name = "Ada"
        cls.owner.last_name = "Owner"
        cls.owner.save(update_fields=["first_name", "last_name"])
        Company.objects.filter(pk=cls.company.pk).update(created_by=cls.owner)
        make_employee(
            company=cls.company,
            email="first-owner@example.test",
            first_name="Ada",
            last_name="Owner",
            user=cls.owner,
        )
        cls.company_admin = make_user("company-admin", is_superuser=True)
        make_employee(
            company=cls.company,
            email="company-admin@example.test",
            first_name="Company",
            last_name="Admin",
            user=cls.company_admin,
        )
        cls.unassigned_superuser = make_user("unassigned-superuser", is_superuser=True)

    def setUp(self):
        self.client.force_login(self.developer)

    def test_developer_sees_all_companies_and_registration_information(self):
        response = self.client.get(reverse("developer-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "First Registered Company")
        self.assertContains(response, "Archived Company")
        self.assertContains(response, "Ada Owner")
        self.assertContains(response, "company-admin@example.test")
        first_company = next(
            company
            for company in response.context["companies"]
            if company.pk == self.company.pk
        )
        self.assertEqual(first_company.active_employee_count, 2)
        self.assertContains(response, "Archived")
        self.assertEqual(self.client.session["selected_company"], "all")

    def test_search_restricts_display_but_not_summary_counts(self):
        response = self.client.get(
            reverse("developer-dashboard"), {"q": "Archive Street"}
        )

        self.assertContains(response, "Archived Company")
        self.assertNotContains(response, "First Registered Company")
        self.assertEqual(response.context["total_companies"], 2)

    def test_developer_can_edit_and_archive_any_company(self):
        response = self.client.post(
            reverse("developer-company-edit", kwargs={"pk": self.company.pk}),
            {
                "company": "Updated Registered Company",
                "hq": "on",
                "address": "1 Test St",
                "country": "Ghana",
                "state": "Greater Accra",
                "city": "Accra",
                "zip": "00233",
                # Omitting this checkbox archives the company without deleting data.
            },
        )

        self.assertRedirects(response, reverse("developer-dashboard"))
        self.company.refresh_from_db()
        self.assertEqual(self.company.company, "Updated Registered Company")
        self.assertFalse(self.company.is_active)
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_company_superuser_cannot_enter_even_if_their_username_is_configured(self):
        with override_settings(KENADHR_PLATFORM_DEVELOPER_USERNAMES=("company-admin",)):
            self.client.force_login(self.company_admin)
            response = self.client.get(reverse("developer-dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_unconfigured_or_unauthenticated_users_cannot_enter(self):
        self.client.logout()
        response = self.client.get(reverse("developer-dashboard"))
        self.assertRedirects(
            response, f"{reverse('login')}?next={reverse('developer-dashboard')}"
        )

        self.client.force_login(self.company_admin)
        response = self.client.get(reverse("developer-dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_unassigned_superuser_cannot_use_the_platform_entry_point(self):
        self.client.force_login(self.unassigned_superuser)

        response = self.client.get(reverse("home-page"))

        self.assertRedirects(response, reverse("login"))

    def test_configured_developer_can_sign_in_without_an_employee_record(self):
        from base.platform_access import is_platform_developer

        self.assertTrue(is_platform_developer(self.developer))
        client = Client()
        response = client.post(
            reverse("login"), {"username": "kenadhr-developer", "password": "pass"}
        )

        self.assertRedirects(
            response, reverse("home-page"), fetch_redirect_response=False
        )
        self.assertIn("_auth_user_id", client.session)
        self.developer.refresh_from_db()
        self.assertTrue(is_platform_developer(self.developer))
        response = client.get(reverse("home-page"))
        self.assertRedirects(
            response, reverse("developer-dashboard"), fetch_redirect_response=False
        )
        response = client.get(reverse("developer-dashboard"))
        self.assertEqual(response.status_code, 200)

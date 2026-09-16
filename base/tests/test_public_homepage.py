"""The public homepage must not change workspace access or disclose tenant data."""

from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth.models import AnonymousUser
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from base import public_site
from horilla.testkit import (
    CompanyFilterTestMixin,
    make_company,
    make_employee,
    make_user,
)


class PageElements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class PublicHomepageTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/")
        self.request.user = AnonymousUser()

    def test_anonymous_home_renders_without_database_access(self):
        # SimpleTestCase rejects DB queries, including tenant context processors.
        response = public_site.home(self.request)
        self.assertContains(response, "People first.")
        self.assertContains(response, "KenadHr")
        self.assertContains(response, "Sample data")
        self.assertNotContains(response, "Horilla")

    def test_welcome_is_available_without_an_account(self):
        self.assertEqual(public_site.welcome(self.request).status_code, 200)
        self.assertEqual(resolve("/").func, public_site.home)
        self.assertEqual(resolve("/welcome/").func, public_site.welcome)

    def test_signed_in_home_uses_the_existing_guarded_entry_point(self):
        self.request.user = SimpleNamespace(is_authenticated=True)
        expected = HttpResponse(status=302)
        with patch("base.views.home", return_value=expected) as workspace:
            self.assertIs(public_site.home(self.request), expected)
        workspace.assert_called_once_with(self.request)

    def test_welcome_does_not_render_request_or_company_information(self):
        self.request.user = SimpleNamespace(
            is_authenticated=True, username="PRIVATE-STAFF-NAME"
        )
        self.request.selected_company_instance = "PRIVATE-COMPANY"
        response = public_site.welcome(self.request)
        self.assertContains(response, "People first.")
        self.assertNotContains(response, "PRIVATE-STAFF-NAME")
        self.assertNotContains(response, "PRIVATE-COMPANY")

    def test_every_navigation_link_has_a_real_local_destination(self):
        page = PageElements(public_site.welcome(self.request).content.decode())
        ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        for tag, attrs in page.elements:
            if tag != "a":
                continue
            destination = urlsplit(attrs["href"])
            with self.subTest(href=attrs["href"]):
                self.assertFalse(destination.scheme)
                self.assertFalse(destination.netloc)
                if destination.fragment:
                    self.assertIn(destination.fragment, ids)
                else:
                    self.assertIn(
                        resolve(destination.path).url_name,
                        (
                            "login",
                            "product-home",
                            "forgot-password",
                            "open-source-notices",
                        ),
                    )

    @override_settings(STATIC_URL="/static/")
    def test_assets_exist_and_no_external_scripts_or_trackers_are_loaded(self):
        page = PageElements(public_site.welcome(self.request).content.decode())
        for tag, attrs in page.elements:
            self.assertNotEqual(tag, "script")
            asset = attrs.get("src")
            if tag == "link":
                asset = attrs.get("href")
            if asset:
                with self.subTest(asset=asset):
                    self.assertTrue(asset.startswith("/static/"))
                    self.assertIsNotNone(finders.find(asset.removeprefix("/static/")))
            if tag == "img":
                self.assertIn("alt", attrs)

    def test_faq_uses_one_native_exclusive_group_and_real_reset_link(self):
        page = PageElements(public_site.welcome(self.request).content.decode())
        details = [attrs for tag, attrs in page.elements if tag == "details"]
        self.assertEqual(len(details), 5)
        self.assertEqual({attrs.get("name") for attrs in details}, {"homepage-faq"})
        self.assertEqual(sum("open" in attrs for attrs in details), 1)
        self.assertTrue(
            any(
                attrs.get("href") == reverse("forgot-password")
                for _, attrs in page.elements
            )
        )

    def test_public_routes_accept_head_and_reject_mutations(self):
        for view in (public_site.home, public_site.welcome):
            request = self.factory.head("/")
            request.user = AnonymousUser()
            self.assertEqual(view(request).status_code, 200)
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(view=view.__name__, method=method):
                    request = getattr(self.factory, method)("/")
                    request.user = AnonymousUser()
                    self.assertEqual(view(request).status_code, 405)


class HomepageEntryFlowTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Private Homepage Test Company")
        cls.other_company = make_company("Other Private Company", address="2 Test St")
        cls.employee = make_user("homepage-staff")
        cls.owner = make_user("homepage-owner", is_superuser=True)
        for user in (cls.employee, cls.owner):
            make_employee(company=cls.company, user=user, email=user.email)

    def test_public_routes_do_not_expose_real_company_or_staff_data(self):
        for route in ("home-page", "product-home"):
            response = self.client.get(reverse(route))
            self.assertContains(response, "People first.")
            for private_value in (
                self.company.company,
                self.other_company.company,
                self.employee.email,
                self.owner.email,
            ):
                self.assertNotContains(response, private_value)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_employee_root_keeps_self_service_redirect_and_company_scope(self):
        self.client.force_login(self.employee)
        session = self.client.session
        session["selected_company"] = str(self.other_company.pk)
        session.save()
        response = self.client.get(reverse("home-page"))
        self.assertRedirects(
            response, reverse("staff-platform"), fetch_redirect_response=False
        )
        self.assertEqual(self.client.session["selected_company"], str(self.company.pk))

    def test_company_owner_root_keeps_analytics_redirect(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("home-page"))
        self.assertRedirects(
            response, reverse("dashboard"), fetch_redirect_response=False
        )

    def test_signed_in_user_can_preview_homepage_without_losing_session(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("product-home"))
        self.assertContains(response, "People first.")
        self.assertNotContains(response, self.company.company)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.employee.pk)

    def test_homepage_does_not_make_company_pages_public(self):
        for route in ("ess-dashboard", "dashboard", "employee-view"):
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(
                urlsplit(response.url).path.rstrip("/"), reverse("login").rstrip("/")
            )

    def test_login_page_links_back_to_public_homepage(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, f'href="{reverse("product-home")}"')

    @override_settings(TWO_FACTORS_AUTHENTICATION=True)
    def test_existing_two_factor_gate_still_applies(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("home-page"))
        self.assertRedirects(response, "/two-factor", fetch_redirect_response=False)

    def test_existing_password_change_gate_still_applies(self):
        self.employee.is_new_employee = True
        self.employee.save(update_fields=["is_new_employee"])
        self.client.force_login(self.employee)
        response = self.client.get(reverse("home-page"))
        self.assertRedirects(
            response, reverse("change-password"), fetch_redirect_response=False
        )

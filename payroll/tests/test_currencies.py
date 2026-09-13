"""Currency selection and tenant-specific display; no exchange-rate conversion."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Permission
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from base.templatetags.horillafilters import currency_symbol_position
from horilla.horilla_middlewares import _thread_locals
from horilla.testkit import CompanyFilterTestMixin, make_company, make_employee, make_user
from payroll.currencies import AFRICAN_CURRENCIES, currency_choices, get_currency_format
from payroll.forms.component_forms import PayrollSettingsForm
from payroll.models.tax_models import PayrollSettings


class CurrencyTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Ghana Payroll")
        cls.other_company = make_company("Kenya Payroll")
        cls.user = make_user("currency-admin", is_superuser=True)
        make_employee(company=cls.company, user=cls.user, email="currency-admin@example.com")
        # A shared row deliberately predates both company-specific settings.
        cls.shared = PayrollSettings.objects.create(currency_symbol="$", position="postfix")
        cls.settings = PayrollSettings.objects.create(company_id=cls.company, currency_symbol="GHS", position="prefix")
        cls.other_settings = PayrollSettings.objects.create(company_id=cls.other_company, currency_symbol="KES", position="postfix")

    def setUp(self):
        self.clear_company_context()
        _thread_locals.request = None
        self.addCleanup(setattr, _thread_locals, "request", None)

    def test_all_african_iso_currency_codes_are_present_without_duplicates(self):
        expected = set("AOA BIF BWP CDF CVE DJF DZD EGP ERN ETB GHS GMD GNF KES KMF LRD LSL LYD MAD MGA MRU MUR MWK MZN NAD NGN RWF SCR SDG SHP SLE SOS SSP STN SZL TND TZS UGX XAF XOF ZAR ZMW ZWG".split())
        codes = [code for code, _label in AFRICAN_CURRENCIES]
        self.assertEqual(set(codes), expected)
        self.assertEqual(len(codes), len(expected))
        self.assertEqual(codes[0], "GHS")
        self.assertIn("Cedis", str(AFRICAN_CURRENCIES[0][1]))
        choices = {code for _group, entries in currency_choices() for code, _label in entries}
        self.assertTrue({"EUR", "USD", "GBP"}.issubset(choices))
        self.assertTrue({"SLL", "MRO", "STD", "ZWL"}.isdisjoint(choices))

    def test_every_african_currency_can_be_selected(self):
        for code, _label in AFRICAN_CURRENCIES:
            with self.subTest(code=code):
                form = PayrollSettingsForm({"currency_symbol": code, "position": "prefix"}, instance=self.settings)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["currency_symbol"], code)

    def test_current_legacy_symbol_is_preserved_without_forcing_a_currency_change(self):
        instance = PayrollSettings(currency_symbol="GH₵", position="prefix")
        form = PayrollSettingsForm({"currency_symbol": "GH₵", "position": "postfix"}, instance=instance)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn('value="GH₵"', str(form["currency_symbol"]))

    def test_unknown_new_code_is_rejected(self):
        form = PayrollSettingsForm({"currency_symbol": "FAKE", "position": "prefix"}, instance=self.settings)
        self.assertFalse(form.is_valid())
        self.assertIn("currency_symbol", form.errors)

    def test_company_currency_wins_over_an_older_shared_row(self):
        self.set_company_context(str(self.company.pk))
        self.assertEqual(get_currency_format(), ("GHS", "prefix"))
        self.assertEqual(currency_symbol_position("100.00"), "GHS 100.00")
        self.set_company_context(str(self.other_company.pk))
        self.assertEqual(currency_symbol_position("100.00"), "100.00 KES")

    def test_shared_default_and_missing_settings_do_not_crash_or_leak_another_company(self):
        self.assertEqual(currency_symbol_position("100.00"), "100.00 $")
        PayrollSettings._base_manager.filter(pk=self.shared.pk).delete()
        self.assertEqual(currency_symbol_position("100.00"), "100.00 $")
        self.assertEqual(get_currency_format(company_id=999999), ("$", "postfix"))

    def test_form_renders_selector_with_codes_in_both_settings_templates(self):
        form = PayrollSettingsForm(instance=self.settings)
        request = RequestFactory().get("/settings/")
        for path in (
            "horilla_theme/templates/payroll/settings/payroll_settings.html",
            "payroll/templates/payroll/settings/payroll_settings.html",
        ):
            with self.subTest(template=path):
                source = (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")
                rendered = Template(source).render(Context({"currency_form": form, "request": request}))
                self.assertIn('<select', rendered)
                self.assertRegex(rendered, r'<option\b[^>]*value="GHS"\s+selected(?:\s|>)')
                self.assertIn('value="ZWG"', rendered)
                self.assertIn('value="XOF"', rendered)

    def test_settings_save_changes_only_callers_company_and_persists_position(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("payroll-settings"), {
            "currency_symbol": "GHS", "position": "postfix", "company_id": self.other_company.pk,
        }, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.settings.refresh_from_db()
        self.other_settings.refresh_from_db()
        self.shared.refresh_from_db()
        self.assertEqual((self.settings.currency_symbol, self.settings.position), ("GHS", "postfix"))
        self.assertEqual(self.other_settings.currency_symbol, "KES")
        self.assertEqual(self.shared.currency_symbol, "$")

    def test_currency_cannot_be_saved_with_view_permission_alone(self):
        self.user.is_superuser = False
        self.user.save()
        self.user.user_permissions.add(Permission.objects.get(codename="view_payrollsettings"))
        self.client.force_login(self.user)
        response = self.client.post(reverse("payroll-settings"), {"currency_symbol": "NGN", "position": "prefix"})
        self.assertEqual(response.status_code, 403)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.currency_symbol, "GHS")

    def test_payslip_display_filter_uses_selected_african_currency(self):
        self.set_company_context(str(self.company.pk))
        template = Template('{% load horillafilters %}{{ amount|floatformat:2|currency_symbol_position }}')
        self.assertEqual(template.render(Context({"amount": 115})), "GHS 115.00")

    def test_new_company_can_save_its_first_currency_row(self):
        PayrollSettings._base_manager.filter(pk=self.settings.pk).delete()
        self.client.force_login(self.user)
        response = self.client.post(reverse("payroll-settings"), {"currency_symbol": "GHS", "position": "prefix"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PayrollSettings._base_manager.get(company_id=self.company).currency_symbol, "GHS")

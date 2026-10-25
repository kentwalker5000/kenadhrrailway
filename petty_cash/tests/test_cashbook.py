from datetime import date
from decimal import Decimal

from django.test import TestCase

from base.models import Company
from horilla.testkit import make_employee, make_user
from petty_cash.models import PettyCashAccount, PettyCashEntry
from petty_cash.forms import PettyCashAccountForm, PettyCashEntryForm


class PettyCashCashbookTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(company="Cashbook QA")
        self.user = make_user("cashbook-admin", is_superuser=True)
        make_employee(company=self.company, user=self.user, email="cashbook@example.test")
        self.account = PettyCashAccount._base_manager.create(
            name="Office Float", company_id=self.company, opening_balance=Decimal("100.00")
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()

    def test_posted_entries_calculate_current_balance(self):
        PettyCashEntry._base_manager.create(
            account=self.account,
            transaction_date=date.today(),
            entry_type=PettyCashEntry.TYPE_TOP_UP,
            amount=Decimal("50.00"),
            description="Float replenishment",
        )
        expense = PettyCashEntry._base_manager.create(
            account=self.account,
            transaction_date=date.today(),
            entry_type=PettyCashEntry.TYPE_EXPENSE,
            amount=Decimal("35.50"),
            description="Office supplies",
        )
        self.assertEqual(expense.direction, PettyCashEntry.DIRECTION_OUT)
        self.assertEqual(self.account.current_balance, Decimal("114.50"))

    def test_top_up_does_not_require_a_direction_but_adjustment_does(self):
        data = {"account": self.account.pk, "transaction_date": date.today(),
                "entry_type": "top_up", "amount": "15.00", "description": "Cash received"}
        form = PettyCashEntryForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().direction, "in")
        data["entry_type"] = "adjustment"
        form = PettyCashEntryForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("direction", form.errors)

    def test_float_edit_cannot_rewrite_opening_balance_or_currency(self):
        form = PettyCashAccountForm({"name": "Office Float", "opening_balance": "9999",
                                    "currency": "USD", "is_active": "on"}, instance=self.account)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.account.refresh_from_db()
        self.assertEqual(self.account.opening_balance, Decimal("100.00"))
        self.assertEqual(self.account.currency, "GHS")

    def test_duplicate_float_is_a_form_error(self):
        response = self.client.post("/petty-cash/floats/new/", {
            "name": "Office Float", "opening_balance": "10", "currency": "GHS", "is_active": "on"
        }, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertEqual(PettyCashAccount._base_manager.filter(company_id=self.company).count(), 1)

    def test_void_popup_requires_a_reason_then_refreshes_cashbook(self):
        entry = PettyCashEntry._base_manager.create(account=self.account, transaction_date=date.today(),
                                                   amount="12.00", description="Duplicate receipt")
        url = f"/petty-cash/entries/{entry.pk}/void/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertNotContains(response, 'id="ohMainContent"')
        self.assertContains(response, 'hx-target="#objectUpdateModalTarget"')
        response = self.client.post(url, {"void_reason": ""}, HTTP_HX_REQUEST="true")
        entry.refresh_from_db()
        self.assertEqual(entry.status, "posted")
        response = self.client.post(url, {"void_reason": "Duplicate receipt"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["HX-Redirect"], "/petty-cash/")
        entry.refresh_from_db()
        self.assertEqual(entry.status, "void")

    def test_voided_entry_is_retained_but_removed_from_balance(self):
        entry = PettyCashEntry._base_manager.create(
            account=self.account,
            transaction_date=date.today(),
            amount=Decimal("40.00"),
            description="Taxi to meeting",
        )
        response = self.client.post(
            f"/petty-cash/entries/{entry.pk}/void/", {"void_reason": "Receipt entered twice"}
        )
        self.assertRedirects(response, "/petty-cash/")
        entry.refresh_from_db()
        self.assertEqual(entry.status, PettyCashEntry.STATUS_VOID)
        self.assertEqual(entry.void_reason, "Receipt entered twice")
        self.assertEqual(self.account.current_balance, Decimal("100.00"))

    def test_cashbook_page_and_entry_form_are_available(self):
        self.assertEqual(self.client.get("/petty-cash/").status_code, 200)
        modal = self.client.get("/petty-cash/entries/new/", HTTP_HX_REQUEST="true")
        self.assertEqual(modal.status_code, 200)
        self.assertContains(modal, "oh-modal__dialog-header")
        response = self.client.post(
            "/petty-cash/entries/new/",
            {
                "account": self.account.pk,
                "transaction_date": date.today().isoformat(),
                "entry_type": PettyCashEntry.TYPE_EXPENSE,
                "direction": PettyCashEntry.DIRECTION_IN,
                "amount": "12.75",
                "category": "Office supplies",
                "payee": "Local vendor",
                "description": "Staples",
                "reference": "QA-1",
            },
        )
        self.assertRedirects(response, "/petty-cash/")
        entry = PettyCashEntry._base_manager.get(reference="QA-1")
        self.assertEqual(entry.direction, PettyCashEntry.DIRECTION_OUT)

    def test_amount_spent_card_excludes_top_ups_and_voided_entries(self):
        PettyCashEntry._base_manager.create(
            account=self.account,
            transaction_date=date.today(),
            entry_type=PettyCashEntry.TYPE_EXPENSE,
            amount=Decimal("35.50"),
            description="Stationery",
        )
        PettyCashEntry._base_manager.create(
            account=self.account,
            transaction_date=date.today(),
            entry_type=PettyCashEntry.TYPE_TOP_UP,
            amount=Decimal("50.00"),
            description="Replenishment",
        )
        PettyCashEntry._base_manager.create(
            account=self.account,
            transaction_date=date.today(),
            entry_type=PettyCashEntry.TYPE_EXPENSE,
            amount=Decimal("8.00"),
            description="Voided taxi",
            status=PettyCashEntry.STATUS_VOID,
        )
        response = self.client.get("/petty-cash/")
        self.assertContains(response, 'id="pettyCashAmountSpent"')
        self.assertContains(response, 'id="pettyCashCashIn"')
        self.assertContains(response, "Amount spent")
        self.assertContains(response, "Cash in")
        self.assertContains(response, "35.50")
        self.assertContains(response, "50.00")
        self.assertNotContains(response, "43.50")

    def test_navigation_and_history_return_page_but_search_returns_fragment(self):
        for headers in [
            {"HTTP_HX_REQUEST": "true", "HTTP_HX_SIDEBAR_NAV": "true"},
            {"HTTP_HX_REQUEST": "true", "HTTP_HX_HISTORY_RESTORE_REQUEST": "true"},
        ]:
            with self.subTest(headers=headers):
                response = self.client.get("/petty-cash/", **headers)
                self.assertContains(response, 'id="ohMainContent"')
                self.assertContains(response, 'id="breadcrumbs-container"')
                self.assertContains(response, 'hx-history-elt')
        search = self.client.get("/petty-cash/?search=Office", HTTP_HX_REQUEST="true")
        self.assertEqual(search.status_code, 200)
        self.assertNotContains(search, 'id="ohMainContent"')

    def test_modal_entry_save_redirects_back_to_the_cashbook(self):
        response = self.client.post(
            "/petty-cash/entries/new/",
            {
                "account": self.account.pk,
                "transaction_date": date.today().isoformat(),
                "entry_type": PettyCashEntry.TYPE_TOP_UP,
                "direction": PettyCashEntry.DIRECTION_OUT,
                "amount": "50.00",
                "description": "Float replenishment",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], "/petty-cash/")

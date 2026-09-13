"""HR accounts must never select another company's tenant context."""

from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from base.auth_backends import get_allowed_company_ids, get_home_company_id
from base.context_processors import get_companies
from base.forms import AddToUserGroupForm, AssignUserGroup
from base.models import CompanyGroupAssignment
from employee.models import Employee, EmployeeWorkInformation
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee, make_user


class SingleCompanyLoginTests(TestCase):
    def setUp(self):
        self.company_a = make_company("Tenant A")
        self.company_b = make_company("Tenant B", address="2 Tenant Way")
        self.user = make_user("tenant-hr")
        self.employee = make_employee(
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

    def test_company_bound_superuser_cannot_use_all_companies(self):
        superuser = make_user("tenant-admin", is_superuser=True)
        make_employee(
            company=self.company_a,
            email="tenant-admin@test.horilla",
            user=superuser,
        )
        superuser.refresh_from_db()
        self.client.force_login(superuser)
        session = self.client.session
        session["selected_company"] = "all"
        session.save()

        self.client.get("/")

        self.assertEqual(self.client.session["selected_company"], str(self.company_a.id))
        request = RequestFactory().get("/")
        request.user = superuser
        request.session = {"selected_company": str(self.company_a.id)}
        companies = get_companies(request)
        self.assertEqual(
            [company[0] for company in companies["all_companies"]],
            [self.company_a.id],
        )
        self.assertFalse(companies["show_company_switcher"])

        for target in ("all", self.company_b.pk):
            self.client.get(
                reverse("update-selected-company"),
                {"company_id": target},
                HTTP_HX_REQUEST="true",
            )
            self.assertEqual(self.client.session["selected_company"], str(self.company_a.pk))

    def test_unassigned_admin_cannot_enter_with_an_existing_session(self):
        self.user.is_superuser = True
        self.user.save()
        EmployeeWorkInformation.objects.filter(employee_id=self.employee).update(company_id=None)
        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("selected_company", self.client.session)
        self.assertEqual(get_allowed_company_ids(self.user), set())

    def test_unassigned_admin_cannot_sign_in(self):
        self.client.logout()
        self.user.is_superuser = True
        self.user.save()
        EmployeeWorkInformation.objects.filter(employee_id=self.employee).update(company_id=None)
        self.client.post(reverse("login"), {"username": self.user.username, "password": "pass"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_company_resolver_ignores_stale_relations_and_prior_context(self):
        self.assertEqual(self.user.employee_get.employee_work_info.company_id_id, self.company_a.pk)
        EmployeeWorkInformation.objects.filter(employee_id=self.employee).update(company_id=None)
        set_selected_company(self.company_b.pk)
        try:
            self.assertIsNone(get_home_company_id(self.user))
        finally:
            set_selected_company(None)

    def test_unassigned_account_has_no_company_menu(self):
        request = RequestFactory().get("/")
        request.user = make_user("unassigned-admin", is_superuser=True)
        request.session = {"selected_company": "all"}
        context = get_companies(request)
        self.assertEqual(context["all_companies"], [])
        self.assertFalse(context["show_company_switcher"])

    def test_role_cannot_assign_an_account_to_a_second_company(self):
        group = Group.objects.create(name="Single company role")
        CompanyGroupAssignment.objects.create(user=self.user, company=self.company_a, group=group)
        with self.assertRaises(ValidationError):
            CompanyGroupAssignment.objects.create(user=self.user, company=self.company_b, group=group)
        with self.assertRaises(ValidationError):
            CompanyGroupAssignment.objects.bulk_create([
                CompanyGroupAssignment(user=self.user, company=self.company_b, group=group)
            ])
        with self.assertRaises(ValidationError):
            CompanyGroupAssignment.objects.filter(user=self.user).update(company=self.company_b)

    def test_legacy_foreign_role_does_not_grant_permissions_or_menu_access(self):
        group = Group.objects.create(name="Old foreign grant")
        permission = Permission.objects.get(codename="change_company", content_type__app_label="base")
        group.permissions.add(permission)
        with override_settings(SINGLE_COMPANY_LOGIN=False):
            CompanyGroupAssignment.objects.create(user=self.user, company=self.company_b, group=group)
        self.user.groups.add(group)
        set_selected_company("all")
        try:
            self.assertFalse(self.user.has_perm("base.change_company"))
        finally:
            set_selected_company(None)

    def test_both_role_forms_only_grant_the_employees_company(self):
        group = Group.objects.create(name="HR role")
        data = QueryDict(mutable=True)
        data.setlist("employee", [str(self.employee.pk)])
        data["group"] = str(group.pk)
        data.setlist("companies", [str(self.company_a.pk), str(self.company_b.pk)])
        form = AssignUserGroup(data)
        self.assertNotIn("companies", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        form = AddToUserGroupForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(
            set(CompanyGroupAssignment.objects.filter(user=self.user).values_list("company_id", flat=True)),
            {self.company_a.pk},
        )

    def test_role_form_rejects_employee_from_another_company(self):
        other = make_employee(company=self.company_b, email="other@test.horilla")
        group = Group.objects.create(name="HR role")
        request = RequestFactory().get("/")
        request.user = self.user
        request.session = {"selected_company": str(self.company_a.pk)}
        _thread_locals.request = request
        try:
            data = QueryDict(mutable=True)
            data.setlist("employee", [str(other.pk)])
            data["group"] = str(group.pk)
            for form_class in (AssignUserGroup, AddToUserGroupForm):
                form = form_class(data)
                self.assertFalse(form.is_valid())
        finally:
            _thread_locals.request = None

    def test_new_employee_inherits_company_and_admin_cannot_change_it(self):
        self.user.is_superuser = True
        self.user.save()
        request = RequestFactory().get("/")
        request.user = self.user
        request.session = {"selected_company": str(self.company_a.pk)}
        _thread_locals.request = request
        try:
            employee = Employee.objects.create(
                employee_first_name="New", employee_last_name="Hire",
                email="new-hire@test.horilla", phone="9999999999",
            )
            work_info = EmployeeWorkInformation.objects.get(employee_id=employee)
            self.assertEqual(work_info.company_id_id, self.company_a.pk)
            work_info.company_id = self.company_b
            with self.assertRaises(ValidationError):
                work_info.save()
        finally:
            _thread_locals.request = None

    def test_editing_role_members_preserves_the_other_company(self):
        other = make_employee(company=self.company_b, email="other-member@test.horilla")
        group = Group.objects.create(name="Shared role definition")
        for employee, company in ((self.employee, self.company_a), (other, self.company_b)):
            CompanyGroupAssignment.objects.create(user=employee.employee_user_id, company=company, group=group)
            employee.employee_user_id.groups.add(group)
        request = RequestFactory().get("/")
        request.user = self.user
        request.session = {"selected_company": str(self.company_a.pk)}
        _thread_locals.request = request
        try:
            data = QueryDict(mutable=True)
            data["group"] = str(group.pk)
            form = AssignUserGroup(data)
            self.assertTrue(form.is_valid(), form.errors)
            form.save(mode="edit")
            self.assertFalse(group.user_set.filter(pk=self.user.pk).exists())
            self.assertTrue(group.user_set.filter(pk=other.employee_user_id_id).exists())
        finally:
            _thread_locals.request = None

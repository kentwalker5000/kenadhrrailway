"""The self-profile action and edit endpoint must agree about access."""

from django.test import TestCase
from django.urls import reverse

from accessibility.models import DefaultAccessibility
from employee.models import ProfileEditFeature
from horilla.testkit import (
    CompanyFilterTestMixin,
    make_company,
    make_employee,
    make_user,
)


class StaffProfileEditAccessTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Profile Edit Company")
        cls.user = make_user("self-profile-editor")
        cls.employee = make_employee(
            company=cls.company,
            user=cls.user,
            email="self-profile-editor@example.test",
        )
        cls.other_employee = make_employee(
            company=cls.company,
            email="other-profile@example.test",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def profile_response(self, employee=None):
        return self.client.get(
            reverse("employee-profile", kwargs={"pk": (employee or self.employee).pk}),
            HTTP_HX_REQUEST="true",
        )

    def restriction(self, **kwargs):
        return DefaultAccessibility.objects.create(
            feature="profile_edit", filter={"feature": ["profile_edit"]}, **kwargs
        )

    def assert_edit_access(self, allowed):
        profile = self.profile_response()
        self.assertEqual(profile.status_code, 200)
        edit_url = reverse("edit-profile")
        if allowed:
            self.assertContains(profile, f'href="{edit_url}"')
        else:
            self.assertNotContains(profile, f'href="{edit_url}"')
        editor = self.client.get(edit_url)
        if allowed:
            self.assertEqual(editor.status_code, 200)
            self.assertTemplateUsed(editor, "employee/profile/profile.html")
        else:
            self.assertTemplateNotUsed(editor, "employee/profile/profile.html")
        self.assertFalse(self.user.has_perm("employee.change_employee"))
        self.assertFalse(self.user.is_staff)

    def test_no_restriction_shows_edit_and_opens_form(self):
        self.assert_edit_access(True)

    def test_disabled_restriction_feature_does_not_hide_edit(self):
        ProfileEditFeature.objects.create(is_enabled=False)
        self.assert_edit_access(True)

    def test_enabled_rule_blocks_staff_not_on_allowlist(self):
        ProfileEditFeature.objects.create(is_enabled=True)
        self.restriction()
        self.assert_edit_access(False)

    def test_allowed_staff_can_edit_with_restrictions_enabled(self):
        ProfileEditFeature.objects.create(is_enabled=True)
        rule = self.restriction()
        rule.employees.add(self.employee)
        self.assert_edit_access(True)

    def test_exclude_all_overrides_allowlist(self):
        rule = self.restriction(exclude_all=True)
        rule.employees.add(self.employee)
        self.assert_edit_access(False)

    def test_disabled_access_rule_does_not_block_editing(self):
        self.restriction(is_enabled=False, exclude_all=True)
        self.assert_edit_access(True)

    def test_self_edit_action_is_not_shown_on_another_employee(self):
        response = self.profile_response(self.other_employee)
        self.assertNotContains(response, f'href="{reverse("edit-profile")}"')

    def test_restricted_post_cannot_change_personal_details(self):
        self.restriction(exclude_all=True)
        self.client.post(reverse("edit-profile"), {"employee_first_name": "Changed"})
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.employee_first_name, "Test")

    def test_allowed_post_updates_only_the_signed_in_employee(self):
        response = self.client.post(
            reverse("edit-profile"),
            {
                "employee_first_name": "Updated",
                "employee_last_name": self.employee.employee_last_name,
                "email": self.employee.email,
                "phone": self.employee.phone,
                "gender": self.employee.gender,
                # Posted identifiers must not select another employee/account.
                "employee_id": self.other_employee.pk,
                "employee_user_id": self.other_employee.employee_user_id_id,
                "is_staff": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].errors)
        self.employee.refresh_from_db()
        self.other_employee.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.employee.employee_first_name, "Updated")
        self.assertEqual(self.employee.employee_user_id_id, self.user.pk)
        self.assertEqual(self.other_employee.employee_first_name, "Test")
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.has_perm("employee.change_employee"))

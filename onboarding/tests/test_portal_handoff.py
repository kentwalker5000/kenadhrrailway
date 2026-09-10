"""Exercise the public portal across real requests, without sending email."""

from datetime import date
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from base.models import Department, JobPosition
from employee.models import Employee, EmployeeBankDetails
from horilla.testkit import clear_selected_company, make_company, make_employee
from horilla_documents.models import Document
from onboarding.models import CandidateStage, OnboardingPortal
from recruitment.models import Candidate, CandidateDocument, Recruitment, Stage


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class PortalHandoffTests(TestCase):
    password = "Portal-test-password-928!"

    def setUp(self):
        clear_selected_company()
        self.addCleanup(clear_selected_company)
        media = TemporaryDirectory(prefix="onboarding-test-")
        self.addCleanup(media.cleanup)
        media_override = override_settings(MEDIA_ROOT=media.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.company = make_company("Portal Handoff Co")
        self.department = Department.objects.create(department="Portal Engineering")
        self.department.company_id.add(self.company)
        self.position = JobPosition.objects.create(
            job_position="Portal Developer", department_id=self.department
        )
        self.recruitment = Recruitment.objects.create(
            title="Portal Recruitment",
            company_id=self.company,
            job_position_id=self.position,
            optional_resume=True,
        )
        self.recruitment.open_positions.add(self.position)
        self.candidate = Candidate.objects.create(
            name="Portal Candidate",
            email="portal-candidate@test.horilla",
            mobile="0241234567",
            recruitment_id=self.recruitment,
            job_position_id=self.position,
            joining_date=date(2026, 9, 1),
            start_onboard=True,
        )
        self.portal = OnboardingPortal.objects.create(
            candidate_id=self.candidate, token="portal-test-token"
        )

    def url(self, name, portal=None):
        return reverse(name, args=[(portal or self.portal).token])

    def account(self):
        response = self.client.post(
            self.url("user-creation"),
            {"password1": self.password, "password2": self.password},
        )
        self.assertRedirects(
            response, self.url("profile-view"), fetch_redirect_response=False
        )

    def personal_data(self):
        return {
            "employee_first_name": "Portal",
            "employee_last_name": "Candidate",
            "phone": "0241234567",
            "address": "1 Test Street",
            "country": "Ghana",
            "state": "Greater Accra",
            "zip": "00233",
            "gender": "male",
            "marital_status": "single",
            "qualification": "Degree",
            "experience": "2",
            "children": "0",
            "emergency_contact": "0241234568",
            "emergency_contact_name": "Test Contact",
            "emergency_contact_relation": "Sibling",
        }

    def bank_data(self):
        return {
            "bank_name": "Test Bank",
            "account_number": "123456789",
            "branch": "Accra",
            "address": "1 Bank Street",
            "country": "Ghana",
            "state": "Greater Accra",
            "city": "Accra",
            "any_other_code1": "TESTCODE",
        }

    def create_employee(self):
        self.account()
        response = self.client.post(self.url("employee-creation"), self.personal_data())
        self.assertRedirects(
            response, self.url("employee-bank-details"), fetch_redirect_response=False
        )
        return Employee.objects.get(email=self.candidate.email)

    def test_account_step_survives_a_different_worker(self):
        self.account()
        # A new worker has no module-local state; the browser only sends cookies.
        with patch("onboarding.views.portal_user", {}, create=True):
            other_worker_client = Client()
            other_worker_client.cookies = self.client.cookies
            response = other_worker_client.get(self.url("employee-creation"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Personal Details")

    def test_complete_flow_links_candidate_work_information_and_bank_details(self):
        original = CandidateDocument.objects.create(
            candidate_id=self.candidate,
            title="Candidate Identity",
            document=SimpleUploadedFile(
                "identity.pdf", b"%PDF-1.4\n%", content_type="application/pdf"
            ),
            status="approved",
        )
        employee = self.create_employee()
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.converted_employee_id, employee)
        work = employee.employee_work_info
        self.assertEqual(work.company_id, self.company)
        self.assertEqual(work.department_id, self.department)
        self.assertEqual(work.job_position_id, self.position)
        self.assertEqual(work.date_joining, self.candidate.joining_date)
        self.assertEqual(employee.employee_user_id.email, self.candidate.email)
        self.assertTrue(employee.employee_user_id.check_password(self.password))
        self.assertTrue(employee.employee_user_id.has_perm("employee.view_ownprofile"))
        self.assertTrue(
            employee.employee_user_id.has_perm("employee.change_ownprofile")
        )
        copied = Document.objects.get(employee_id=employee, title=original.title)
        self.assertEqual(copied.document.name, original.document.name)
        self.assertEqual(copied.status, original.status)
        response = self.client.post(self.url("employee-bank-details"), self.bank_data())
        self.assertRedirects(
            response, reverse("welcome-aboard"), fetch_redirect_response=False
        )
        self.portal.refresh_from_db()
        self.assertTrue(self.portal.used)
        self.assertEqual(self.portal.count, 4)
        self.assertEqual(employee.employee_bank_details.account_number, "123456789")

    def test_invalid_personal_details_show_errors_instead_of_crashing(self):
        self.account()
        response = self.client.post(self.url("employee-creation"), {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertFalse(Employee.objects.filter(email=self.candidate.email).exists())

    def test_invalid_bank_details_stay_on_the_form(self):
        employee = self.create_employee()
        response = self.client.post(self.url("employee-bank-details"), {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.portal.refresh_from_db()
        self.assertFalse(self.portal.used)
        self.assertFalse(
            EmployeeBankDetails.objects.filter(employee_id=employee).exists()
        )

    def test_revisiting_personal_details_resumes_bank_step_without_duplicates(self):
        employee = self.create_employee()
        for method in (self.client.get, self.client.post):
            response = method(self.url("employee-creation"))
            self.assertRedirects(
                response,
                self.url("employee-bank-details"),
                fetch_redirect_response=False,
            )
        self.assertEqual(Employee.objects.filter(email=employee.email).count(), 1)

    def test_used_portals_are_rejected_on_every_step(self):
        self.portal.used = True
        self.portal.save()
        for name in (
            "user-creation",
            "profile-view",
            "employee-creation",
            "employee-bank-details",
        ):
            for method in (self.client.get, self.client.post):
                with self.subTest(step=name, method=method.__name__):
                    self.assertEqual(method(self.url(name)).status_code, 404)

    def test_archived_or_canceled_candidates_cannot_use_the_portal(self):
        for updates in ({"is_active": False}, {"is_active": True, "canceled": True}):
            Candidate.objects.filter(pk=self.candidate.pk).update(**updates)
            for name in (
                "user-creation",
                "profile-view",
                "employee-creation",
                "employee-bank-details",
            ):
                with self.subTest(state=updates, step=name):
                    self.assertEqual(self.client.get(self.url(name)).status_code, 404)

    def test_existing_account_password_cannot_be_replaced_by_a_portal(self):
        user = get_user_model().objects.create_user(
            username=self.candidate.email,
            email=self.candidate.email,
            password="Original-password!",
        )
        response = self.client.post(
            self.url("user-creation"),
            {"password1": self.password, "password2": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        user.refresh_from_db()
        self.assertTrue(user.check_password("Original-password!"))
        self.portal.refresh_from_db()
        self.assertEqual(self.portal.count, 0)

    def test_bank_step_cannot_modify_another_signed_in_employee(self):
        employee = self.create_employee()
        other = self.make_existing_employee("other@test.horilla")
        self.client.force_login(other.employee_user_id)
        response = self.client.post(self.url("employee-bank-details"), self.bank_data())
        self.assertEqual(response.status_code, 403)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.converted_employee_id, employee)
        self.assertFalse(EmployeeBankDetails.objects.filter(employee_id=other).exists())

    def test_bank_step_requires_personal_details_first(self):
        response = self.client.get(self.url("employee-bank-details"))
        self.assertRedirects(
            response, self.url("user-creation"), fetch_redirect_response=False
        )
        self.assertFalse(EmployeeBankDetails.objects.exists())

    def test_pending_accounts_are_separate_for_each_candidate(self):
        self.account()
        other = Candidate.objects.create(
            name="Other Candidate",
            email="second@test.horilla",
            recruitment_id=self.recruitment,
            job_position_id=self.position,
        )
        other_portal = OnboardingPortal.objects.create(
            candidate_id=other, token="second-token"
        )
        response = self.client.get(self.url("employee-creation", other_portal))
        self.assertRedirects(
            response,
            self.url("user-creation", other_portal),
            fetch_redirect_response=False,
        )

    def test_employee_creation_failure_rolls_back_user_and_employee(self):
        from django.db import IntegrityError

        self.account()
        with patch(
            "onboarding.views.EmployeeWorkInformation.objects.update_or_create",
            side_effect=IntegrityError("simulated work information failure"),
        ):
            response = self.client.post(
                self.url("employee-creation"), self.personal_data()
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            get_user_model().objects.filter(username=self.candidate.email).exists()
        )
        self.assertFalse(Employee.objects.filter(email=self.candidate.email).exists())
        self.portal.refresh_from_db()
        self.assertEqual(self.portal.count, 1)

    def test_expired_session_requires_login_to_resume_bank_details(self):
        employee = self.create_employee()
        self.client.logout()
        response = self.client.get(self.url("employee-bank-details"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)
        self.client.force_login(employee.employee_user_id)
        self.assertEqual(
            self.client.get(self.url("employee-bank-details")).status_code, 200
        )

    def login_hr(self):
        user = get_user_model().objects.create_superuser(
            username="portal-hr", email="portal-hr@test.horilla", password="test-only"
        )
        make_employee(company=self.company, email=user.email, user=user)
        self.client.force_login(user)

    def make_existing_employee(self, email):
        # These users have already set their passwords. Auto-created employee
        # accounts are correctly intercepted by ForcePasswordChangeMiddleware.
        user = get_user_model().objects.create_user(
            username=email, email=email, password="Existing-account-test-982!"
        )
        return make_employee(company=self.company, email=email, user=user)

    def test_start_onboarding_needs_no_mail_and_preserves_portal_progress(self):
        self.login_hr()
        self.portal.count = 2
        self.portal.save()
        with patch("onboarding.views.ConfiguredEmailBackend") as backend:
            for _ in range(2):
                response = self.client.post(
                    reverse("email-send") + "?no_portal=True",
                    {"ids": [self.candidate.pk]},
                )
                self.assertLess(response.status_code, 400)
            backend.assert_not_called()
        self.portal.refresh_from_db()
        self.candidate.refresh_from_db()
        self.assertEqual(self.portal.count, 2)
        self.assertEqual(self.portal.token, "portal-test-token")
        self.assertTrue(self.candidate.start_onboard)
        self.assertEqual(
            CandidateStage.objects.filter(candidate_id=self.candidate).count(), 1
        )

    def test_resending_portal_preserves_link_and_progress(self):
        self.login_hr()
        self.portal.count = 2
        self.portal.save()
        with (
            patch("onboarding.views.ConfiguredEmailBackend"),
            patch("onboarding.views.EmailMultiAlternatives") as email,
        ):
            email.return_value.send.return_value = 1
            response = self.client.post(
                reverse("email-send"), {"ids": [self.candidate.pk]}
            )
        self.assertLess(response.status_code, 400)
        email.return_value.send.assert_called_once()
        self.portal.refresh_from_db()
        self.assertEqual(self.portal.count, 2)
        self.assertEqual(self.portal.token, "portal-test-token")

    def test_failed_invitation_does_not_start_onboarding(self):
        self.login_hr()
        Candidate.objects.filter(pk=self.candidate.pk).update(start_onboard=False)
        with (
            patch("onboarding.views.ConfiguredEmailBackend"),
            patch("onboarding.views.EmailMultiAlternatives") as email,
        ):
            email.return_value.send.return_value = 0
            response = self.client.post(
                reverse("email-send"), {"ids": [self.candidate.pk]}
            )
        self.assertLess(response.status_code, 400)
        self.candidate.refresh_from_db()
        self.portal.refresh_from_db()
        self.assertFalse(self.candidate.start_onboard)
        self.assertEqual(self.portal.token, "portal-test-token")
        self.assertFalse(
            CandidateStage.objects.filter(candidate_id=self.candidate).exists()
        )

    def test_hired_candidate_is_available_to_hr_and_enters_the_pipeline(self):
        self.login_hr()
        hired = Stage.objects.create(
            recruitment_id=self.recruitment,
            stage="Hired",
            stage_type="hired",
            sequence=10,
        )
        self.candidate.stage_id = hired
        self.candidate.start_onboard = False
        self.candidate.save()
        self.assertTrue(self.candidate.hired)
        response = self.client.get(reverse("candidates-view"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.candidate, response.context["hired_candidates"])
        self.client.post(
            reverse("email-send") + "?no_portal=True", {"ids": [self.candidate.pk]}
        )
        response = self.client.get(reverse("onboarding-dashboard-stages"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sum(stage["count"] for stage in response.json()["stages"]), 1)

    def test_authorized_hr_can_start_onboarding_without_superuser_access(self):
        hr = self.make_existing_employee("hr-staff@test.horilla")
        hr.employee_user_id.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="recruitment", codename="view_recruitment"
            )
        )
        self.client.force_login(hr.employee_user_id)
        response = self.client.post(
            reverse("email-send") + "?no_portal=True", {"ids": [self.candidate.pk]}
        )
        self.assertLess(response.status_code, 400)
        self.assertTrue(
            CandidateStage.objects.filter(candidate_id=self.candidate).exists()
        )

    def test_manager_cannot_start_candidates_from_an_unmanaged_recruitment(self):
        manager = self.make_existing_employee("manager@test.horilla")
        other_recruitment = Recruitment.objects.create(
            title="Other Recruitment",
            company_id=self.company,
            job_position_id=self.position,
            start_date=date(2026, 8, 1),
        )
        other_recruitment.recruitment_managers.add(manager)
        self.client.force_login(manager.employee_user_id)
        response = self.client.post(
            reverse("email-send") + "?no_portal=True", {"ids": [self.candidate.pk]}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            CandidateStage.objects.filter(candidate_id=self.candidate).exists()
        )

    def test_account_progress_contains_no_plaintext_password(self):
        self.account()
        session_data = str(dict(self.client.session))
        self.assertNotIn(self.password, session_data)

    def test_unknown_portals_are_rejected_on_every_step(self):
        for name in (
            "user-creation",
            "profile-view",
            "employee-creation",
            "employee-bank-details",
        ):
            with self.subTest(step=name):
                self.assertEqual(
                    self.client.get(reverse(name, args=["invalid-token"])).status_code,
                    404,
                )

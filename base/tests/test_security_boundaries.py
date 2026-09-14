"""Tenant boundaries apply to the admin site, ORM and raw file downloads."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings

from base.media_access import can_download
from employee.models import EmployeeWorkInformation
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from horilla_documents.models import Document


@override_settings(
    TWO_FACTORS_AUTHENTICATION=False,
    KENADHR_PLATFORM_DEVELOPER_USERNAMES=["security-developer"],
)
class SecurityBoundaryTests(TestCase):
    def setUp(self):
        _thread_locals.request = None
        set_selected_company(None)
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.addCleanup(set_selected_company, None)
        self.company = make_company("Security A")
        self.foreign = make_company("Security B", hq=False)
        self.owner = make_user("security-owner", is_superuser=True)
        self.employee = make_employee(
            company=self.company, email="owner@test.horilla", user=self.owner
        )
        self.staff = make_user("security-staff")
        self.staff_employee = make_employee(
            company=self.company, email="staff@test.horilla", user=self.staff
        )
        self.other = make_employee(company=self.foreign, email="foreign@test.horilla")
        self.developer = make_user("security-developer", is_superuser=True)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.media_root = Path(directory.name)
        override = override_settings(MEDIA_ROOT=directory.name)
        override.enable()
        self.addCleanup(override.disable)
        for filename, employee in (
            ("owner.txt", self.employee),
            ("staff.txt", self.staff_employee),
            ("foreign.txt", self.other),
        ):
            (self.media_root / filename).write_text(filename)
            Document.objects.create(
                title="Private document", employee_id=employee, document=filename
            )
        (self.media_root / "orphan.txt").write_text("not registered")

    def test_company_owner_cannot_enter_platform_admin(self):
        self.client.force_login(self.owner)
        for url in (
            "/admin/",
            f"/admin/base/company/{self.foreign.pk}/change/",
            f"/admin/horilla_auth/horillauser/{self.developer.pk}/change/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/admin/login/", response.url)

    def test_platform_developer_retains_admin(self):
        self.client.force_login(self.developer)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_owner_can_read_own_company_but_not_foreign_or_orphan_file(self):
        self.client.force_login(self.owner)
        response = self.client.get("/media/staff.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"staff.txt")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        for name in ("foreign.txt", "orphan.txt"):
            self.assertEqual(self.client.get("/media/" + name).status_code, 404)

    def test_staff_can_read_own_file_not_colleague_file(self):
        self.client.force_login(self.staff)
        response = self.client.get("/media/staff.txt")
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        self.assertEqual(self.client.get("/media/owner.txt").status_code, 404)
        self.assertEqual(self.client.get("/media/foreign.txt").status_code, 404)

    def test_bearer_download_uses_same_tenant_policy(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(self.owner)
        refresh["company_id"] = self.company.pk
        token = str(refresh.access_token)
        response = self.client.get(
            "/media/staff.txt", HTTP_AUTHORIZATION="Bearer " + token
        )
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        self.assertEqual(
            self.client.get(
                "/media/foreign.txt", HTTP_AUTHORIZATION="Bearer " + token
            ).status_code,
            404,
        )

    def test_only_registered_company_icon_is_public(self):
        (self.media_root / "logo.png").write_bytes(b"image")
        (self.media_root / "unregistered.png").write_bytes(b"image")
        self.company.icon = "logo.png"
        self.company.save(update_fields=["icon"])
        response = self.client.get("/media/logo.png")
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        self.assertEqual(self.client.get("/media/unregistered.png").status_code, 302)

    def test_profiles_still_visible_within_company(self):
        from employee.models import Employee

        Employee._base_manager.filter(pk=self.staff_employee.pk).update(
            employee_profile="profile.png"
        )
        self.assertTrue(can_download(self.owner, "profile.png"))
        self.assertFalse(can_download(self.other.employee_user_id, "profile.png"))

    def test_web_orm_bulk_company_bypass_is_blocked(self):
        _thread_locals.request = SimpleNamespace(user=self.owner)
        with self.assertRaises(ValidationError):
            EmployeeWorkInformation._base_manager.filter(
                employee_id=self.employee
            ).update(company_id=self.foreign)

    def test_note_attachments_inherit_parent_access(self):
        from employee.models import EmployeeNote, NoteFiles

        attachment = NoteFiles.objects.create(files="note.txt")
        note = EmployeeNote.objects.create(
            employee_id=self.staff_employee,
            updated_by=self.employee,
            description="A private note",
        )
        note.note_files.add(attachment)
        self.assertTrue(can_download(self.owner, "note.txt"))
        self.assertTrue(can_download(self.staff, "note.txt"))
        self.assertFalse(can_download(self.other.employee_user_id, "note.txt"))

    def test_pdf_assets_cannot_read_foreign_media(self):
        from payroll.pdf import EMPTY_IMAGE, render_payslip_html

        request = RequestFactory().get("/")
        request.user = self.owner
        with patch(
            "payroll.pdf.pisa.CreatePDF", return_value=SimpleNamespace(err=0)
        ) as render:
            render_payslip_html("<h1>Document</h1>", request=request)
        callback = render.call_args.kwargs["link_callback"]
        self.assertEqual(callback("/media/foreign.txt", None), EMPTY_IMAGE)
        self.assertEqual(
            callback("/media/staff.txt", None), str(self.media_root / "staff.txt")
        )

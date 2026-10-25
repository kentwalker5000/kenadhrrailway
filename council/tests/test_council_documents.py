import tempfile

from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from base.models import Company
from council.models import CouncilDocument, CouncilLibraryFolder, CouncilMember
from horilla.testkit import make_employee, make_user


class CouncilDocumentAccessTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_root.cleanup)
        self.company = Company.objects.create(company="Council Test Company", hq=True)
        self.manager = make_user("council-manager")
        make_employee(company=self.company, user=self.manager, email="manager@example.test")
        self.viewer = make_user("council-viewer")
        make_employee(company=self.company, user=self.viewer, email="viewer@example.test")
        self.member = CouncilMember.objects.create(full_name="Ama Mensah", company_id=self.company)
        self.view_permission = Permission.objects.get(
            content_type__app_label="council", codename="view_councildocument"
        )
        self.change_permission = Permission.objects.get(
            content_type__app_label="council", codename="change_councildocument"
        )
        self.manager.user_permissions.add(self.change_permission)
        self.viewer.user_permissions.add(self.view_permission)

    def upload(self, name="minutes.pdf"):
        return SimpleUploadedFile(name, b"council test document", content_type="application/pdf")

    def test_private_member_document_requires_document_manager(self):
        with override_settings(MEDIA_ROOT=self.media_root.name):
            document = CouncilDocument.objects.create(
                title="Appointment letter", member=self.member, document=self.upload()
            )
            self.client.force_login(self.viewer)
            response = self.client.get(reverse("council-document-download", args=[document.pk]))
        self.assertEqual(response.status_code, 404)

    def test_shared_folder_document_is_available_to_authorised_viewer(self):
        with override_settings(MEDIA_ROOT=self.media_root.name):
            folder = CouncilLibraryFolder.objects.create(
                name="Approved minutes", company_id=self.company
            )
            document = CouncilDocument.objects.create(
                title="March minutes", folder=folder, document=self.upload()
            )
            self.client.force_login(self.viewer)
            response = self.client.get(reverse("council-document-download", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"council test document")

    def test_restricted_folder_requires_an_explicit_group_or_user(self):
        with override_settings(MEDIA_ROOT=self.media_root.name):
            folder = CouncilLibraryFolder.objects.create(
                name="Confidential papers",
                company_id=self.company,
                access_level=CouncilLibraryFolder.ACCESS_RESTRICTED,
            )
            document = CouncilDocument.objects.create(
                title="Confidential paper", folder=folder, document=self.upload()
            )
            self.client.force_login(self.viewer)
            denied = self.client.get(reverse("council-document-download", args=[document.pk]))
            group = Group.objects.create(name="Council secretariat")
            group.user_set.add(self.viewer)
            folder.allowed_groups.add(group)
            allowed = self.client.get(reverse("council-document-download", args=[document.pk]))
            library = self.client.get(reverse("council-library"))
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(library, folder.name)

    def test_document_must_have_one_parent(self):
        document = CouncilDocument(title="Orphan", document=self.upload())
        with self.assertRaisesMessage(ValidationError, "exactly one"):
            document.full_clean()

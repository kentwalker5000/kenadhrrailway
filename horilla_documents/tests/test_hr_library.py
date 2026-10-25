from tempfile import TemporaryDirectory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from base.models import Company
from horilla.testkit import make_employee, make_user
from horilla_documents.models import HRDocumentFolder, HRLibraryDocument


class HRDocumentLibraryTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings_override = override_settings(MEDIA_ROOT=media.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.company = Company.objects.create(company="Document Library QA")
        self.user = make_user("document-library-owner", is_superuser=True)
        make_employee(company=self.company, user=self.user, email="documents@example.test")
        self.client.force_login(self.user)
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()
        self.folder = HRDocumentFolder._base_manager.create(
            company_id=self.company, name="Policies", description="Current policies"
        )

    def test_library_uses_shared_toolbar_and_compact_action_controls(self):
        response = self.client.get(reverse("hr-document-library"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="hrDocumentLibraryContent"')
        self.assertContains(response, 'data-target="#objectCreateModal"')
        self.assertContains(response, 'document-upload-mark document-action-icon__fallback')
        self.assertContains(response, 'document-edit-mark document-action-icon__fallback')
        self.assertContains(response, 'document-delete-mark document-action-icon__fallback')

    def test_search_returns_only_library_content_fragment(self):
        response = self.client.get(
            reverse("hr-document-library") + "?search=Policies", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Policies")
        self.assertNotContains(response, 'id="ohMainContent"')

    def test_search_finds_a_document_inside_a_differently_named_folder(self):
        HRLibraryDocument._base_manager.create(
            folder=self.folder,
            company_id=self.company,
            title="Remote-work policy",
            document=SimpleUploadedFile("remote-work-policy.pdf", b"test", "application/pdf"),
        )
        response = self.client.get(
            reverse("hr-document-library") + "?search=Remote-work", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Policies")
        self.assertContains(response, "Remote-work policy")

    def test_sidebar_navigation_gets_the_complete_page(self):
        response = self.client.get(
            reverse("hr-document-library"),
            HTTP_HX_REQUEST="true",
            HTTP_HX_SIDEBAR_NAV="true",
        )
        self.assertContains(response, 'id="ohMainContent"')
        self.assertContains(response, 'id="hrDocumentLibraryContent"')

    def test_modal_folder_create_saves_and_redirects_to_library(self):
        create_url = reverse("hr-document-folder-create")
        modal = self.client.get(create_url, HTTP_HX_REQUEST="true")
        self.assertEqual(modal.status_code, 200)
        self.assertContains(modal, 'hx-target="#objectCreateModalTarget"')
        response = self.client.post(
            create_url, {"name": "Compliance", "description": "Audit material"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("hr-document-library"))
        self.assertTrue(HRDocumentFolder.objects.filter(name="Compliance").exists())

    def test_duplicate_folder_returns_validation_in_modal(self):
        response = self.client.post(reverse("hr-document-folder-create"),
                                    {"name": "Policies"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertEqual(HRDocumentFolder.objects.filter(name="Policies").count(), 1)

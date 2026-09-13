"""KenadHr branding stays consistent without renaming tenant or account data."""

import importlib
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.template import Context, Engine
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils.translation import override
from openpyxl import load_workbook
from PIL import Image

from base.context_processors import white_labelling_company
from horilla.testkit import make_company, make_employee, make_user
from horilla_auth.models import HorillaUser
from report.export import export_xlsx


class ProductBrandingTests(SimpleTestCase):
    @override_settings(WHITE_LABELLING=False)
    def test_default_product_name_uses_exact_spelling(self):
        request = RequestFactory().get("/login/")
        request.user = AnonymousUser()
        for language in ("en", "fr", "es", "de", "ar"):
            with override(language):
                self.assertEqual(white_labelling_company(request)["white_label_company_name"], "KenadHr")

    def test_internal_system_account_name_is_not_renamed(self):
        bot = HorillaUser(username="Horilla Bot")
        self.assertEqual(bot.username, "Horilla Bot")
        self.assertEqual(str(bot), "KenadHr System")
        self.assertEqual(bot.get_full_name(), "KenadHr System")
        self.assertTrue(bot.is_system_actor)
        person = HorillaUser(username="ama", first_name="Ama", last_name="Mensah")
        self.assertEqual(str(person), "ama")
        self.assertEqual(person.get_full_name(), "Ama Mensah")
        self.assertFalse(person.is_system_actor)

    def test_admin_uses_product_name(self):
        self.assertEqual(admin.site.site_title, "KenadHr")
        self.assertEqual(admin.site.site_header, "KenadHr Administration")

    def test_pwa_icons_match_declared_sizes_and_have_new_name(self):
        root = Path(settings.BASE_DIR)
        manifest = json.loads((root / "static/build/manifest.json").read_text())
        self.assertEqual(manifest["name"], "KenadHr")
        self.assertEqual(manifest["short_name"], "KenadHr")
        for icon in manifest["icons"]:
            with Image.open(root / icon["src"].lstrip("/")) as image:
                self.assertEqual(f"{image.width}x{image.height}", icon["sizes"])
        for size in (16, 32, 180):
            with Image.open(root / f"static/favicons/kenadhr-{size}.png") as image:
                self.assertEqual(image.size, (size, size))

    def test_report_default_branding_and_document_metadata(self):
        payload = {"table": {"columns": [{"key": "count", "label": "Count"}], "rows": [{"count": 1}]}}
        workbook = load_workbook(io.BytesIO(export_xlsx(payload, meta={"company": {"name": "IoD-Gh"}}).content))
        self.assertEqual(workbook.properties.creator, "IoD-Gh")
        self.assertEqual(workbook.properties.title, "KenadHr Report")
        contents = " ".join(str(cell.value) for sheet in workbook for row in sheet for cell in row if cell.value)
        self.assertIn("KenadHr", contents)
        self.assertNotIn("Horilla", contents)

    def test_templates_do_not_display_old_brand_or_use_old_fallback_logos(self):
        root = Path(settings.BASE_DIR)
        roots = [root / "templates"] + [path for path in root.glob("*/templates") if path.parent.name != "notifications"]
        failures = []
        for directory in roots:
            for template in directory.rglob("*.html"):
                if template.relative_to(root).as_posix() == "templates/legal/open_source_notices.html":
                    continue
                content = template.read_text(encoding="utf-8")
                content = re.sub(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}|{#.*?#}|<!--.*?-->", "", content, flags=re.S)
                content = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", content, flags=re.S | re.I)
                if re.search(r"\bHorilla\b|Kenad HR|KenadHR|(?:auth-logo|horilla-logo)\.png", content):
                    failures.append(str(template.relative_to(root)))
        self.assertEqual(failures, [])

    def test_setup_templates_render_new_brand_and_valid_logo_source(self):
        root = Path(settings.BASE_DIR)
        engine = Engine(dirs=[root / "templates"], libraries={"static": "django.templatetags.static", "i18n": "django.templatetags.i18n"})
        for name in ("templates/initialize_database/horilla_company.html", "templates/initialize_database/horilla_department.html"):
            html = engine.from_string((root / name).read_text(encoding="utf-8")).render(Context({"request": RequestFactory().get("/")}))
            self.assertIn("KenadHr", html)
            self.assertNotIn("Horilla", html)


class CompanyBrandingPreservationTests(TestCase):
    @override_settings(WHITE_LABELLING=True)
    def test_company_name_is_preserved(self):
        company = make_company("IoD-Gh")
        user = make_user("branding-owner")
        make_employee(company=company, email="branding-owner@test.horilla", user=user)
        request = RequestFactory().get("/")
        request.user = user
        self.assertEqual(white_labelling_company(request)["white_label_company_name"], "IoD-Gh")
        company.refresh_from_db()
        self.assertEqual(company.company, "IoD-Gh")

    def test_tour_migration_preserves_custom_copy_and_progress(self):
        from horilla_tour.models import Tour, TourStep

        migration = importlib.import_module("horilla_tour.migrations.0088_rebrand_default_tours")
        default = Tour.objects.get(slug="dashboard-overview", company_id=None)
        original = migration.TOUR_COPY[0][2]
        Tour.objects.filter(pk=default.pk).update(description=original)
        step = TourStep.objects.filter(tour=default).first()
        TourStep.objects.filter(pk=step.pk).update(description="Our custom Horilla training notes")
        step_ids = list(default.steps.values_list("pk", flat=True))
        migration.forwards(apps, SimpleNamespace(connection=connection))
        default.refresh_from_db()
        step.refresh_from_db()
        self.assertEqual(default.description, original.replace("Horilla", "KenadHr"))
        self.assertEqual(step.description, "Our custom Horilla training notes")
        self.assertEqual(list(default.steps.values_list("pk", flat=True)), step_ids)

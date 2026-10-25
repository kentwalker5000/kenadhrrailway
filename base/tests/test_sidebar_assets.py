"""Prevent broken menu icons from being shipped in sidebar configuration."""

from importlib import import_module
import base64
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase
from django.template import Context, Template

from horilla_theme.templatetags.sidebar_icons import sidebar_icon_uri


class SidebarAssetTests(SimpleTestCase):
    def test_every_configured_sidebar_icon_exists(self):
        for app in settings.SIDEBARS:
            with self.subTest(app=app):
                sidebar = import_module(f"{app}.sidebar")
                asset = getattr(sidebar, "IMG_SRC", "")
                self.assertTrue(asset, f"{app} has no sidebar icon")
                self.assertIsNotNone(finders.find(asset), f"Missing menu icon: {asset}")

    def test_dashboard_icon_exists(self):
        self.assertIsNotNone(finders.find("images/ui/dashboard.svg"))

    def test_all_menu_images_are_embedded_from_the_real_assets(self):
        assets = {"images/ui/dashboard.svg"}
        assets.update(import_module(f"{app}.sidebar").IMG_SRC for app in settings.SIDEBARS)
        for asset in assets:
            with self.subTest(asset=asset):
                uri = sidebar_icon_uri(asset)
                self.assertTrue(uri.startswith("data:image/"))
                self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), Path(finders.find(asset)).read_bytes())

    def test_template_tag_renders_an_embedded_icon(self):
        rendered = Template("{% load sidebar_icons %}{% sidebar_icon_uri asset %}").render(
            Context({"asset": "images/ui/dashboard.svg"})
        )
        self.assertTrue(rendered.startswith("data:image/svg+xml;base64,"))

    def test_missing_asset_uses_an_embedded_fallback(self):
        uri = sidebar_icon_uri("images/ui/nonexistent-menu-icon.svg")
        self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))
        self.assertIn(b"<svg", base64.b64decode(uri.split(",", 1)[1]))

    def test_untrusted_paths_are_never_read(self):
        with patch("horilla_theme.templatetags.sidebar_icons.finders.find") as find:
            for asset in ["../secret.svg", "/media/photo.png", "images/ui/../../secret.svg", "https://example.invalid/icon.svg"]:
                self.assertTrue(sidebar_icon_uri(asset).startswith("data:image/svg+xml;base64,"))
            find.assert_not_called()

    def test_assets_are_cached_between_page_renders(self):
        sidebar_icon_uri.cache_clear()
        with patch("horilla_theme.templatetags.sidebar_icons.finders.find", wraps=finders.find) as find:
            sidebar_icon_uri("images/ui/dashboard.svg")
            sidebar_icon_uri("images/ui/dashboard.svg")
            find.assert_called_once()

    def test_icon_only_action_buttons_have_a_visible_fallback(self):
        index = Path(settings.BASE_DIR / "horilla_theme/templates/index.html").read_text(
            encoding="utf-8"
        )
        footer = Path(
            settings.BASE_DIR / "horilla_theme/templates/horilla_theme/components/footer_scripts.html"
        ).read_text(encoding="utf-8")
        self.assertIn(".oh-btn ion-icon:not(.hydrated)::before", index)
        for name in ["create", "trash", "checkmark", "close", "add", "copy", "download"]:
            self.assertIn(f'ion-icon[name*="{name}"]', index)
        self.assertIn('customElements.get("ion-icon")', footer)
        self.assertIn('script.dataset.ioniconsFallback', footer)

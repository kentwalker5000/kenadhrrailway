"""Production-only Django security defaults."""

from django.test import SimpleTestCase

from horilla.settings.security import apply_secure_defaults


class DefaultEnvironment:
    def __call__(self, _key, default=None):
        return default

    def bool(self, _key, default=False):
        return default

    def int(self, _key, default=0):
        return default


class ProductionSecurityDefaultsTests(SimpleTestCase):
    def test_production_denies_framing_by_default(self):
        settings = apply_secure_defaults(DefaultEnvironment(), debug=False)

        self.assertEqual(settings["X_FRAME_OPTIONS"], "DENY")
        self.assertTrue(settings["SESSION_COOKIE_SECURE"])
        self.assertTrue(settings["CSRF_COOKIE_SECURE"])

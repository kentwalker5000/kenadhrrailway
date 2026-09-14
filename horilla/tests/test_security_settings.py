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
        self.assertTrue(settings["SECURE_SSL_REDIRECT"])

    def test_production_rejects_weak_secrets(self):
        from django.core.exceptions import ImproperlyConfigured
        from horilla.settings.security import validate_production_secrets

        strong_key = "aB3!x9-" * 9
        for key, hosts, bootstrap in (
            ("default", ["kenadhr.com"], "strong-bootstrap-secret"),
            (strong_key, ["*"], "strong-bootstrap-secret"),
            (strong_key, ["kenadhr.com"], "kenad"),
        ):
            with self.assertRaises(ImproperlyConfigured):
                validate_production_secrets(key, hosts, bootstrap)
        validate_production_secrets(strong_key, ["kenadhr.com"], "strong-bootstrap-secret")

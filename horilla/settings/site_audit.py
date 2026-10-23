"""Isolated settings for the repeatable navigation audit; never serve the app with these."""

from . import *  # noqa: F403

# A separate database allows the audit to run beside the normal regression suite.
DATABASES = {
    alias: {
        **config,
        "TEST": {**config.get("TEST", {}), "NAME": f"test_{config['NAME']}_siteaudit"},
    }
    for alias, config in DATABASES.items()
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
TWO_FACTORS_AUTHENTICATION = False
SITE_AUDIT_REPORT = BASE_DIR / "tmp" / "site-navigation-audit.json"

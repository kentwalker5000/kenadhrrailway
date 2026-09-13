import logging
import runpy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from django.conf import settings
from django.test import SimpleTestCase

from horilla.access_logging import CredentialSafeLogger
from horilla.credential_urls import redact_reset_urls
from horilla.observability import RequestIDFilter, _before_send


class ResetURLLoggingTests(SimpleTestCase):
    def test_reset_credentials_are_removed_from_log_messages(self):
        record = logging.LogRecord("django.request", logging.WARNING, "", 0,
                                   "Forbidden: %s", ("/accounts/reset/abc/secret-token/",), None)
        RequestIDFilter().filter(record)
        self.assertNotIn("secret-token", record.getMessage())
        self.assertNotIn("abc", record.getMessage())
        self.assertIn("[redacted]", record.getMessage())

    def test_gunicorn_request_line_and_referrer_are_redacted(self):
        logger = object.__new__(CredentialSafeLogger)
        response = SimpleNamespace(status=200, sent=10, headers=[])
        environ = {"REQUEST_METHOD": "GET", "RAW_URI": "/accounts/reset/abc/secret-token/",
                   "PATH_INFO": "/accounts/reset/abc/secret-token/", "SERVER_PROTOCOL": "HTTP/1.1",
                   "HTTP_REFERER": "https://www.kenadhr.com/accounts/reset/abc/secret-token/"}
        atoms = logger.atoms(response, [], environ, timedelta(seconds=1))
        for value in atoms.values():
            self.assertNotIn("secret-token", str(value))

    def test_error_tracking_urls_are_redacted(self):
        event = _before_send({"request": {"url": "https://www.kenadhr.com/accounts/reset/abc/secret-token/"}}, None)
        self.assertNotIn("secret-token", event["request"]["url"])

    def test_noncredential_paths_are_unchanged(self):
        for path in ("/accounts/reset/done/", "/forgot-password/", "/payroll/view-payslip/"):
            self.assertEqual(redact_reset_urls(path), path)

    def test_gunicorn_reload_adopts_new_logger_class(self):
        hook = runpy.run_path(str(Path(settings.BASE_DIR) / "docker/gunicorn.conf.py"))["on_reload"]
        initialized = Mock()

        class NewLogger:
            def __init__(self, config):
                initialized(config)

        config = SimpleNamespace(logger_class=NewLogger)
        server = SimpleNamespace(log=object(), cfg=config)
        hook(server)
        self.assertIsInstance(server.log, NewLogger)
        initialized.assert_called_once_with(config)
        # Further reloads must not duplicate handlers or replace the same logger.
        existing = server.log
        hook(server)
        self.assertIs(server.log, existing)
        initialized.assert_called_once()

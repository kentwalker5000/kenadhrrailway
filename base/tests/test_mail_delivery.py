"""Mail tests never use SMTP; verify connection setup and truthful send feedback."""

import smtplib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib import messages
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from base.backends import DefaultHorillaMailBackend
from base.models import Company, DynamicEmailConfiguration
from horilla.horilla_middlewares import _thread_locals
from horilla.testkit import (
    CompanyFilterTestMixin,
    make_company,
    make_employee,
    make_user,
)


class MailConnectionConfigurationTests(SimpleTestCase):
    def configuration(self, **overrides):
        values = dict(
            host="smtp.example.com", port=465,
            username="sender@example.com", password="test-only-password",
            use_tls=False, use_ssl=True, fail_silently=True, timeout=30,
            from_email="sender@example.com", display_name="KenadHr",
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_selected_server_is_applied_before_smtp_initialization(self):
        config = self.configuration()
        with patch.object(DefaultHorillaMailBackend, "get_dynamic_email_config") as lookup:
            backend = DefaultHorillaMailBackend(configuration=config)
        lookup.assert_not_called()
        for attribute, expected in (
            ("host", config.host), ("port", 465), ("username", config.username),
            ("password", config.password), ("use_ssl", True), ("use_tls", False),
            ("timeout", 30),
        ):
            self.assertEqual(getattr(backend, attribute), expected)

    def test_explicit_failure_handling_overrides_saved_setting(self):
        for saved, explicit in ((True, False), (False, True)):
            with self.subTest(saved=saved, explicit=explicit):
                backend = DefaultHorillaMailBackend(
                    configuration=self.configuration(fail_silently=saved),
                    fail_silently=explicit,
                )
                self.assertEqual(backend.fail_silently, explicit)

    def test_saved_failure_setting_is_used_without_an_override(self):
        backend = DefaultHorillaMailBackend(configuration=self.configuration())
        self.assertTrue(backend.fail_silently)

    def test_missing_timeout_is_bounded_and_explicit_timeout_is_respected(self):
        config = self.configuration(timeout=None)
        self.assertEqual(DefaultHorillaMailBackend(configuration=config).timeout, 30)
        self.assertEqual(
            DefaultHorillaMailBackend(configuration=config, timeout=12).timeout, 12
        )

    def test_default_server_lookup_still_works(self):
        config = self.configuration()
        with patch.object(
            DefaultHorillaMailBackend, "get_dynamic_email_config", return_value=config
        ) as lookup:
            backend = DefaultHorillaMailBackend()
        lookup.assert_called_once_with()
        self.assertIs(backend.configuration, config)

    def test_explicit_message_connection_does_not_initialize_a_different_server(self):
        from django.core.mail import EmailMultiAlternatives

        connection = DefaultHorillaMailBackend(configuration=self.configuration())
        with patch("base.backends.DefaultHorillaMailBackend") as unrelated_backend:
            message = EmailMultiAlternatives(
                "Reset your password - KenadHr", "Synthetic", "sender@example.com",
                ["recipient@example.com"], connection=connection,
            )
        unrelated_backend.assert_not_called()
        self.assertIs(message.connection, connection)


@override_settings(WHITE_LABELLING=False, STATIC_ROOT=Path(settings.BASE_DIR) / "static")
class MailServerTestViewTests(CompanyFilterTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Mail Company")
        cls.other_company = make_company("Other Mail Company")
        cls.user = make_user("mail-settings-admin", is_superuser=True)
        make_employee(company=cls.company, email="mail-admin@example.com", user=cls.user)
        config_values = dict(
            host="smtp.example.com", port=465, username="sender@example.com",
            password="test-only-password", from_email="sender@example.com",
            display_name="KenadHr", use_tls=False, use_ssl=True,
            timeout=30, fail_silently=True,
        )
        cls.config = DynamicEmailConfiguration.objects.create(
            company_id=cls.company, **config_values
        )
        cls.other_config = DynamicEmailConfiguration.objects.create(
            company_id=cls.other_company, **config_values
        )

    def setUp(self):
        self.clear_company_context()
        _thread_locals.request = None
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.client.force_login(self.user)
        self.send_patch = patch("base.views.EmailMultiAlternatives.send", return_value=1)
        self.send = self.send_patch.start()
        self.addCleanup(self.send_patch.stop)

    def submit(self, instance_id=None, recipient="recipient@example.com"):
        instance_id = self.config.pk if instance_id is None else instance_id
        return self.client.post(
            reverse("mail-server-test-email") + f"?instance_id={instance_id}",
            {"to_email": recipient}, HTTP_HX_REQUEST="true",
            HTTP_REFERER="http://testserver/settings/mail-server-conf/",
        )

    def feedback(self, response):
        return [(item.level, str(item)) for item in get_messages(response.wsgi_request)]

    def assert_failed(self, response):
        feedback = self.feedback(response)
        self.assertTrue(any(level == messages.ERROR for level, _ in feedback), feedback)
        self.assertFalse(any(level == messages.SUCCESS for level, _ in feedback), feedback)
        return " ".join(text for _, text in feedback)

    def test_success_requires_server_acceptance(self):
        feedback = self.feedback(self.submit())
        self.send.assert_called_once()
        self.assertTrue(any(
            level == messages.SUCCESS and "accepted by the mail server" in text
            for level, text in feedback
        ), feedback)

    def test_zero_sent_is_an_error_not_success(self):
        self.send.return_value = 0
        self.assertIn("did not accept", self.assert_failed(self.submit()))

    def test_missing_send_result_is_not_success(self):
        self.send.return_value = None
        self.assert_failed(self.submit())

    def test_authentication_error_is_actionable_without_leaking_server_reply(self):
        self.send.side_effect = smtplib.SMTPAuthenticationError(
            535, b"private-smtp-response-account-details"
        )
        text = self.assert_failed(self.submit())
        self.assertIn("rejected the sign-in", text)
        self.assertNotIn("private-smtp-response", text)

    def test_connection_error_is_not_success_and_does_not_leak_details(self):
        self.send.side_effect = smtplib.SMTPServerDisconnected("private-smtp-response")
        text = self.assert_failed(self.submit())
        self.assertIn("could not be sent", text)
        self.assertNotIn("private-smtp-response", text)

    def test_selected_server_and_explicit_errors_are_passed_to_backend(self):
        from base.backends import ConfiguredEmailBackend

        with patch("base.views.ConfiguredEmailBackend", wraps=ConfiguredEmailBackend) as backend:
            self.submit()
        self.assertEqual(backend.call_args.kwargs["configuration"].pk, self.config.pk)
        self.assertIs(backend.call_args.kwargs["fail_silently"], False)

    def test_other_company_server_is_inaccessible_even_to_an_admin(self):
        self.assertEqual(self.submit(instance_id=self.other_config.pk).status_code, 404)
        self.send.assert_not_called()

    def test_unknown_or_invalid_server_does_not_fall_back_to_primary(self):
        for instance_id in ("", "invalid", 99999999):
            with self.subTest(instance_id=instance_id):
                self.assertEqual(self.submit(instance_id=instance_id).status_code, 404)
        self.send.assert_not_called()

    def test_invalid_recipient_does_not_send(self):
        response = self.submit(recipient="not-an-email")
        self.assertEqual(response.status_code, 200)
        self.send.assert_not_called()

    def test_get_only_displays_form_without_sending(self):
        response = self.client.get(
            reverse("mail-server-test-email") + f"?instance_id={self.config.pk}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.send.assert_not_called()

    @override_settings(WHITE_LABELLING=True)
    def test_company_without_a_logo_uses_product_logo(self):
        Company._base_manager.filter(pk=self.company.pk).update(icon="")
        self.assertTrue(any(
            level == messages.SUCCESS for level, _ in self.feedback(self.submit())
        ))
        self.send.assert_called_once()

    @override_settings(WHITE_LABELLING=True)
    def test_missing_company_logo_file_uses_product_logo(self):
        Company._base_manager.filter(pk=self.company.pk).update(icon="missing-mail-logo.png")
        self.assertTrue(any(
            level == messages.SUCCESS for level, _ in self.feedback(self.submit())
        ))
        self.send.assert_called_once()

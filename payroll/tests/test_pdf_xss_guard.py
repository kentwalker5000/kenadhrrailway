"""PDF rendering rejects active HTML and uses no executable or network assets."""

import io
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings
from pypdf import PdfReader

from payroll.views.views import generate_payslip_pdf


class PayslipPdfXssGuardTests(SimpleTestCase):
    @patch("payroll.views.views.render_to_string")
    def test_active_html_is_rejected_before_rendering(self, mock_render):
        mock_render.return_value = (
            "<html><body><script>fetch('file:///etc/passwd')</script></body></html>"
        )

        response = generate_payslip_pdf(
            "payroll/payslip/payslip_pdf.html",
            {},
            html=False,
        )

        self.assertEqual(response.status_code, 400)

    @patch(
        "payroll.views.views.render_to_string",
        return_value="<html><body><h1>Payslip</h1></body></html>",
    )
    @patch("payroll.views.views.render_payslip_html", return_value=b"%PDF-1.4")
    def test_trusted_rendered_html_is_allowed(self, mock_renderer, _mock_render):
        response = generate_payslip_pdf(
            "payroll/payslip/payslip_pdf.html",
            {},
            html=False,
        )

        self.assertEqual(response.status_code, 200)
        mock_renderer.assert_called_once()

    @patch(
        "payroll.views.views.render_to_string",
        return_value="<html><body><h1>KenadHr Payslip</h1></body></html>",
    )
    def test_pdf_is_readable_without_external_binary(self, *_mocks):
        response = generate_payslip_pdf("unused.html", {})
        self.assertEqual(response.status_code, 200)
        reader = PdfReader(io.BytesIO(response.content))
        self.assertIn("KenadHr Payslip", reader.pages[0].extract_text())

    @patch("payroll.views.views.render_to_string", return_value="<h1>Payslip</h1>")
    @patch(
        "payroll.views.views.render_payslip_html",
        side_effect=ValueError("Renderer failed"),
    )
    def test_renderer_failure_returns_error(self, *_mocks):
        response = generate_payslip_pdf("unused.html", {})
        self.assertEqual(response.status_code, 500)

    def test_fallback_does_not_fetch_remote_styles_or_images(self):
        from payroll.pdf import render_payslip_html

        with patch(
            "socket.create_connection", side_effect=AssertionError("Network forbidden")
        ) as network:
            with self.assertRaises(ValueError):
                render_payslip_html(
                    '<link rel="stylesheet" href="https://example.invalid/font.css">'
                )
            pdf = render_payslip_html(
                "<html><head></head>"
                '<body><h1>Payslip</h1><img src="https://example.invalid/logo.png"></body></html>'
            )
            network.assert_not_called()
        self.assertTrue(pdf.startswith(b"%PDF-"))

    @override_settings(
        STATIC_URL="/static/", MEDIA_URL="/media/", MEDIA_ROOT="/app/media"
    )
    def test_fallback_rejects_local_file_urls_and_path_traversal(self):
        from payroll.pdf import EMPTY_IMAGE, render_payslip_html

        request = RequestFactory().get("/")
        with patch(
            "payroll.pdf.pisa.CreatePDF", return_value=SimpleNamespace(err=0)
        ) as render:
            render_payslip_html("<h1>Payslip</h1>", request=request)
        asset = render.call_args.kwargs["link_callback"]
        for uri in (
            "file:///etc/passwd",
            "/etc/passwd",
            "/media/../../etc/passwd",
            "/static/../../etc/passwd",
            "http://testserver/media/%2e%2e/%2e%2e/etc/passwd",
            "https://example.invalid/media/logo.png",
        ):
            with self.subTest(uri=uri):
                self.assertEqual(asset(uri, None), EMPTY_IMAGE)

    def test_renderer_does_not_fetch_assets_using_browser_cookies(self):
        from horilla.horilla_middlewares import _thread_locals

        request = RequestFactory().get("/", HTTP_COOKIE="sessionid=synthetic-only")
        previous_request = _thread_locals.request
        self.addCleanup(setattr, _thread_locals, "request", previous_request)
        _thread_locals.request = request
        with patch(
            "payroll.views.views.render_to_string", return_value="<h1>Payslip</h1>"
        ), patch(
            "socket.create_connection", side_effect=AssertionError("Network forbidden")
        ):
            response = generate_payslip_pdf("unused.html", {})
        self.assertEqual(response.status_code, 200)

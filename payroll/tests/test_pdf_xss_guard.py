"""PDF rendering must never pass active HTML to wkhtmltopdf."""

from unittest.mock import patch

from django.test import SimpleTestCase

from payroll.views.views import generate_payslip_pdf


class PayslipPdfXssGuardTests(SimpleTestCase):
    @patch("payroll.views.views.render_to_string")
    def test_active_html_is_rejected_before_pdfkit_runs(self, mock_render):
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
    @patch("payroll.views.views.pdfkit.from_string", return_value=b"%PDF-1.4")
    def test_trusted_rendered_html_is_allowed(self, mock_pdfkit, _mock_render):
        response = generate_payslip_pdf(
            "payroll/payslip/payslip_pdf.html",
            {},
            html=False,
        )

        self.assertEqual(response.status_code, 200)
        mock_pdfkit.assert_called_once()

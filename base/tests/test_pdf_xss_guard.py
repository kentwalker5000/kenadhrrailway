"""
generate_pdf must reject active HTML before the shared offline renderer runs.
The checks remain in place after removal of the vulnerable pdfkit dependency.
"""

from django.test import SimpleTestCase

from base.methods import generate_pdf


class GeneratePdfXssGuardTests(SimpleTestCase):
    def test_script_payload_is_refused(self):
        response = generate_pdf(
            "<html><body><script>fetch('/etc/passwd')</script></body></html>",
            {},
            path=False,
            title="Document",
        )

        self.assertEqual(response.status_code, 400)

    def test_local_file_exfiltration_payload_is_refused(self):
        # The shape the advisory describes: read a local file, post it out.
        payload = (
            "<html><body><script>"
            "var x=new XMLHttpRequest();"
            "x.open('GET','file:///etc/passwd');"
            "x.send();"
            "</script></body></html>"
        )

        response = generate_pdf(payload, {}, path=False, title="Document")

        self.assertEqual(response.status_code, 400)

    def test_onerror_handler_is_refused(self):
        response = generate_pdf(
            "<img src=x onerror=\"fetch('//evil.test')\">",
            {},
            path=False,
            title="Document",
        )

        self.assertEqual(response.status_code, 400)

    def test_ordinary_payslip_markup_still_renders(self):
        # Over-blocking would break payslip and document generation outright,
        # so the negative case matters as much as the positive ones.
        response = generate_pdf(
            "<html><body><h1>Payslip</h1><table><tr><td>Basic</td>"
            "<td>50000</td></tr></table></body></html>",
            {},
            path=False,
            title="Payslip",
        )

        self.assertNotEqual(response.status_code, 400)

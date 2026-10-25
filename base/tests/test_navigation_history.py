from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from unittest.mock import patch

from horilla.navigation import HistoryRestoreMiddleware


class NavigationHistoryTests(SimpleTestCase):
    def test_history_restore_is_a_full_page_request(self):
        request = RequestFactory().get(
            "/petty-cash/", HTTP_HX_REQUEST="true",
            HTTP_HX_HISTORY_RESTORE_REQUEST="true",
        )
        # Exercise cached request.headers too, not just META consumers.
        self.assertEqual(request.headers.get("HX-Request"), "true")

        def view(req):
            self.assertNotIn("HTTP_HX_REQUEST", req.META)
            self.assertIsNone(req.headers.get("HX-Request"))
            self.assertEqual(req.headers["HX-History-Restore-Request"], "true")
            return HttpResponse("full page")

        response = HistoryRestoreMiddleware(view)(request)
        self.assertEqual(response.content, b"full page")

    def test_regular_htmx_requests_remain_fragments(self):
        request = RequestFactory().get("/petty-cash/", HTTP_HX_REQUEST="true")
        HistoryRestoreMiddleware(lambda req: HttpResponse())(request)
        self.assertEqual(request.headers["HX-Request"], "true")

    def test_normal_requests_are_unchanged(self):
        request = RequestFactory().get("/petty-cash/")
        HistoryRestoreMiddleware(lambda req: HttpResponse())(request)
        self.assertIsNone(request.headers.get("HX-Request"))

    def test_history_rebuilds_breadcrumbs_instead_of_retaining_the_previous_page(self):
        from horilla_crumbs.context_processors import breadcrumbs

        request = RequestFactory().get(
            "/petty-cash/", HTTP_HX_HISTORY_RESTORE_REQUEST="true",
            HTTP_REFERER="http://testserver/payroll/view-payslip/",
        )
        request.session = {"breadcrumbs": [{"name": "Old payroll page"}]}
        trail = [{"name": "Company"}, {"name": "Finance"}, {"name": "Petty Cash"}]
        with patch("horilla_crumbs.context_processors.is_asset_request", return_value=False), \
             patch("horilla_crumbs.context_processors.build_breadcrumbs", return_value=trail):
            self.assertEqual(breadcrumbs(request)["breadcrumbs"], trail)
        self.assertEqual(request.session["breadcrumbs"], trail)

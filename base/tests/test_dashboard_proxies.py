"""Tests for safe dashboard chart proxy failures."""

import json

from django.test import RequestFactory, SimpleTestCase

from base.dashboard import _call_module_json


class DashboardProxyTests(SimpleTestCase):
    def test_chart_failure_is_logged_without_exposing_the_exception(self):
        request = RequestFactory().get("/dashboard/api/example/")

        def broken_chart(_request):
            raise RuntimeError("database password must not reach the browser")

        with self.assertLogs("base.dashboard", level="ERROR"):
            response = _call_module_json(broken_chart, request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload["error"], "Unable to load dashboard data.")
        self.assertNotIn("password", response.content.decode())

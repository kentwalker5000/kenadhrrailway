"""Exercise menu destinations and read-only HTMX controls using synthetic records.

Run separately with --settings=horilla.settings.site_audit to produce a report.
This does not claim to exercise JavaScript or external service integrations.
"""

import importlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from django.apps import apps
from django.conf import settings
from django.contrib.staticfiles import finders
from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import Resolver404, resolve

from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.menu import get_settings_menu
from horilla.testkit import make_company, make_employee, make_user


class ControlsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.controls = []

    def handle_starttag(self, tag, attrs):
        self.controls.append((tag, dict(attrs)))


# Never invoke mutation-like URLs simply because a template calls them with GET.
MUTATION = re.compile(
    r"delete|remove|archive|unarchive|approve|reject|send|logout|clock-in|clock-out|"
    r"check-in|check-out|toggle|activate|deactivate|duplicate|confirm|cancel|reset|"
    r"mark-|clear|notification-sound|start-stop|read-notification|refresh-token|oauth|authenticate|connect|disconnect",
    re.I,
)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    TWO_FACTORS_AUTHENTICATION=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class SiteNavigationAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _thread_locals.request = None
        set_selected_company(None)
        cls.company = make_company("Synthetic Site Audit")
        cls.owner = make_user("site-audit-owner", is_superuser=True)
        cls.employee = make_employee(
            company=cls.company, user=cls.owner, email="audit-owner@example.invalid"
        )
        cls.staff = make_user("site-audit-staff")
        make_employee(
            company=cls.company, user=cls.staff, email="audit-staff@example.invalid"
        )
        cls.report = {
            "pages": [],
            "controls": [],
            "broken_links": [],
            "missing_assets": [],
            "skipped": [],
        }

    def setUp(self):
        self.report = type(self).report
        set_selected_company(None)
        _thread_locals.request = None
        self.addCleanup(set_selected_company, None)
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.client.force_login(self.owner)

    @classmethod
    def tearDownClass(cls):
        try:
            output = getattr(settings, "SITE_AUDIT_REPORT", None)
            if output:
                output = Path(output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(cls.report, indent=2, default=str), encoding="utf-8"
                )
        finally:
            set_selected_company(None)
            _thread_locals.request = None
            super().tearDownClass()

    @staticmethod
    def internal_url(value):
        if not value or value.startswith(("#", "javascript:", "mailto:", "tel:")):
            return None
        parsed = urlsplit(value)
        if parsed.netloc or parsed.scheme or not parsed.path.startswith("/"):
            return None
        if any(token in value for token in ("{{", "${", "<", ">")):
            return None
        return parsed.path + ("?" + parsed.query if parsed.query else "")

    def menu_destinations(self):
        destinations = {"/": "Home"}
        for app in apps.get_app_configs():
            if not (Path(app.path) / "sidebar.py").is_file():
                continue
            module = importlib.import_module(f"{app.name}.sidebar")
            for item in getattr(module, "SUBMENUS", []):
                url = self.internal_url(str(item.get("redirect", "")))
                if url:
                    destinations[url] = f"{app.label}: {item.get('menu', '')}"
        request = RequestFactory().get("/settings/")
        request.user = self.owner
        request.session = {"selected_company": str(self.company.pk)}
        for section in get_settings_menu(request):
            for item in section["items"]:
                url = self.internal_url(str(item.get("url", "")))
                if url:
                    destinations[url] = (
                        f"Settings: {section['title']} / {item['label']}"
                    )
        return destinations

    def request_page(self, url, *, htmx=False, parent="/", target=""):
        record = {"url": url, "htmx": htmx}
        try:
            # Isolate page side effects and recover after a database exception.
            with transaction.atomic():
                headers = {"HTTP_REFERER": "http://testserver" + parent}
                if htmx:
                    headers.update(
                        HTTP_HX_REQUEST="true",
                        HTTP_HX_CURRENT_URL="http://testserver" + parent,
                    )
                    if target.startswith("#"):
                        headers["HTTP_HX_TARGET"] = target[1:]
                response = self.client.get(url, follow=True, **headers)
                record["status"] = response.status_code
                record["redirects"] = response.redirect_chain
                html = (
                    response.content.decode("utf-8", errors="replace")
                    if not response.streaming
                    else ""
                )
                if any("/login" in location for location, _ in response.redirect_chain):
                    record["error"] = "Authenticated navigation redirected to login"
                transaction.set_rollback(True)
            return record, html
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            return record, ""

    def test_owner_navigation_links_assets_and_readonly_controls(self):
        issues = []
        visited_controls = set()
        for url, label in sorted(self.menu_destinations().items()):
            if MUTATION.search(url):
                self.report["skipped"].append(
                    {"url": url, "reason": "potential side effect"}
                )
                continue
            page, html = self.request_page(url)
            # Some settings panels deliberately require an HTMX request.
            if page.get("status") == 405:
                page, html = self.request_page(url, htmx=True)
            page["label"] = label
            self.report["pages"].append(page)
            print(f"AUDIT {url}: {page.get('error') or page.get('status')}", flush=True)
            if page.get("error") or page.get("status") != 200:
                issues.append(page)
                continue
            self.inspect_controls(html, url, visited_controls, issues)
        self.assertFalse(issues, json.dumps(issues, indent=2, default=str))

    def inspect_controls(self, html, url, visited_controls, issues, depth=0):
        parser = ControlsParser()
        parser.feed(html)
        for tag, attrs in parser.controls:
            for attribute in (
                "href",
                "action",
                "hx-get",
                "hx-post",
                "hx-delete",
                "hx-put",
            ):
                value = self.internal_url(attrs.get(attribute, ""))
                if not value:
                    continue
                path = urlsplit(value).path
                if path.startswith((settings.STATIC_URL, settings.MEDIA_URL)):
                    continue
                try:
                    resolve(path)
                except Resolver404:
                    failure = {"page": url, "attribute": attribute, "url": value}
                    self.report["broken_links"].append(failure)
                    issues.append(failure)
            asset = (
                attrs.get("src")
                if tag == "script"
                else attrs.get("href")
                if tag == "link" and attrs.get("rel") == "stylesheet"
                else None
            )
            if asset and asset.startswith(settings.STATIC_URL):
                relative = urlsplit(asset).path[len(settings.STATIC_URL) :]
                if not finders.find(relative):
                    failure = {"page": url, "asset": asset}
                    self.report["missing_assets"].append(failure)
                    issues.append(failure)
            control = self.internal_url(attrs.get("hx-get", ""))
            if not control or control in visited_controls or depth >= 2:
                continue
            visited_controls.add(control)
            if (
                MUTATION.search(control)
                or attrs.get("hx-include")
                or attrs.get("hx-vals", "").startswith("js:")
            ):
                self.report["skipped"].append(
                    {
                        "page": url,
                        "url": control,
                        "reason": "side effect or browser-dependent inputs",
                    }
                )
                continue
            vals = attrs.get("hx-vals")
            if vals:
                try:
                    control += ("&" if "?" in control else "?") + urlencode(
                        json.loads(vals)
                    )
                except (ValueError, TypeError):
                    self.report["skipped"].append(
                        {"page": url, "url": control, "reason": "dynamic hx-vals"}
                    )
                    continue
            result, fragment = self.request_page(
                control, htmx=True, parent=url, target=attrs.get("hx-target", "")
            )
            result["page"] = url
            self.report["controls"].append(result)
            if result.get("error") or result.get("status", 500) >= 400:
                issues.append(result)
            elif fragment:
                self.inspect_controls(
                    fragment, url, visited_controls, issues, depth + 1
                )

    def test_staff_visible_navigation_does_not_crash_or_expose_forbidden_pages(self):
        from horilla.config import get_MENUS

        self.client.force_login(self.staff)
        request = RequestFactory().get("/")
        request.user = self.staff
        request.session = self.client.session
        set_selected_company(str(self.company.pk))
        _thread_locals.request = request
        menus = get_MENUS(request)["sidebar"]
        destinations = {
            str(item["redirect"]) for menu in menus for item in menu["submenu"]
        }
        issues = []
        for url in sorted(destinations):
            result, _ = self.request_page(url)
            result["role"] = "staff"
            self.report["pages"].append(result)
            print(
                f"AUDIT staff {url}: {result.get('error') or result.get('status')}",
                flush=True,
            )
            if result.get("error") or result.get("status") != 200:
                issues.append(result)
        self.assertTrue(destinations)
        self.assertFalse(issues, json.dumps(issues, indent=2, default=str))

"""Static contracts between first-party templates, routes and included templates."""

import re
import json
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import URLResolver, get_resolver


def route_names(resolver, prefix=""):
    names = set()
    for item in resolver.url_patterns:
        if isinstance(item, URLResolver):
            namespace = f"{item.namespace}:" if item.namespace else ""
            names.update(route_names(item, prefix + namespace))
        elif item.name:
            names.add(prefix + item.name)
    return names


class TemplateRoutingContractTests(SimpleTestCase):
    def test_literal_template_url_names_exist(self):
        root = Path(settings.BASE_DIR)
        directories = [root / "templates"] + [
            Path(app.path) / "templates"
            for app in apps.get_app_configs()
            if Path(app.path).parent == root
        ]
        known = route_names(get_resolver())
        broken = []
        checked = 0
        # These upstream remnants have no active view/include referencing them.
        # Keep exclusions explicit, rather than silently ignoring all unknown names.
        inactive = {
            "base/templates/base/auth/group_view.html": "Superseded by base/auth/roles_permissions.html",
            "payroll/templates/payroll/contribution/contribution_deduction_list.html": "Retired contribution model; current deductions implement employer contributions",
            "horilla_views/templates/generic/index.html": "Unwired example scaffold with placeholder route names",
            "horilla_backup/templates/backup/local_setup_form.html": "Local backup web endpoints are deliberately disabled",
        }
        for directory in directories:
            for path in directory.rglob("*.html"):
                relative = path.relative_to(root).as_posix()
                if relative in inactive:
                    continue
                source = path.read_text(encoding="utf-8-sig")
                # Django comments are intentionally not executable template code.
                source = re.sub(
                    r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}|{#.*?#}",
                    "",
                    source,
                    flags=re.S,
                )
                for match in re.finditer(r"{%\s*url\s+(['\"])(.*?)\1(.*?)%}", source):
                    checked += 1
                    if match[2] == "outlook_view_records" and not apps.is_installed(
                        "outlook_auth"
                    ):
                        # The template guards this link with app_installed.
                        continue
                    # `as variable` is Django's documented optional-link pattern.
                    if match[2] not in known and not re.search(
                        r"\bas\s+\w+\s*$", match[3]
                    ):
                        line = source.count("\n", 0, match.start()) + 1
                        broken.append(f"{path.relative_to(root)}:{line}: {match[2]}")
        output = getattr(settings, "SITE_AUDIT_REPORT", None)
        if output:
            Path(output).with_name("site-ui-contracts.json").write_text(
                json.dumps(
                    {
                        "url_references_checked": checked,
                        "registered_route_names": len(known),
                        "broken": broken,
                        "inactive_templates_excluded": inactive,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        self.assertGreater(checked, 100)
        self.assertFalse(broken, "Unknown URL names:\n" + "\n".join(broken))

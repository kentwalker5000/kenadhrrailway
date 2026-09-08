"""Regression checks for the organization chart manager selector layout."""

import re
from pathlib import Path

from django.template import Engine
from django.test import SimpleTestCase


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
THEME_TEMPLATE = (
    REPOSITORY_ROOT
    / "horilla_theme"
    / "templates"
    / "organisation_chart"
    / "org_chart.html"
)
BUILT_ORG_CHART_CSS = REPOSITORY_ROOT / "static" / "build" / "css" / "orgChart.css"
SOURCE_ORG_CHART_SCSS = (
    REPOSITORY_ROOT / "static" / "src" / "scss" / "vendors" / "_orgchart.scss"
)


def css_rule(source, selector):
    """Return a flat CSS rule body while tolerating formatting differences."""

    match = re.search(
        rf"{re.escape(selector)}\s*\{{(?P<body>[^{{}}]*)\}}",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"Missing CSS rule for {selector}")
    return match.group("body")


def at_rule_body(source, at_rule):
    """Return an at-rule body using brace matching rather than fragile regex."""

    start = source.find(at_rule)
    if start == -1:
        raise AssertionError(f"Missing CSS at-rule {at_rule}")
    opening_brace = source.find("{", start)
    depth = 0
    for index in range(opening_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening_brace + 1 : index]
    raise AssertionError(f"Unclosed CSS at-rule {at_rule}")


class OrganisationChartSelectorLayoutTests(SimpleTestCase):
    """Keep the Select2 control from being clipped or overflowing its header."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_source = THEME_TEMPLATE.read_text(encoding="utf-8")
        cls.built_css = BUILT_ORG_CHART_CSS.read_text(encoding="utf-8")
        cls.source_scss = SOURCE_ORG_CHART_SCSS.read_text(encoding="utf-8")

    def test_theme_template_uses_dedicated_manager_selector_markup(self):
        self.assertIsNotNone(Engine.get_default().from_string(self.template_source))
        self.assertEqual(self.template_source.count('id="managerSelect"'), 1)
        self.assertIn('class="oh-org-chart__manager-row"', self.template_source)
        self.assertRegex(
            self.template_source,
            r'<label\s+class="oh-org-chart__manager-label"\s+'
            r'for="managerSelect">[\s\S]*?</label>',
        )
        self.assertIn('class="oh-org-chart__manager-select"', self.template_source)
        self.assertIn('hx-target="#chart_target"', self.template_source)
        self.assertIn('hx-swap="innerHTML"', self.template_source)
        self.assertNotIn('hx-swap="OuterHTML"', self.template_source)

    def test_built_css_keeps_generated_select2_control_fully_sized(self):
        row_rule = css_rule(self.built_css, ".oh-org-chart__manager-row")
        self.assertRegex(row_rule, r"display:\s*flex\s*;")
        self.assertRegex(row_rule, r"flex-wrap:\s*wrap\s*;")

        container_rule = css_rule(self.built_css, ".oh-org-chart__manager-select")
        self.assertRegex(container_rule, r"width:\s*[^;]+;")
        self.assertRegex(container_rule, r"min-width:\s*0\s*;")

        select2_rule = css_rule(
            self.built_css,
            ".oh-org-chart__manager-select > .select2-container",
        )
        self.assertRegex(select2_rule, r"width:\s*100%\s*!important\s*;")
        self.assertRegex(select2_rule, r"min-width:\s*0\s*;")

        selection_rule = css_rule(
            self.built_css,
            ".oh-org-chart__manager-select .select2-selection--single",
        )
        self.assertRegex(
            selection_rule,
            r"height:\s*(?!0(?:px|rem|em)?\s*;|auto\s*;|unset\s*;)[^;]+;",
        )
        self.assertRegex(selection_rule, r"width:\s*100%\s*;")

    def test_mobile_css_stacks_selector_without_horizontal_clipping(self):
        mobile_css = at_rule_body(self.built_css, "@media (max-width: 767.98px)")
        mobile_row_rule = css_rule(mobile_css, ".oh-org-chart__manager-row")
        self.assertRegex(
            mobile_row_rule,
            r"(?:flex-direction:\s*column|flex-wrap:\s*wrap)\s*;",
        )

        mobile_label_rule = css_rule(mobile_css, ".oh-org-chart__manager-label")
        self.assertRegex(mobile_label_rule, r"width:\s*100%\s*;")
        mobile_container_rule = css_rule(
            mobile_css,
            ".oh-org-chart__manager-select",
        )
        self.assertRegex(mobile_container_rule, r"width:\s*100%\s*;")

    def test_source_scss_carries_the_selector_contract(self):
        for selector in (
            ".oh-org-chart__manager-row",
            ".oh-org-chart__manager-label",
            ".oh-org-chart__manager-select",
            ".select2-selection--single",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.source_scss)
        self.assertRegex(self.source_scss, r"min-width:\s*0\s*;")

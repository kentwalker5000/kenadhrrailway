"""Readable history labels and colours, without rewriting the audit trail."""

import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.template import Context, Engine
from django.test import SimpleTestCase, TestCase

from horilla.testkit import make_company, make_employee, make_user
from horilla_audit.activity_feed import (
    _normalize_tracking_change,
    build_activity_history_feed,
    normalize_log_entries,
    normalize_tracking_entries,
)
from horilla_audit.methods import Bot, get_diff
from horilla_audit.models import HistoryTrackingFields
from horilla_views.history_methods import get_diff as get_generic_diff


def assignment_change(**overrides):
    return {
        "field_name": "company_id", "field_label": "Company", "is_fk": True,
        "old": None, "new": 1, "old_value": "—", "new_value": "IoD-Gh",
        **overrides,
    }


def tracking_entry(actor=None, **overrides):
    return {
        "type": "Changes", "updated_by": actor,
        "changes": [assignment_change()], **overrides,
    }


class HistoryDisplayLabelsTests(SimpleTestCase):
    def test_system_fallback_uses_neutral_label_and_no_external_bot_avatar(self):
        for actor in (None, Bot()):
            with self.subTest(actor=actor):
                entry = normalize_tracking_entries([tracking_entry(actor)])[0]
                self.assertEqual(entry["actor_name"], "System update")
                self.assertTrue(entry["is_system_actor"])
                self.assertIsNone(entry["actor_avatar"])

    def test_recorded_employee_keeps_name_and_avatar(self):
        employee = SimpleNamespace(
            get_full_name=lambda: "Ama Mensah", get_avatar=lambda: "/media/ama.png"
        )
        entry = normalize_tracking_entries([tracking_entry(employee)])[0]
        self.assertEqual(entry["actor_name"], "Ama Mensah")
        self.assertEqual(entry["actor_avatar"], "/media/ama.png")
        self.assertFalse(entry["is_system_actor"])

    def test_empty_assignment_gets_display_label_without_mutating_raw_diff(self):
        change = assignment_change()
        original = deepcopy(change)
        rendered = _normalize_tracking_change(change)
        self.assertEqual(rendered["old_value"], "Previously unassigned")
        self.assertTrue(rendered["old_is_empty"])
        self.assertEqual(rendered["new_value"], "IoD-Gh")
        self.assertEqual(change, original)
        self.assertIsNone(rendered["old"])

    def test_removed_assignment_uses_unassigned_not_previously_unassigned(self):
        rendered = _normalize_tracking_change(assignment_change(
            old=1, old_value="IoD-Gh", new=None, new_value="—"
        ))
        self.assertEqual(rendered["old_value"], "IoD-Gh")
        self.assertEqual(rendered["new_value"], "Unassigned")
        self.assertFalse(rendered["old_is_empty"])

    def test_empty_nonrelationship_value_uses_not_set(self):
        rendered = _normalize_tracking_change({"old": "", "new": "Address"})
        self.assertEqual(rendered["old_value"], "Not set")

    def test_zero_false_and_literal_none_are_not_treated_as_unassigned(self):
        for value in (0, False, "None"):
            with self.subTest(value=value):
                rendered = _normalize_tracking_change({"old": value, "new": value})
                self.assertEqual(rendered["old_value"], str(value))
                self.assertFalse(rendered["old_is_empty"])

    def test_legacy_relationship_diffs_still_resolve_names(self):
        pair = (SimpleNamespace(company_id="New Company"), SimpleNamespace(company_id="Old Company"))
        change = {"field_name": "company_id", "is_fk": True, "old": 1, "new": 2}
        rendered = _normalize_tracking_change(change, pair)
        self.assertEqual(rendered["old_value"], "Old Company")
        self.assertEqual(rendered["new_value"], "New Company")

    def test_deleted_related_record_keeps_its_id(self):
        change = {"field_name": "company_id", "is_fk": True, "old": 3, "new": None}
        rendered = _normalize_tracking_change(change, (SimpleNamespace(), SimpleNamespace()))
        self.assertEqual(rendered["old_value"], "3 (deleted)")

    def test_auditlog_preserves_a_recorded_user_even_without_employee_profile(self):
        actor = SimpleNamespace(get_full_name=lambda: "HR Administrator")
        log = SimpleNamespace(actor=actor, changes_display_dict={"City": ["Accra", "Tema"]})
        entry = normalize_log_entries([log])[0]
        self.assertEqual(entry["actor_name"], "HR Administrator")
        self.assertFalse(entry["is_system_actor"])

    def test_auditlog_without_actor_uses_system_label(self):
        log = SimpleNamespace(actor=None, changes_display_dict={"City": ["Accra", "Tema"]})
        entry = normalize_log_entries([log])[0]
        self.assertEqual(entry["actor_name"], "System update")
        self.assertIsNone(entry["actor_avatar"])
        self.assertTrue(entry["is_system_actor"])


class HistoryTemplateTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(settings.BASE_DIR)
        self.engine = Engine(
            dirs=[self.root / "horilla_views/templates"],
            libraries={
                "i18n": "django.templatetags.i18n",
                "static": "django.templatetags.static",
            },
        )

    def test_both_templates_render_clear_labels_search_and_local_system_icon(self):
        for app in ("horilla_theme", "horilla_views"):
            for compact in (False, True):
                with self.subTest(app=app, compact=compact):
                    source = (self.root / app / "templates/generic/activity_history_feed.html").read_text(encoding="utf-8")
                    context = build_activity_history_feed(tracking=[tracking_entry(Bot())])
                    html = self.engine.from_string(source).render(Context({
                        **context, "feed_id": "testHistory", "show_header": True,
                        "show_search": True, "compact": compact, "title": "Activity history",
                    }))
                    self.assertIn("Previously unassigned", html)
                    self.assertIn("System update", html)
                    self.assertIn("IoD-Gh", html)
                    self.assertIn('name="settings-outline"', html)
                    self.assertIn('id="testHistorySearch"', html)
                    self.assertIn('data-search-text="System update', html)
                    self.assertIn("eah-search-input", html)
                    self.assertIn("body.dark #testHistory", html)
                    self.assertNotIn("Horilla+Bot", html)
                    self.assertNotIn("text-dark-100", html)
                    self.assertNotIn('class="eah-old eah-strike', html)

    def test_light_and_dark_text_colour_pairs_have_readable_contrast(self):
        source = (self.root / "horilla_views/templates/generic/activity_history_styles.html").read_text(encoding="utf-8")
        css = self.engine.from_string(source).render(Context({"feed_id": "testHistory"}))

        def luminance(hex_colour):
            channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        for selector in ("#testHistory", "body.dark #testHistory"):
            block = re.search(re.escape(selector) + r"\s*\{([^}]+)\}", css).group(1)
            colours = dict(re.findall(r"--eah-([\w-]+):\s*(#[0-9a-f]{6})", block))
            for text, background in (("text", "surface"), ("muted", "surface"), ("old-text", "old-bg"), ("new-text", "new-bg")):
                with self.subTest(mode=selector, text=text):
                    values = sorted((luminance(colours[text]), luminance(colours[background])))
                    self.assertGreaterEqual((values[1] + 0.05) / (values[0] + 0.05), 4.5)


class HistoryAuditPreservationTests(TestCase):
    def setUp(self):
        company = make_company("History Test Company")
        employee = make_employee(company=company, email="history-display@test.horilla")
        self.work = employee.employee_work_info
        self.work.save()
        HistoryTrackingFields.objects.create(
            company_id=company, work_info_track=True,
            tracking_fields={"tracking_fields": ["company_id", "basic_salary"]},
        )
        self.work.basic_salary = 1234
        self.work.save()

    def test_reading_history_does_not_delete_duplicate_snapshots_or_change_records(self):
        duplicate = self.work.history_set.values().first()
        duplicate.pop("history_id")
        self.work.history_set.model.objects.create(**duplicate)
        before = list(self.work.history_set.order_by("history_id").values())
        feed = build_activity_history_feed(tracking=get_diff(self.work))
        self.assertTrue(feed["has_history"])
        self.assertEqual(list(self.work.history_set.order_by("history_id").values()), before)

    def test_history_keeps_recorded_user_without_employee_profile(self):
        actor = make_user("history-auditor")
        latest = self.work.history_set.first()
        self.work.history_set.filter(pk=latest.pk).update(history_user_id=actor.pk)
        entries = normalize_tracking_entries(get_diff(self.work))
        self.assertEqual(entries[0]["actor_name"], "history-auditor")
        self.assertFalse(entries[0]["is_system_actor"])

    def test_generic_history_is_read_only_and_uses_the_same_system_label(self):
        duplicate = self.work.history_set.values().first()
        duplicate.pop("history_id")
        self.work.history_set.model.objects.create(**duplicate)
        before = list(self.work.history_set.order_by("history_id").values())
        entries = normalize_tracking_entries(get_generic_diff(self.work, "history_set"))
        self.assertTrue(entries)
        self.assertEqual(entries[0]["actor_name"], "System update")
        self.assertEqual(list(self.work.history_set.order_by("history_id").values()), before)

    def test_generic_history_preserves_recorded_user_without_employee_profile(self):
        actor = make_user("generic-history-auditor")
        latest = self.work.history_set.first()
        self.work.history_set.filter(pk=latest.pk).update(history_user_id=actor.pk)
        entries = normalize_tracking_entries(get_generic_diff(self.work, "history_set"))
        self.assertEqual(entries[0]["actor_name"], "generic-history-auditor")
        self.assertFalse(entries[0]["is_system_actor"])

"""Regression checks for recruitment routes used by the survey UI."""

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from recruitment.views import search, surveys, views


class RecruitmentRouteSmokeTests(SimpleTestCase):
    def test_survey_filter_route_resolves_to_its_filter_view(self):
        path = reverse("rec-filter-survey")

        self.assertEqual(path, "/recruitment/filter-survey/")
        self.assertIs(resolve(path).func, search.filter_survey)

    def test_survey_template_update_route_resolves_to_edit_view(self):
        path = reverse("survey-template-update")

        self.assertEqual(path, "/recruitment/survey-template-update/")
        self.assertIs(resolve(path).func, surveys.create_template)

    def test_candidate_mail_log_route_requires_a_candidate_identifier(self):
        path = reverse("get-mail-log-rec", args=[1])

        self.assertEqual(path, "/recruitment/get-mail-log-rec/1/")
        self.assertIs(resolve(path).func, views.get_mail_log)

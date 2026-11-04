from datetime import timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase, RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.utils import timezone
from employee.models import EmployeeWorkInformation
from horilla.testkit import make_company, make_employee, make_user
from pms.models import Period, QuestionTemplate, Question, Feedback, Answer
from pms.review_workflow import open_period, review_access_error
from pms.views import feedback_answer_post


class QuarterlyReviewTests(TestCase):
    def setUp(self):
        self.company = make_company("Review workflow test")
        self.manager = make_employee(company=self.company, email="manager@review.test", user=make_user("review-manager"))
        self.staff = make_employee(company=self.company, email="staff@review.test", user=make_user("review-staff"))
        self.outsider = make_employee(company=self.company, email="other@review.test", user=make_user("review-other"))
        EmployeeWorkInformation.objects.filter(employee_id=self.staff).update(reporting_manager_id=self.manager)
        self.period = Period.objects.create(period_name="Quarter workflow test", start_date=timezone.localdate()-timedelta(days=1), end_date=timezone.localdate()+timedelta(days=30))
        self.template = QuestionTemplate.objects.create(question_template="Workflow rating")
        self.question = Question.objects.create(template_id=self.template, question="Communication", question_type="2")
        open_period(self.period, self.company, self.template)
        self.review = Feedback.objects.get(period=self.period, employee_id=self.manager)

    def post(self, employee, value="4"):
        request = RequestFactory().post("/", {f"answer{self.question.pk}": value})
        request.user = employee.employee_user_id
        request.session = SessionStore()
        request.session.create()
        request._messages = FallbackStorage(request)
        return feedback_answer_post(request, self.review.pk)

    def test_staff_and_manager_are_assigned_both_directions(self):
        self.assertIn(self.staff, self.review.subordinate_id.all())
        self.assertEqual(Feedback.objects.get(period=self.period, employee_id=self.staff).manager_id, self.manager)
        self.assertEqual(open_period(self.period, self.company, self.template), 0)

    def test_unassigned_staff_cannot_post(self):
        self.assertEqual(self.post(self.outsider).status_code, 403)
        self.assertFalse(Answer.objects.exists())

    def test_submission_is_complete_and_cannot_be_repeated(self):
        self.assertEqual(self.post(self.staff).status_code, 302)
        self.assertEqual(self.post(self.staff).status_code, 403)
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "On Track")
        self.assertEqual(self.post(self.manager).status_code, 302)
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "Closed")

    def test_closed_and_expired_quarters_block_submission(self):
        Period.objects.filter(pk=self.period.pk).update(is_open=False)
        self.assertEqual(self.post(self.staff).status_code, 403)
        Period.objects.filter(pk=self.period.pk).update(is_open=True, end_date=timezone.localdate()-timedelta(days=1))
        self.assertEqual(self.post(self.staff).status_code, 403)

    def test_invalid_rating_creates_no_answers(self):
        self.assertEqual(self.post(self.staff, "9").status_code, 400)
        self.assertFalse(Answer.objects.exists())

    def test_future_quarter_blocks_submission(self):
        Period.objects.filter(pk=self.period.pk).update(start_date=timezone.localdate()+timedelta(days=1))
        self.assertEqual(self.post(self.staff).status_code, 403)

    def test_staff_cannot_open_or_close_quarters(self):
        from django.core.exceptions import PermissionDenied
        from pms.quarter_views import quarter_control
        request = RequestFactory().post("/", {"action": "close"})
        request.user = self.staff.employee_user_id
        with self.assertRaises(PermissionDenied):
            quarter_control(request, self.period.pk)

    def test_manager_can_submit_staff_review(self):
        self.review = Feedback.objects.get(period=self.period, employee_id=self.staff)
        self.assertEqual(self.post(self.manager).status_code, 302)
        self.assertTrue(Answer.objects.filter(feedback_id=self.review, employee_id=self.manager).exists())

    def test_individual_answer_api_cannot_bypass_quarter_workflow(self):
        from horilla_api.api_serializers.pms.serializers import AnswerSerializer
        serializer = AnswerSerializer(data={"feedback_id_write": self.review.pk,
            "question_id_write": self.question.pk, "employee_id_write": self.staff.pk,
            "answer": {"answer": "4"}})
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)

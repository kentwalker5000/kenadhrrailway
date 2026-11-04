from django.test import TestCase

from base.models import Department
from helpdesk.models import Ticket


class TicketRaisedOnTests(TestCase):
    def test_legacy_department_name_is_safe_to_display(self):
        """Imported ticket recipients may be names instead of database IDs."""
        department = Department.objects.create(department="QA Technology")
        ticket = Ticket(assigning_type="department", raised_on="QA Technology")

        self.assertEqual(ticket.get_raised_on(), "QA Technology")
        self.assertEqual(ticket.get_raised_on_object(), department)

    def test_missing_recipient_is_displayed_without_raising(self):
        ticket = Ticket(assigning_type="department", raised_on="Removed department")

        self.assertEqual(ticket.get_raised_on(), "Removed department")
        self.assertIsNone(ticket.get_raised_on_object())

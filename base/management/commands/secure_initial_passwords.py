"""Invalidate historical employee passwords derived from phone numbers."""

from django.contrib.auth.hashers import check_password
from django.core.management.base import BaseCommand
from django.db import transaction

from base.account_security import initial_password
from employee.models import Employee


class Command(BaseCommand):
    help = "Audit historical phone-number passwords; --apply requires affected staff to reset their passwords."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Replace matched passwords and require reset. No email is sent.",
        )

    def handle(self, *args, **options):
        count = 0
        # One user at a time, locked so a concurrent password change cannot be
        # overwritten by a match calculated before that change.
        for employee in Employee._base_manager.exclude(
            employee_user_id=None
        ).iterator():
            if not employee.phone:
                continue
            with transaction.atomic():
                user = (
                    employee.employee_user_id.__class__.objects.select_for_update().get(
                        pk=employee.employee_user_id_id
                    )
                )
                if not check_password(str(employee.phone), user.password):
                    continue
                count += 1
                if options["apply"]:
                    user.set_password(initial_password())
                    user.is_new_employee = True
                    user.save(update_fields=["password", "is_new_employee"])
        action = (
            "Password reset required for"
            if options["apply"]
            else "Phone-number password found for"
        )
        self.stdout.write(f"{action} {count} employee account(s). No email was sent.")

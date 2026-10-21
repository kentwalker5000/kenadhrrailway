"""Install the reviewed Ghana payroll template for one company."""

from django.core.management.base import BaseCommand, CommandError

from base.models import Company
from payroll.ghana import configure_ghana_payroll


class Command(BaseCommand):
    help = (
        "Configure Ghana resident PAYE and SSNIT payroll rules for one company. "
        "Does not assign contracts or generate payslips."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, required=True)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the configuration. Without this flag, only show the plan.",
        )

    def handle(self, *args, **options):
        company_id = options["company_id"]
        company = Company.objects.filter(pk=company_id).first()
        if company is None:
            raise CommandError(f"Company {company_id} does not exist.")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Preview: Ghana PAYE and SSNIT would be configured for {company}. "
                    "No contracts would be changed. Re-run with --apply to write it."
                )
            )
            return

        result = configure_ghana_payroll(company)
        self.stdout.write(
            self.style.SUCCESS(
                "Configured Ghana payroll: "
                f"{result['filing_status'].filing_status}; "
                f"{len(result['brackets'])} PAYE brackets; "
                f"{result['ssnit'].title}; "
                f"{result['salary_structure'].title}; "
                f"{result['national_service_structure'].title}; "
                f"{result['national_service_filing_status'].filing_status}."
            )
        )

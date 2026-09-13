"""Company-scoped payslip email delivery in a background thread."""

import logging
from contextvars import copy_context
from threading import Thread

from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import close_old_connections, connections
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import get_language, override

from base.backends import ConfiguredEmailBackend
from base.models import DynamicEmailConfiguration
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from payroll.models.models import Payslip
from payroll.views.views import payslip_pdf

logger = logging.getLogger(__name__)


class MailSendThread(Thread):
    """Send one email per employee, recording only confirmed SMTP acceptance."""

    def __init__(self, request, result_dict, ids, *, company_id, configuration):
        super().__init__()
        self.result_dict = result_dict
        self.ids = set(ids)
        self.request = request
        self.company_id = company_id
        self.configuration_id = configuration.pk
        self.host = request.get_host()
        self.protocol = "https" if request.is_secure() else "http"
        self.language = get_language()
        self.context = copy_context()
        self.accepted_count = 0
        self.failed_count = 0

    def run(self):
        # A new thread does not inherit the request/company ContextVars.
        self.context.run(self._run_scoped)

    def _run_scoped(self):
        close_old_connections()
        _thread_locals.request = self.request
        set_selected_company(str(self.company_id))
        try:
            with override(self.language):
                self._deliver()
        finally:
            _thread_locals.request = None
            connections.close_all()

    def _deliver(self):
        configuration = DynamicEmailConfiguration.objects.filter(
            Q(company_id=self.company_id) | Q(company_id__isnull=True, is_primary=True),
            pk=self.configuration_id,
        ).first()
        if not self.company_id or configuration is None:
            logger.warning("Payslip mail stopped: company mail configuration unavailable")
            self.failed_count = len(self.ids)
            return

        for original in self.result_dict.values():
            group_ids = {instance.pk for instance in original["instances"]}
            employee_id = original["employee_id"].pk
            try:
                if not group_ids or not group_ids.issubset(self.ids):
                    raise ValueError("Invalid payslip group")
                # Re-read inside the worker, retaining the exact company and employee.
                instances = list(Payslip.objects.filter(
                    pk__in=group_ids, employee_id=employee_id,
                    employee_id__employee_work_info__company_id=self.company_id,
                ).select_related("employee_id__employee_work_info"))
                if len(instances) != len(group_ids):
                    raise ValueError("Payslip no longer belongs to the selected employee/company")

                employee = instances[0].employee_id
                work_info = getattr(employee, "employee_work_info", None)
                work_email = (getattr(work_info, "email", None) or "").strip()
                recipient = work_email or (employee.email or "").strip()
                validate_email(recipient)
                validate_email(configuration.from_email)

                attachments = []
                for instance in instances:
                    response = payslip_pdf(self.request, instance.pk)
                    if (
                        response.status_code != 200
                        or response.get("Content-Type", "").split(";")[0] != "application/pdf"
                        or not response.content.startswith(b"%PDF-")
                    ):
                        raise ValueError("Payslip PDF generation failed")
                    attachments.append((
                        f"{instance.get_payslip_title()}.pdf",
                        response.content,
                        "application/pdf",
                    ))

                record = {"employee_id": employee, "instances": instances, "count": len(instances)}
                html_message = render_to_string(
                    "payroll/mail_templates/default.html",
                    {
                        "record": record,
                        "host": self.host,
                        "protocol": self.protocol,
                        "white_label_company_name": "KenadHr",
                        "current_year": timezone.localdate().year,
                    },
                )
                backend = ConfiguredEmailBackend(
                    configuration=configuration, fail_silently=False
                )
                sender = backend.dynamic_from_email_with_display_name
                email = EmailMessage(
                    "Your KenadHr payslips are ready",
                    html_message, sender, [recipient],
                    reply_to=[configuration.from_email], connection=backend,
                )
                email.content_subtype = "html"
                email.attachments = attachments

                if email.send() != 1:
                    raise ValueError("Mail server did not accept the message")

                Payslip.objects.filter(
                    pk__in=group_ids, employee_id=employee_id,
                    employee_id__employee_work_info__company_id=self.company_id,
                ).update(sent_to_employee=True)
                self.accepted_count += len(instances)
            except Exception as error:
                self.failed_count += len(group_ids)
                # SMTP errors and PDF context can contain payroll/account data.
                logger.warning(
                    "Payslip email failed for employee id %s (%s)",
                    employee_id, type(error).__name__,
                )

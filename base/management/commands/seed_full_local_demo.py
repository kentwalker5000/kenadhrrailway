"""Build a realistic, disposable 30-person company scenario for local QA."""

import calendar
import json
from datetime import date, datetime, time, timedelta

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


QA_EMAIL_SUFFIX = "@kenadhr.test"


class Command(BaseCommand):
    help = "Populate every enabled HR area with linked, clearly-labelled local QA data."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, required=True)

    def handle(self, *args, **options):
        from base.models import Company

        company = Company.objects.filter(pk=options["company_id"]).first()
        if company is None:
            raise CommandError(f"Company {options['company_id']} does not exist.")

        call_command("seed_qa_workforce", company_id=company.pk, stdout=self.stdout)
        with transaction.atomic():
            context = self._people(company)
            self._attendance(context)
            self._leave(context)
            self._documents(context)
            self._recruitment_and_onboarding(context)
            self._performance_and_projects(context)
            self._assets_and_helpdesk(context)
            self._offboarding_and_company_requests(context)
            self._council(context)
            self._payroll_extras(context)
            self._petty_cash(context)
            self._automation_and_reports(context)

        self.stdout.write(
            self.style.SUCCESS(
                "Full local QA company scenario is ready: 30 staff and linked records "
                "across the enabled HR modules. All generated records are labelled QA TEST."
            )
        )

    def _people(self, company):
        from base.models import (
            Department, EmployeeShift, EmployeeShiftDay, EmployeeShiftSchedule,
            EmployeeType, JobPosition, WorkType,
        )
        from employee.models import Employee, EmployeeWorkInformation
        from payroll.ghana import configure_ghana_payroll
        from payroll.models.models import Contract

        employees = list(
            Employee._base_manager.filter(email__endswith=QA_EMAIL_SUFFIX).order_by("badge_id")
        )
        if len(employees) != 30:
            raise CommandError(f"Expected 30 QA employees; found {len(employees)}.")

        types = {
            label: EmployeeType._base_manager.get_or_create(employee_type=label)[0]
            for label in ("Permanent", "Fixed-Term", "Internship", "National Service")
        }
        for value in types.values():
            value.company_id.add(company)

        work_types = {}
        for label in ("Office", "Remote", "Field"):
            item, _ = WorkType._base_manager.get_or_create(work_type=f"QA {label}")
            item.company_id.add(company)
            work_types[label] = item

        shifts = {}
        for label, start, end in (("QA Standard Shift", time(8, 30), time(17, 0)), ("QA Field Shift", time(7, 30), time(16, 0))):
            shift, _ = EmployeeShift._base_manager.get_or_create(employee_shift=label)
            shift.company_id.add(company)
            shifts[label] = shift
            for name in ("monday", "tuesday", "wednesday", "thursday", "friday"):
                day, _ = EmployeeShiftDay._base_manager.get_or_create(day=name)
                day.company_id.add(company)
                schedule, _ = EmployeeShiftSchedule._base_manager.get_or_create(
                    shift_id=shift, day=day,
                    defaults={"minimum_working_hour": "08:00", "start_time": start, "end_time": end},
                )
                schedule.company_id.add(company)

        department_names = {
            "HR": "People & Culture", "Finance": "Finance & Accounts", "IT": "Technology",
            "Program": "Programmes", "Project": "Programmes", "Research": "Programmes",
            "Field": "Programmes", "Monitoring": "Programmes", "Membership": "Programmes",
            "Communications": "Communications", "Training": "People & Culture",
            "Operations": "Operations", "Facilities": "Operations", "Procurement": "Operations",
            "Executive": "Executive Office", "Legal": "Executive Office", "Data": "Technology",
            "Accounts": "Finance & Accounts", "Administrative": "Operations", "Graduate": "People & Culture",
            "National": "Programmes", "Fixed-Term": "Programmes",
        }
        departments = {}
        payroll = configure_ghana_payroll(company)
        for index, employee in enumerate(employees, 1):
            role = employee.get_full_name()
            contract = Contract._base_manager.filter(employee_id=employee).order_by("pk").first()
            position_name = employee.employee_work_info.job_position_id.job_position if employee.employee_work_info.job_position_id else "QA Staff"
            while position_name.startswith("QA "):
                position_name = position_name[3:]
            department_label = next((value for key, value in department_names.items() if key in position_name), "Operations")
            department = departments.get(department_label)
            if department is None:
                department, _ = Department._base_manager.get_or_create(department=f"QA {department_label}")
                department.company_id.add(company)
                departments[department_label] = department
            position, _ = JobPosition._base_manager.get_or_create(
                job_position=f"QA {position_name}"[:50], department_id=department
            )
            position.company_id.add(company)
            if "National Service" in position_name:
                employment_type = types["National Service"]
            elif "Intern" in position_name:
                employment_type = types["Internship"]
            elif "Fixed-Term" in position_name:
                employment_type = types["Fixed-Term"]
            else:
                employment_type = types["Permanent"]
            is_field = department_label == "Programmes" and index % 3 == 0
            EmployeeWorkInformation._base_manager.filter(employee_id=employee).update(
                company_id=company, department_id=department, job_position_id=position,
                employee_type_id=employment_type,
                shift_id=shifts["QA Field Shift" if is_field else "QA Standard Shift"],
                work_type_id=work_types["Field" if is_field else ("Remote" if index % 7 == 0 else "Office")],
                reporting_manager_id=None,
                location="Accra HQ" if not is_field else "Greater Accra field sites",
            )
            if contract:
                contract.department = department
                contract.job_position = position
                if employment_type.employee_type == "Fixed-Term":
                    contract.contract_name = f"QA TEST - Fixed-Term Agreement - {employee.get_full_name()}"
                    contract.contract_end_date = date(2027, 6, 30)
                elif employment_type.employee_type == "Internship":
                    contract.contract_name = f"QA TEST - Internship Agreement - {employee.get_full_name()}"
                    contract.contract_end_date = date(2027, 3, 31)
                elif employment_type.employee_type == "National Service":
                    contract.contract_name = f"QA TEST - NSS Placement - {employee.get_full_name()}"
                    contract.contract_end_date = date(2027, 8, 31)
                    contract.filing_status = payroll["national_service_filing_status"]
                    contract.wage = 1800
                else:
                    contract.contract_name = f"QA TEST - Permanent Employment - {employee.get_full_name()}"
                contract.save()
                if employment_type.employee_type == "National Service":
                    contract.set_salary_structure(payroll["national_service_structure"])
        self._apply_organisation_chart(company, employees)
        self._refresh_draft_payslips(employees)
        return {"company": company, "employees": employees, "owner": employees[19], "work_types": work_types, "shifts": shifts}

    def _apply_organisation_chart(self, company, employees):
        """Build a usable three-level reporting tree for the QA workforce."""
        from base.models import JobPosition
        from employee.models import EmployeeWorkInformation
        from payroll.models.models import Contract

        by_badge = {employee.badge_id: employee for employee in employees}
        # badge: (display title, direct manager badge). Daniel is the root.
        hierarchy = {
            "QA-020": ("QA Chief Executive Officer", None),
            "QA-009": ("QA Executive Assistant to CEO", "QA-020"),
            "QA-015": ("QA Legal and Governance Advisor", "QA-020"),
            "QA-001": ("QA Head of People and Culture", "QA-020"),
            "QA-002": ("QA Head of Finance", "QA-020"),
            "QA-004": ("QA Head of Technology", "QA-020"),
            "QA-005": ("QA Head of Communications", "QA-020"),
            "QA-006": ("QA Head of Operations", "QA-020"),
            "QA-010": ("QA Head of Programmes", "QA-020"),
            "QA-011": ("QA Monitoring and Evaluation Manager", "QA-010"),
            "QA-019": ("QA Learning and Development Officer", "QA-001"),
            "QA-021": ("QA People and Culture Intern", "QA-001"),
            "QA-022": ("QA People and Culture Intern", "QA-001"),
            "QA-008": ("QA Accounts Assistant", "QA-002"),
            "QA-027": ("QA Fixed-Term Finance Officer", "QA-002"),
            "QA-016": ("QA Data Analyst", "QA-004"),
            "QA-028": ("QA Fixed-Term IT Support Officer", "QA-004"),
            "QA-029": ("QA Communications Intern", "QA-005"),
            "QA-013": ("QA Procurement Officer", "QA-006"),
            "QA-014": ("QA Administrative Officer", "QA-006"),
            "QA-018": ("QA Facilities Officer", "QA-006"),
            "QA-003": ("QA Programme Officer", "QA-010"),
            "QA-007": ("QA Research Officer", "QA-010"),
            "QA-012": ("QA Field Officer", "QA-011"),
            "QA-017": ("QA Membership Officer", "QA-011"),
            "QA-023": ("QA National Service Personnel", "QA-011"),
            "QA-024": ("QA National Service Personnel", "QA-011"),
            "QA-025": ("QA National Service Personnel", "QA-011"),
            "QA-026": ("QA Fixed-Term Project Officer", "QA-011"),
            "QA-030": ("QA Programme Intern", "QA-011"),
        }
        for badge, (title, manager_badge) in hierarchy.items():
            employee = by_badge[badge]
            info = employee.employee_work_info
            position, _ = JobPosition._base_manager.get_or_create(
                job_position=title, department_id=info.department_id
            )
            position.company_id.add(company)
            manager = by_badge[manager_badge] if manager_badge else None
            EmployeeWorkInformation._base_manager.filter(pk=info.pk).update(
                job_position_id=position, reporting_manager_id=manager
            )
            Contract._base_manager.filter(employee_id=employee).update(job_position=position)

    def _refresh_draft_payslips(self, employees):
        """Regenerate the QA-only September payslips after engagement changes."""
        from payroll.methods.methods import calculate_employer_contribution, save_payslip
        from payroll.views.component_views import payroll_calculation

        start, end = date(2026, 9, 1), date(2026, 9, 30)
        days = calendar.monthrange(start.year, start.month)[1]
        for employee in employees:
            calculation = payroll_calculation(
                employee, start, end,
                month_summary={"present": days, "pay_period_days": days},
            )
            if calculation is None:
                raise CommandError(f"Could not regenerate payroll for {employee.get_full_name()}.")
            payload = {
                "employee": employee, "start_date": calculation["start_date"],
                "end_date": calculation["end_date"], "status": "draft",
                "contract_wage": calculation["contract_wage"], "basic_pay": calculation["basic_pay"],
                "gross_pay": calculation["gross_pay"], "deduction": calculation["total_deductions"],
                "net_pay": calculation["net_pay"], "pay_data": json.loads(calculation["json_data"]),
                "installments": calculation["installments"], "group_name": "QA TEST DATA - SEP 2026",
            }
            calculate_employer_contribution(payload)
            save_payslip(**payload)

    def _attendance(self, context):
        from attendance.models import Attendance, AttendanceActivity
        from base.models import EmployeeShiftDay

        today = date.today()
        work_days = []
        cursor = today - timedelta(days=22)
        while len(work_days) < 12:
            if cursor.weekday() < 5:
                work_days.append(cursor)
            cursor += timedelta(days=1)
        day_map = {row.day: row for row in EmployeeShiftDay._base_manager.all()}
        for number, employee in enumerate(context["employees"], 1):
            info = employee.employee_work_info
            for day in work_days:
                if (number + day.day) % 11 == 0:
                    continue
                attendance, _ = Attendance._base_manager.get_or_create(
                    employee_id=employee, attendance_date=day,
                    defaults={
                        "shift_id": info.shift_id, "work_type_id": info.work_type_id,
                        "attendance_day": day_map.get(day.strftime("%A").lower()),
                        "attendance_clock_in_date": day, "attendance_clock_in": time(8, 35),
                        "attendance_clock_out_date": day, "attendance_clock_out": time(17, 5),
                        "attendance_worked_hour": "08:30", "minimum_hour": "08:00",
                        "attendance_validated": day != today,
                    },
                )
                if number <= 8 and day == work_days[-1]:
                    AttendanceActivity._base_manager.get_or_create(
                        employee_id=employee, attendance_date=day, clock_in=attendance.attendance_clock_in,
                        defaults={"shift_day_id": attendance.attendance_day_id, "clock_in_date": day},
                    )

    def _leave(self, context):
        from leave.models import AvailableLeave, LeaveRequest, LeaveType

        company = context["company"]
        annual, _ = LeaveType._base_manager.get_or_create(
            name="QA Annual Leave", company_id=company,
            defaults={"payment": "paid", "period_in": "year", "total_days": 20, "require_approval": "yes"},
        )
        sick, _ = LeaveType._base_manager.get_or_create(
            name="QA Sick Leave", company_id=company,
            defaults={"payment": "paid", "period_in": "year", "total_days": 10, "require_approval": "yes"},
        )
        today = date.today()
        for number, employee in enumerate(context["employees"], 1):
            for leave_type, allowance in ((annual, 20), (sick, 10)):
                AvailableLeave._base_manager.update_or_create(
                    employee_id=employee, leave_type_id=leave_type,
                    defaults={"available_days": allowance - (number % 4), "total_leave_days": allowance, "assigned_date": date(today.year, 1, 1)},
                )
            if number <= 12:
                start = today - timedelta(days=number + 2)
                LeaveRequest._base_manager.get_or_create(
                    employee_id=employee, leave_type_id=annual, start_date=start,
                    defaults={"end_date": start + timedelta(days=1), "requested_days": 2, "description": "QA TEST annual leave scenario.", "status": "approved" if number % 3 else "requested", "created_by": context["owner"]},
                )

    def _documents(self, context):
        from horilla_documents.models import (
            Document,
            DocumentRequest,
            HRDocumentFolder,
            HRLibraryDocument,
        )

        request, _ = DocumentRequest._base_manager.get_or_create(
            title="QA TEST - Identity and Employment Documents",
            format="pdf", defaults={"max_size": 2, "description": "Fictional local testing documents only."},
        )
        request.employee_id.add(*context["employees"])
        for employee in context["employees"]:
            document = Document._base_manager.filter(employee_id=employee, document_request_id=request).first()
            if document and not document.document:
                document.document.save(
                    f"{employee.badge_id}-qa-test-document.pdf",
                    ContentFile(b"QA TEST DATA ONLY - not a real identity or employment document."),
                    save=False,
                )
                document.title = f"QA TEST employment document - {employee.badge_id}"
                document.status = "approved"
                document.issue_date = date(2026, 1, 1)
                document.expiry_date = date(2027, 12, 31)
                document.save()

        # A separate, HR-owned library. These are company records, not files
        # attached to an individual employee or a document request.
        library_records = {
            "QA TEST - HR Policies": [
                ("QA TEST - Employee Handbook 2026", "Staff handbook and workplace standards."),
                ("QA TEST - Leave and Attendance Policy", "Reference policy for leave and timekeeping."),
            ],
            "QA TEST - Payroll and Benefits": [
                ("QA TEST - Salary Bands and Benefits Guide", "Internal payroll and benefits reference."),
            ],
            "QA TEST - Compliance and Governance": [
                ("QA TEST - Data Protection Register", "Local compliance testing record."),
                ("QA TEST - Board Resolutions Index", "Reference index for governance records."),
            ],
            "QA TEST - HR Templates": [
                ("QA TEST - Employment Contract Template", "Current test contract template."),
                ("QA TEST - Performance Review Template", "Quarterly performance review template."),
            ],
            "QA TEST - Health and Safety": [
                ("QA TEST - Workplace Safety Procedure", "Internal health and safety procedure."),
            ],
        }
        for folder_name, documents in library_records.items():
            folder, _ = HRDocumentFolder._base_manager.get_or_create(
                name=folder_name,
                company_id=context["company"],
                defaults={"description": "QA TEST local HR library folder."},
            )
            for title, description in documents:
                library_document, created = HRLibraryDocument._base_manager.get_or_create(
                    folder=folder,
                    title=title,
                    defaults={"description": description},
                )
                if created or not library_document.document:
                    library_document.description = description
                    library_document.document.save(
                        f"{title.lower().replace(' ', '-')}.txt",
                        ContentFile(f"{title}\nQA TEST DATA ONLY — local testing document.".encode()),
                        save=False,
                    )
                    library_document.save()

    def _recruitment_and_onboarding(self, context):
        from onboarding.models import CandidateStage, OnboardingStage, OnboardingTask
        from recruitment.models import Candidate, InterviewSchedule, Recruitment, Stage

        company = context["company"]
        position = context["employees"][0].employee_work_info.job_position_id
        recruitment, _ = Recruitment._base_manager.get_or_create(
            title="QA TEST - Programme Officer Recruitment", company_id=company,
            defaults={"description": "A realistic local recruitment pipeline.", "job_position_id": position, "vacancy": 2, "start_date": date.today() - timedelta(days=30), "end_date": date.today() + timedelta(days=30), "is_published": True, "publish_in_linkedin": False},
        )
        stages = {}
        for sequence, (name, stage_type) in enumerate((("Application Review", "applied"), ("Assessment", "test"), ("Panel Interview", "interview"), ("Offer", "interview")), 1):
            stages[name], _ = Stage._base_manager.get_or_create(recruitment_id=recruitment, stage=name, defaults={"stage_type": stage_type, "sequence": sequence})
        candidates = []
        for number, (name, stage_name) in enumerate((("Selina Boateng", "Application Review"), ("Ibrahim Abdul", "Assessment"), ("Naana Aidoo", "Panel Interview"), ("George Acquaah", "Offer")), 1):
            candidate, _ = Candidate._base_manager.get_or_create(
                email=f"qa.candidate.{number:02d}@kenadhr.test",
                defaults={"name": name, "recruitment_id": recruitment, "job_position_id": position, "stage_id": stages[stage_name], "mobile": f"0200000{number:03d}", "resume": ContentFile(b'QA TEST RESUME', name=f'qa-candidate-{number}.pdf'), "source": "application", "gender": "female" if number % 2 else "male", "schedule_date": datetime.combine(date.today() + timedelta(days=number + 1), time(10, 0)), "offer_letter_status": "accepted" if number == 4 else "not_sent"},
            )
            candidates.append(candidate)
            if number >= 3:
                InterviewSchedule._base_manager.get_or_create(candidate_id=candidate, interview_date=date.today() + timedelta(days=number), interview_time=time(10 + number, 0), defaults={"description": "QA TEST panel interview.", "completed": False})
        onboarding_stage, _ = OnboardingStage._base_manager.get_or_create(stage_title="QA TEST - Welcome and Setup", recruitment_id=recruitment, defaults={"sequence": 1, "is_final_stage": False})
        for title in ("Accept offer", "Submit onboarding documents", "Complete IT induction"):
            OnboardingTask._base_manager.get_or_create(task_title=f"QA TEST - {title}", stage_id=onboarding_stage, defaults={"is_required": True})
        CandidateStage._base_manager.get_or_create(candidate_id=candidates[-1], defaults={"onboarding_stage_id": onboarding_stage, "sequence": 1})

    def _performance_and_projects(self, context):
        from pms.models import EmployeeObjective, Objective, Period
        from project.models import Project, ProjectStage, Task, TimeSheet

        company, employees, owner = context["company"], context["employees"], context["owner"]
        period, _ = Period._base_manager.get_or_create(
            period_name="QA TEST - 2026 Q4",
            defaults={"start_date": date(2026, 10, 1), "end_date": date(2026, 12, 31)},
        )
        period.company_id.add(company)
        objective, _ = Objective._base_manager.get_or_create(title="QA TEST - Improve programme delivery", company_id=company, defaults={"description": "Fictional QA performance objective.", "duration_unit": "months", "duration": 3, "add_assignees": True})
        for number, employee in enumerate(employees[:12], 1):
            EmployeeObjective._base_manager.get_or_create(
                objective_id=objective, employee_id=employee,
                defaults={"objective": objective.title, "objective_description": objective.description, "created_at": date.today() - timedelta(days=20), "updated_at": date.today(), "start_date": date(2026, 10, 1), "end_date": date(2026, 12, 31), "status": "On Track" if number % 3 else "Behind", "progress_percentage": 20 + number * 4, "created_by": owner.employee_user_id},
            )
        project, _ = Project._base_manager.get_or_create(title="QA TEST - Community Outreach 2026", company_id=company, defaults={"status": "in_progress", "start_date": date(2026, 8, 1), "end_date": date(2026, 12, 15), "description": "Fictional programme delivery project."})
        stages = []
        for sequence, title in enumerate(("Planning", "Delivery", "Close-out"), 1):
            stage, _ = ProjectStage._base_manager.get_or_create(project=project, title=title, defaults={"sequence": sequence, "is_end_stage": sequence == 3})
            stages.append(stage)
        for number, employee in enumerate(employees[:9], 1):
            task, _ = Task._base_manager.get_or_create(title=f"QA TEST Outreach task {number}", project=project, defaults={"stage": stages[(number - 1) % 3], "status": "completed" if number % 4 == 0 else "in_progress", "start_date": date.today() - timedelta(days=14), "end_date": date.today() + timedelta(days=14), "description": "QA scenario task."})
            TimeSheet._base_manager.get_or_create(project_id=project, task_id=task, employee_id=employee, date=date.today() - timedelta(days=number), defaults={"time_spent": "07:30", "status": "completed", "description": "QA TEST timesheet entry."})

    def _assets_and_helpdesk(self, context):
        from asset.models import Asset, AssetAssignment, AssetCategory, AssetItem, AssetRequest
        from helpdesk.models import FAQ, FAQCategory, Ticket, TicketType

        company, employees, owner = context["company"], context["employees"], context["owner"]
        category, _ = AssetCategory._base_manager.get_or_create(asset_category_name="QA TEST - Staff Equipment", defaults={"asset_category_description": "Fictional equipment for local testing."})
        category.company_id.add(company)
        for number, employee in enumerate(employees[:15], 1):
            asset, _ = Asset._base_manager.get_or_create(asset_tracking_id=f"QA-LAP-{number:03d}", defaults={"asset_name": f"QA TEST Laptop {number}", "asset_purchase_date": date(2026, 1, 15), "asset_purchase_cost": 4500, "asset_category_id": category, "asset_status": "In-Use"})
            item, _ = AssetItem._base_manager.get_or_create(asset_id=asset, tracking_id=f"QA-LAP-{number:03d}", defaults={"status": "In-Use"})
            AssetAssignment._base_manager.get_or_create(asset_id=asset, asset_item_id=item, assigned_to_employee_id=employee, defaults={"assigned_date": date(2026, 2, 1), "assigned_by_employee_id": owner, "return_date": date(2027, 12, 31), "return_condition": "Pending return - QA test assignment", "return_status": "Healthy"})
        AssetRequest._base_manager.get_or_create(requested_employee_id=employees[16], asset_category_id=category, defaults={"asset_request_date": date.today() - timedelta(days=2), "description": "QA TEST monitor request.", "asset_request_status": "Requested"})
        ticket_type, _ = TicketType._base_manager.get_or_create(title="QA TEST - IT Service", company_id=company, defaults={"type": "service_request", "prefix": "QIT"})
        for number, employee in enumerate(employees[:6], 1):
            Ticket._base_manager.get_or_create(title=f"QA TEST - Support request {number}", employee_id=employee, ticket_type=ticket_type, defaults={"description": "Fictional IT support case for workflow testing.", "priority": "high" if number == 1 else "medium", "created_date": date.today() - timedelta(days=number), "assigning_type": "department", "raised_on": "QA Technology", "deadline": date.today() + timedelta(days=3), "status": "resolved" if number % 3 == 0 else "in_progress"})
        faq_category, _ = FAQCategory._base_manager.get_or_create(title="QA TEST - Staff Support")
        FAQ._base_manager.get_or_create(question="QA TEST - How do I request equipment?", category=faq_category, defaults={"answer": "Use the Asset Request screen. This is fictional test content."})

    def _offboarding_and_company_requests(self, context):
        from base.models import (
            Announcement, Holidays, RotatingShift, RotatingShiftAssign,
            RotatingWorkType, RotatingWorkTypeAssign, ShiftRequest, Tags,
            WorkTypeRequest,
        )
        from offboarding.models import Offboarding, OffboardingEmployee, OffboardingStage, ResignationLetter

        company, employees = context["company"], context["employees"]
        Announcement._base_manager.get_or_create(title="QA TEST - All Staff Meeting", defaults={"description": "Fictional announcement for testing comments and visibility.", "expire_date": date.today() + timedelta(days=30)})
        holiday, _ = Holidays._base_manager.get_or_create(name="QA TEST - Staff Planning Day", company_id=company, defaults={"start_date": date.today() + timedelta(days=20), "end_date": date.today() + timedelta(days=20), "is_specific": False})
        Tags._base_manager.get_or_create(title="QA TEST - High Potential", company_id=company, defaults={"color": "#2563eb"})
        ShiftRequest._base_manager.get_or_create(employee_id=employees[3], shift_id=context["shifts"]["QA Field Shift"], requested_date=date.today() + timedelta(days=4), defaults={"previous_shift_id": context["shifts"]["QA Standard Shift"], "description": "QA TEST temporary field assignment.", "approved": False})
        WorkTypeRequest._base_manager.get_or_create(employee_id=employees[6], work_type_id=context["work_types"]["Remote"], requested_date=date.today() + timedelta(days=2), defaults={"previous_work_type_id": context["work_types"]["Office"], "description": "QA TEST remote-work request.", "approved": False})
        rotating_shift, _ = RotatingShift._base_manager.get_or_create(
            name="QA TEST - Office/Field Rotation",
            defaults={"shift1": context["shifts"]["QA Standard Shift"], "shift2": context["shifts"]["QA Field Shift"]},
        )
        RotatingShiftAssign._base_manager.get_or_create(
            employee_id=employees[4], rotating_shift_id=rotating_shift,
            defaults={"start_date": date.today() - timedelta(days=7), "next_change_date": date.today() + timedelta(days=7), "current_shift": context["shifts"]["QA Standard Shift"], "next_shift": context["shifts"]["QA Field Shift"], "based_on": "after", "rotate_after_day": 14},
        )
        rotating_work, _ = RotatingWorkType._base_manager.get_or_create(
            name="QA TEST - Office/Remote Rotation",
            defaults={"work_type1": context["work_types"]["Office"], "work_type2": context["work_types"]["Remote"]},
        )
        RotatingWorkTypeAssign._base_manager.get_or_create(
            employee_id=employees[6], rotating_work_type_id=rotating_work,
            defaults={"start_date": date.today() - timedelta(days=7), "next_change_date": date.today() + timedelta(days=7), "current_work_type": context["work_types"]["Office"], "next_work_type": context["work_types"]["Remote"], "based_on": "after", "rotate_after_day": 14},
        )
        pipeline, _ = Offboarding._base_manager.get_or_create(title="QA Offboarding", company_id=company, defaults={"description": "Fictional departure workflow.", "status": "ongoing"})
        stage = OffboardingStage._base_manager.filter(offboarding_id=pipeline).order_by("id").first()
        if stage is None:
            stage = OffboardingStage._base_manager.create(offboarding_id=pipeline, title="QA TEST - Notice Received", type="initial")
        departing = employees[-1]
        offboard, _ = OffboardingEmployee._base_manager.get_or_create(employee_id=departing, defaults={"stage_id": stage, "notice_period": 30, "unit": "day", "notice_period_starts": date.today(), "notice_period_ends": date.today() + timedelta(days=30)})
        ResignationLetter._base_manager.get_or_create(employee_id=departing, defaults={"title": "QA TEST - Resignation Letter", "description": "Fictional offboarding test record.", "planned_to_leave_on": date.today() + timedelta(days=30), "status": "approved", "offboarding_employee_id": offboard})

    def _council(self, context):
        from council.models import CouncilDocument, CouncilLibraryFolder, CouncilMember

        company = context["company"]
        folder, _ = CouncilLibraryFolder._base_manager.get_or_create(name="QA TEST - Council Governance", company_id=company, defaults={"description": "Fictional governance records.", "access_level": "shared"})
        for name, role in (("Eleanor Addae", "chair"), ("Martin Sarpong", "secretary"), ("Beatrice Annan", "treasurer")):
            member, _ = CouncilMember._base_manager.get_or_create(full_name=name, company_id=company, defaults={"role": role, "email": f"qa.council.{role}@kenadhr.test", "phone": "0200000000", "organisation": "QA TEST Council", "term_start": date(2026, 1, 1), "term_end": date(2028, 12, 31)})
            document, _ = CouncilDocument._base_manager.get_or_create(title=f"QA TEST - {role.title()} Appointment", member=member, defaults={"description": "Fictional appointment record."})
            if not document.document:
                document.document.save(f"qa-{role}-appointment.pdf", ContentFile(b"QA TEST COUNCIL DOCUMENT"), save=True)
        library_document, _ = CouncilDocument._base_manager.get_or_create(title="QA TEST - Council Meeting Minutes", folder=folder, defaults={"description": "Fictional shared council minutes."})
        if not library_document.document:
            library_document.document.save("qa-council-minutes.pdf", ContentFile(b"QA TEST COUNCIL MINUTES"), save=True)

    def _payroll_extras(self, context):
        from payroll.models.models import LoanAccount

        employee = context["employees"][2]
        LoanAccount._base_manager.get_or_create(
            title="QA TEST - Salary Advance", employee_id=employee,
            defaults={"type": "advanced_salary", "loan_amount": 1200, "provided_date": date.today() - timedelta(days=20), "description": "Fictional salary advance for payroll testing.", "is_fixed": True, "installment_amount": 300, "installments": 4, "installment_start_date": date.today().replace(day=1), "settled": False},
        )

    def _petty_cash(self, context):
        """A realistic cash float and receipt-backed spending for local QA."""
        from petty_cash.models import PettyCashAccount, PettyCashEntry

        company, employees = context["company"], context["employees"]
        account, _ = PettyCashAccount._base_manager.get_or_create(
            name="QA TEST - Accra Office Float",
            company_id=company,
            defaults={
                "custodian": employees[13],
                "opening_balance": 1500,
                "currency": "GHS",
                "notes": "Fictional petty cash float for local QA only.",
            },
        )
        records = [
            (date.today() - timedelta(days=12), "top_up", "in", 1000, "Cash replenishment", "Finance team", "QA TEST - Monthly float top-up", "TOPUP-2026-09"),
            (date.today() - timedelta(days=9), "expense", "out", 186.50, "Office supplies", "Accra Stationers", "QA TEST - Printer paper and stationery", "RCPT-00421"),
            (date.today() - timedelta(days=6), "expense", "out", 320, "Transport", "Local transport", "QA TEST - Staff travel for field coordination", "RCPT-00434"),
            (date.today() - timedelta(days=3), "expense", "out", 95, "Refreshments", "Market purchase", "QA TEST - Water and meeting refreshments", "RCPT-00447"),
        ]
        for tx_date, entry_type, direction, amount, category, payee, description, reference in records:
            entry, _ = PettyCashEntry._base_manager.get_or_create(
                account=account,
                transaction_date=tx_date,
                reference=reference,
                defaults={
                    "entry_type": entry_type,
                    "direction": direction,
                    "amount": amount,
                    "category": category,
                    "payee": payee,
                    "description": description,
                    "company_id": company,
                },
            )
            if not entry.receipt and entry_type == "expense":
                entry.receipt.save(
                    f"qa-test-{reference.lower()}.pdf",
                    ContentFile(b"QA TEST PETTY CASH RECEIPT - fictional local testing data"),
                    save=True,
                )

    def _automation_and_reports(self, context):
        from base.models import HorillaMailTemplate
        from horilla_automations.models import MailAutomation

        template = HorillaMailTemplate._base_manager.first()
        MailAutomation._base_manager.get_or_create(
            title="QA TEST - New Employee Welcome",
            defaults={"model": "employee.models.Employee", "mail_to": "employee_user_id__email", "mail_details": "email", "mail_detail_choice": "", "trigger": "on_create", "mail_template": template, "delivery_channel": "notification", "condition_html": "", "condition_querystring": "", "condition": "[]"},
        )
        call_command("seed_standard_report_templates", stdout=self.stdout)

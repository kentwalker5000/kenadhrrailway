"""Employee self-service workspace, scoped to the signed-in staff member."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_safe


def _staff_employee(request):
    """Return the account's employee record, never a session-selected company."""
    return getattr(request.user, "employee_get", None)


def _staff_or_home(request):
    employee = _staff_employee(request)
    if employee is None:
        messages.error(request, _("Your account is not linked to a staff profile."))
        return None
    return employee


def _format_money(value, currency, position):
    try:
        amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0.00")
    formatted = f"{amount:,.2f}"
    return (
        f"{currency} {formatted}" if position == "prefix" else f"{formatted} {currency}"
    )


def _current_company(employee):
    return getattr(getattr(employee, "employee_work_info", None), "company_id", None)


def _staff_context(employee):
    """Build the small, personal data set used by the staff portal.

    Every record query starts from ``employee`` rather than a company filter.
    That keeps this page correct even if a stale session or URL is manipulated.
    """
    from attendance.models import Attendance
    from horilla_documents.models import Document
    from leave.models import AvailableLeave, LeaveRequest
    from payroll.currencies import get_currency_format
    from payroll.models.models import Payslip

    today = timezone.localdate()
    company = _current_company(employee)
    currency, currency_position = get_currency_format(
        company.pk if company is not None else None
    )

    balances = list(
        AvailableLeave.objects.filter(employee_id=employee)
        .select_related("leave_type_id")
        .order_by("leave_type_id__name")[:4]
    )
    total_leave_days = sum(
        Decimal(str(balance.available_days or 0))
        + Decimal(str(balance.carryforward_days or 0))
        for balance in balances
    )

    payslips = list(
        Payslip.objects.filter(
            employee_id=employee, status__in=["confirmed", "paid"]
        ).order_by("-end_date", "-pk")[:3]
    )
    for payslip in payslips:
        payslip.net_pay_display = _format_money(
            payslip.net_pay, currency, currency_position
        )
        payslip.pdf_url = reverse("payslip-pdf", kwargs={"id": payslip.pk})

    documents = list(
        Document.objects.filter(employee_id=employee)
        .select_related("document_request_id")
        .order_by("-pk")[:4]
    )
    for document in documents:
        document.view_url = reverse("view-file", kwargs={"id": document.pk})

    today_attendance = (
        Attendance.objects.filter(employee_id=employee, attendance_date=today)
        .order_by("-pk")
        .first()
    )
    document_counts = {
        status: Document.objects.filter(employee_id=employee, status=status).count()
        for status in ("requested", "approved", "rejected")
    }

    return {
        "today": today,
        "employee": employee,
        "work_info": getattr(employee, "employee_work_info", None),
        "company": company,
        "today_attendance": today_attendance,
        "leave_balances": balances,
        "total_leave_days": total_leave_days,
        "pending_leave_count": LeaveRequest.objects.filter(
            employee_id=employee, status="requested"
        ).count(),
        "upcoming_leave_count": LeaveRequest.objects.filter(
            employee_id=employee, status="approved", start_date__gte=today
        ).count(),
        "payslips": payslips,
        "documents": documents,
        "document_counts": document_counts,
        "currency": currency,
        "currency_position": currency_position,
    }


@require_safe
@login_required
def staff_home(request):
    employee = _staff_or_home(request)
    if employee is None:
        return redirect("home-page")
    context = _staff_context(employee)
    context["staff_section"] = "home"
    return render(request, "base/staff_portal.html", context)


@require_safe
@login_required
def staff_payslips(request):
    employee = _staff_or_home(request)
    if employee is None:
        return redirect("home-page")

    context = _staff_context(employee)
    from payroll.models.models import Payslip

    payslips = list(
        Payslip.objects.filter(
            employee_id=employee, status__in=["confirmed", "paid"]
        ).order_by("-end_date", "-pk")
    )
    for payslip in payslips:
        payslip.net_pay_display = _format_money(
            payslip.net_pay, context["currency"], context["currency_position"]
        )
        payslip.gross_pay_display = _format_money(
            payslip.gross_pay, context["currency"], context["currency_position"]
        )
        payslip.pdf_url = reverse("payslip-pdf", kwargs={"id": payslip.pk})
    context["payslips"] = payslips
    context["staff_section"] = "payslips"
    return render(request, "base/staff_payslips.html", context)


@require_safe
@login_required
def staff_documents(request):
    employee = _staff_or_home(request)
    if employee is None:
        return redirect("home-page")

    context = _staff_context(employee)
    from horilla_documents.models import Document

    documents = list(
        Document.objects.filter(employee_id=employee)
        .select_related("document_request_id")
        .order_by("-pk")
    )
    for document in documents:
        document.view_url = reverse("view-file", kwargs={"id": document.pk})
    context["documents"] = documents
    context["staff_section"] = "documents"
    return render(request, "base/staff_documents.html", context)


@require_safe
@login_required
def staff_attendance(request):
    """Send staff to the existing self-scoped attendance workflow."""
    if _staff_or_home(request) is None:
        return redirect("home-page")
    return redirect("view-my-attendance")


@require_safe
@login_required
def staff_leave(request):
    """Send staff to the existing self-scoped leave-request workflow."""
    if _staff_or_home(request) is None:
        return redirect("home-page")
    return redirect("user-request-view")


@require_safe
@login_required
def staff_profile(request):
    """Reuse the existing own-profile view rather than duplicating profile logic."""
    if _staff_or_home(request) is None:
        return redirect("home-page")
    from employee.views import employee_profile

    return employee_profile(request)

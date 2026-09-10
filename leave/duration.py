"""Shared, database-free leave duration helpers for attendance and payroll."""

from datetime import timedelta


def leave_payment_type(leave_type):
    """Prefer the configured payment type, retaining legacy records."""
    return leave_type.payment_type or leave_type.payment


def iter_leave_day_units(request, start_date, end_date):
    """Yield (date, fraction) without turning clipped half-day ends into full days.

    The original request boundaries determine the fraction, not the reporting
    window. A single-day request is counted once, including legacy null ends.
    """
    request_end = request.end_date or request.start_date
    day = max(start_date, request.start_date)
    last = min(end_date, request_end)
    while day <= last:
        breakdown = "full_day"
        if day == request.start_date:
            breakdown = request.start_date_breakdown
        elif day == request_end:
            breakdown = request.end_date_breakdown
        yield day, 0.5 if breakdown in ("first_half", "second_half") else 1.0
        day += timedelta(days=1)

# Attendance → leave → payroll integration checks

`test_attendance_leave_handoff.py` uses real attendance, leave, contract, and
payslip records in Django's separate test database. It exercises calculation,
the bulk-generation POST, persisted draft amounts, and the saved payslip page.
Uploads and email/cache backends are isolated from the demo environment.

```sh
python manage.py test payroll.tests.test_attendance_leave_handoff --keepdb
```

## Covered in this pass

- Approved full-day paid/unpaid leave reaches attendance totals; requested and
  rejected leave does not.
- Unpaid time reduces pay once, whether the contract takes it from basic pay or
  lists it as a separate deduction. For a four-day period at 100/day, with two
  present days, one paid leave day and one unpaid leave day, net pay is 300 in
  both modes when no other components apply.
- Bulk payroll uses validated attendance while retaining pending-validation
  details on the payslip. It does not overwrite Attendance's own cached hours.
- Contract windows are resolved independently for each employee. The summary
  used for each calculation matches that employee's covered dates. Monthly
  proration retains the requested period as the denominator, consistent with
  this path's existing period-based wage allocation.
- Missing or invalid generation dates produce field errors instead of crashes.
- Attendance conflict detection compares dates with dates, not model objects.

## Half-day and partially paid leave

- A shared duration helper preserves half-day start/end boundaries, including
  requests clipped to a reporting period and legacy single-day null end dates.
- Approving either half-day choice creates its attendance work record without
  exceeding the database message limit; both boundary choices use half a day.
- Half-day attendance and half-day leave combine into one accounted day. The
  unworked/uncovered half stays absent; a full attendance day overlapping leave
  still needs HR review. This compares day quantities, not clock-time overlap.
- Paid and unpaid summary totals retain fractions. The paid-leave category
  includes partially paid leave duration, with percentage reductions carried
  separately to payroll (not counted as a second full unpaid day).
- Percentage deductions scale by leave duration and the contract's computed or
  fixed deduction basis. Monthly summary payroll uses the same per-day basis
  for full unpaid and percentage-paid leave.
- Payroll uses the custom leave actually included in the attendance summary,
  respecting HR overrides and excluding holiday/week-off leave charges.
- The calendar and absence/conflict detail views use the same summary totals.
  Opening these views does not overwrite cached attendance hours.
- Payslips identify the partial-payment breakdown as already included in Loss
  of Pay. Both deduction modes still reduce net pay only once.

For a four-day period at 100/day, with the other days fully worked:

| Leave | Attendance on that date | Net pay, no other components |
| --- | --- | --- |
| Half-day paid | Half-day | 400 |
| Half-day unpaid | Half-day | 350 |
| Half-day at 50% pay | Half-day | 375 |
| Full day at 75% pay | None | 375 |

The correction affects newly calculated payslips. It does not automatically
recalculate, replace, or change the payment status of existing payslips.

## Remaining before live payroll

This is not a certification of the complete payroll system. Employee-specific
holiday/roster exceptions, genuinely unresolved attendance/leave conflicts,
closed contracts, multi-month periods, hourly-contract leave-pay policy, and
company-specific proration rules still need verification. The existing rule that
holds the period's pay for unresolved conflicts has not been redesigned here;
percentage leave is not deducted again on top of that hold.
No bank transfer, payment posting, or real employee email is part of these tests.

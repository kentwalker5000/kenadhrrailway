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

The correction affects newly calculated payslips. It does not automatically
recalculate, replace, or change the payment status of existing payslips.

## Remaining before live payroll

This is not a certification of the complete payroll system. Dedicated work is
still needed on half-day and custom-percentage leave: the attendance summary
currently groups leave into whole dates and legacy paid/unpaid categories.
Holiday/roster exceptions, unresolved attendance/leave conflicts, closed contracts,
multi-month periods, and company-specific proration rules also need verification.
No bank transfer, payment posting, or real employee email is part of these tests.

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

## Employee calendars and bulk conflict checks

- Shared calendars apply company scope and employee/department/job-position
  holiday assignments. Single-day holidays with a null end date are supported.
- A roster entry changes its date only; unspecified dates retain company weekly
  offs. An explicit workday removes the weekly off, but not a public holiday.
  Draft/published roster behavior is unchanged: both remain HR calendar inputs.
- Summary rows, calendar details, exports, attendance minimum-hour classification,
  leave exclusions, hourly breakdowns and approved overtime components now use
  these employee calendars. Overtime payment requires both validated attendance
  and overtime approval.
- The summary header displays a range when employees have different numbers of
  working days, while rows and exports retain the individual counts.
- Bulk payslip generation skips employees with unresolved attendance/leave
  conflicts and tells HR where to resolve them. Clear employees can proceed in
  the same batch. A skipped employee's existing payslip is not replaced.
- Weekly-off expansion no longer changes the process-wide first weekday, and
  skips fifth-week rules in months without a fifth calendar week.

No existing attendance or payslip records are backfilled by these changes.
Historical attendance with minimum hours computed before a roster change still
needs review; this pass does not silently rewrite it.

## Remaining before live payroll

This is not a certification of the complete payroll system. Individual and
scheduled payslip creation still use separate legacy calculation paths; the new
conflict skip is for bulk generation. Recurring holiday expansion, historical
roster edits, closed contracts, multi-month periods, hourly-contract leave-pay
policy and company-specific proration still need verification. The underlying
calculation's conflict-hold rule remains unchanged; bulk generation now stops
before saving a draft based on it.
No bank transfer, payment posting, or real employee email is part of these tests.

## Payslip email delivery

```sh
python manage.py test payroll.tests.test_payslip_mail payroll.tests.test_pdf_xss_guard --keepdb
node --test horilla_theme/tests/htmx_confirm.test.cjs
```

The email tests use synthetic records in the separate test database and mock
SMTP transport; no real employee receives a message. They cover:

- Web sends require POST, CSRF and payroll permissions. The API reports HTTP
  202 with `status: queued`, not a claim that delivery has completed.
- Both routes reject mixed-company selections and pass the exact company mail
  configuration to the worker. A different company's primary server is never
  used as a fallback.
- One email groups the selected payslips for each employee, addressed to their
  work email (or personal email when work email is blank). The sender is the
  configured mail address, not the HR user's address.
- A failed or non-PDF attachment prevents that employee's email. SMTP rejection,
  a zero send result, or an invalid recipient leaves its payslips unsent, while
  other employees in a batch can succeed.
- Sent flags update only after SMTP acceptance. Acceptance is not proof of
  inbox delivery; a later bounce remains possible. Existing sent flags are not
  backfilled, and queued background work is not a durable/retryable job queue.
- Company context reaches the worker and database connections are cleaned up.
- A real synthetic payslip and mail template are rendered. When wkhtmltopdf is
  absent, the installed xhtml2pdf library produces the PDF with compact print
  spacing. Its assets are restricted to local static/media files; remote logos
  are omitted. Active HTML is still rejected and browser cookies are not passed
  to the PDF renderer.

For visual QA only, set `PAYSLIP_PDF_QA_OUTPUT` to a temporary PDF path when
running the tests, then render its pages with `pdftoppm` and inspect them. That
artifact contains synthetic data only and should not be committed.

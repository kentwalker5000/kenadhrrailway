# Loan and salary-advance repayments

In Payroll → Loans & Salary Advances, record the employee, amount, provided
date, installment count and repayment start date. Select **Already paid outside
payroll** when the employee has already received the money. Otherwise a one-time,
non-taxable payroll allowance pays the principal in the period containing the
provided date. This option defaults to off for compatibility with existing records.

Repayments are fixed, post-tax deductions. A 1,200 advance over six installments
creates six monthly deductions of 200. The final installment absorbs rounding
differences, so the installments total the principal exactly. Dates stay anchored
to the original day: January 31, February 28, March 31, etc. Interest is not added.

Both manual and scheduled payroll use the same calculation. Scheduled payroll
now covers the **previous calendar month**, regardless of the configured run day.
For example, a run on October 25 covers September 1–30. Existing overlapping
payslips cause the scheduler to skip that employee and log a request for manual
review; it does not generate another overlapping salary.

## Repayment lifecycle

- Generating a draft reserves the installments on that payslip. A second period
  cannot collect them again. Regenerating the same draft retains its installments.
- Draft and confirmed payslips do not count as money repaid. Marking the payslip
  **Paid**, individually or in bulk, updates repayment totals. Paying the full
  principal automatically marks the loan settled.
- Deleting an editable draft releases its installments. Confirmed and paid
  payslips and their installment links remain protected.
- Unreserved overdue installments carry into the next payroll. Recovery that
  would make take-home pay negative, or exceed the principal already reserved
  across payslips, is rejected for review. Payroll does not silently forgive or
  truncate the debt.
- HR can adjust an unreserved installment. The remaining future amounts are
  redistributed with exact cent rounding. Setting an installment to zero defers
  it into later payments rather than recording a zero payment as repaid. An edit
  cannot change that installment or later installments already on a payslip.
- Manual settlement stops further collection. Resolve any unpaid payslips
  containing the loan first. Settled loans cannot be reopened or regenerate a
  new schedule.

Existing deduction-exempt salary structures and national-service policy still
exclude all deductions, including loan installments. Their policy has not changed.

## Applying the change

Apply migration `payroll.0013_loan_repayment_safeguards` using the application's
normal deployment process, then restart the web and scheduler processes.

The migration adds the external-disbursement choice and corrects the tax flags
of components not referenced by confirmed/paid payslips. It does not alter saved
payslip amounts or payment statuses. Regenerate and review existing editable
drafts to pick up the corrected calculation before confirming them. Components
already referenced by finalised payslips keep their historical configuration.

Older duplicate deductions or inaccurate paid statuses need separate payroll
review; this change does not infer refunds, reconcile bank transactions, or
rewrite historical payments. Existing loans default to payroll disbursement;
review that choice before creating a new payslip for an externally paid advance.

## Verification

```sh
python manage.py test payroll.tests.test_loan_repayments payroll.tests.test_ghana_payroll payroll.tests.test_attendance_leave_handoff --keepdb
python manage.py makemigrations payroll --check --dry-run
```

These tests use synthetic employees in Django's separate test database. They
cover manual/scheduled calculation, external disbursement, unchanged taxable
salary, reservation conflicts, arrears, rounding, edits, settlement, migration
preservation and existing Ghana/attendance payroll behavior. No bank payment or
employee email is sent.

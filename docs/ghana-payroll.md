# Ghana payroll setup

This project provides a Ghana resident-payroll template for the 2026 rules.
It is a starting point for regular resident employees; it does not replace a
review by the organisation's accountant, tax adviser, SSNIT, or GRA.

## What the template configures

- GHS as the payroll currency.
- Resident PAYE on taxable gross pay, using the annual bands effective
  1 September 2026: GH¢0–7,056 at 0%; next 960 at 5%; next 1,200 at 10%; next
  34,800 at 17.5%; next 192,000 at 25%; next 363,984 at 30%; and the balance
  above GH¢600,000 at 35%.
- Employee SSNIT as a 5.5% pre-tax deduction from basic pay and employer
  pension cost at 13%. For a normal monthly payroll, the 2026 caps use the
  GH¢69,000 monthly maximum insurable earning: GH¢3,795 employee and GH¢8,970
  employer per month.
- A separate **National Service — No Deductions** salary structure. This is
  for organisations that have confirmed that a particular person's allowance
  should not receive company payroll deductions. Its exemption flag blocks
  all deduction components, including global, assigned, conditional, loan,
  and compensation deductions. The matching **National Service — No PAYE**
  filing status also activates this exemption. Attendance-related loss of pay
  is separate and still applies.

The PAYE table comes from the [Ghana Revenue Authority PAYE guidance](https://gra.gov.gh/domestic-tax/tax-types/paye/).
The SSNIT rates and 2026 maximum insurable earnings come from [SSNIT's employer guidance](https://www.ssnit.org.gh/become-an-employer/)
and its [2026 public notice](https://www.ssnit.org.gh/wp-content/uploads/2026/01/Public-Notice-Min-Max-Insurable.pdf).

## Apply it

Preview first:

```powershell
.\.venv\Scripts\python.exe .\scripts\native.py manage setup_ghana_payroll --company-id 1
```

Then apply it:

```powershell
.\.venv\Scripts\python.exe .\scripts\native.py manage setup_ghana_payroll --company-id 1 --apply
```

The command is safe to re-run and deliberately does **not** assign employees,
contracts, or payslips. After review, assign the new Ghana PAYE filing status
and Ghana Statutory Payroll salary structure only to eligible resident staff.
For eligible National Service personnel, assign both the National Service
structure and the National Service filing status. Use them only for personnel
whose treatment has been confirmed by the organisation.

## Historical rules and finalised records

PAYE filing statuses have effective dates and a previous-version link. The
payroll period selects its applicable version, rather than using today's
rules for every month. The setup includes January 2024–August 2026 and
September–December 2026 versions. SSNIT monthly ceilings are 52,000 (2024),
61,000 (2025), and 69,000 (2026). Unsupported years or periods crossing
calendar months are rejected; add reviewed rules before running them.
These limits are versioned in code; the app does not automatically fetch legal
changes. The Ghana template requires monthly payroll.

Source for the earlier PAYE table: [GRA's 2024 amendment notice](https://gra.gov.gh/implementation-of-new-tax-laws-and-amendments/).
The 30% bracket ends at the explicitly published 600,000 annual top-rate
threshold. The notice's printed 30% band width is inconsistent with that
threshold; verify high-income historical payroll with your accountant.
Source for the later table: [GRA's September 2026 amendment](https://gra.gov.gh/news/portfolio/amendments-income-tax-act-2026-act-1178/).

For a complete September 2026 month with basic salary GH¢6,000 and no extras:
employee pension is 330, taxable pay is 5,670, PAYE is 1,022, net pay is 4,648,
and employer pension cost is 780. Employer cost is not deducted from net pay.

Confirmed and paid payslips cannot be regenerated, financially edited,
reopened, or deleted. Confirmation can still advance to paid. PostgreSQL
also enforces the lock for bulk updates and direct SQL. Corrections require
a separate adjustment process, not rewriting payment history.

Run `native.py manage migrate --noinput` when deploying. The migration repairs
the known incorrect pension caps and adds policy dates without changing staff
assignments or saved payslips. Existing drafts need regeneration after review;
previously finalised incorrect slips need reconciliation and adjustments.

## Review before a live payroll

- Enter each employee's actual basic salary and approved taxable/non-taxable
  allowances.
- Confirm residency, contract pay frequency, SSNIT number, and Tier 2 trustee.
- Add approved individual reliefs, provident-fund treatment, loans, and any
  company-specific deductions separately.
- Handle casual workers, non-residents, bonuses, benefits in kind, and junior
  staff overtime under their specific GRA rules; they are not automatically
  inferred from a regular salary component.
- Generate draft payslips, reconcile them against the GRA calculator and SSNIT
  contribution report, then approve payment.

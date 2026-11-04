# Configure loss of pay

Open **Payroll → Configuration** and select the **Loss of Pay** tab after
**Payslip Auto Generation**. The policy applies to employees
in the company assigned to your account.

- **Apply loss of pay** turns deductions for unpaid days and partially paid
  leave on or off.
- **Amount calculation** offers **Calculate from salary**, **Fixed amount per
  day**, or **Use existing contract rates** for compatibility.
- **Fixed amount per unpaid day** is in the payroll currency. It must be
  non-negative; zero is allowed. It is required when loss of pay is enabled
  and the fixed amount option is selected.

For example, a fixed daily amount of 80 deducts 80 for a full unpaid day, 40 for
a half unpaid day, and 20 for a full day paid at 75%. Turning loss of pay off
also removes the partial-leave deduction. Attendance counts remain visible.

Until a company policy is saved, existing contract settings continue to apply.
After saving, the company on/off switch overrides contract switches. Choosing
existing contract rates preserves each contract's rate calculation. These
controls no longer appear on the contract form. The contract's **Take loss of
pay from basic pay** field still controls whether the deduction appears in basic
pay or separately; it does not change net pay.

The page uses the Configuration page's payslip-auto-generation view/change
permissions. View-only users cannot save changes. Visiting the page does not
create or change a policy.

Unresolved attendance conflicts retain their existing payroll hold even when
loss of pay is disabled. Hourly contracts remain paid for recorded hours.
Attendance-summary payroll counts absences and unpaid leave; calculations
without a summary use approved leave records.

Apply migrations through `payroll.0015_company_loss_of_pay_policy` and reload
web and scheduler processes. Settings affect newly calculated payslips,
including scheduled calculations. Existing payslips keep their saved amounts;
review and regenerate editable drafts where appropriate.

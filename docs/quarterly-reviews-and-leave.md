# Quarterly reviews and leave approvals

## Quarterly performance

In Performance Settings → Review Periods, use **Reviews** on a period (or
**Open / Close Reviews** in its details). Select a company and a question
template, then choose **Open and assign reviews**. The user needs the period
change and feedback creation permissions.

Each active employee receives one review for the period. Their reporting
manager reviews them, their direct reports review them, and self-assessment
is included. Assigned reviews appear in the existing 360° Feedback page.
Opening the same period again adds missing employees without duplicating
existing reviews or changing already assigned reviewers.

HR can close submissions at any time. Submissions also require an active date
window, an assigned reviewer, all questions answered, and valid rating values.
An employee can submit a particular review only once. Closing a period does
not delete answers. Reopening does not reset completed reviews.

## Leave

The reporting manager uses **Review** first. The request stays pending and no
leave balance is deducted. A different company Admin/HR then uses **Approve**.
For the Admin/HR lead's own leave, the CEO reviews and then gives final
approval. Only final approval deducts leave. The same checks apply to individual and
bulk approval through the web and API.

The **Admin** and **HR Manager** groups receive the new
`leave.final_approve_leaverequest` permission. Approvers must have employee work
information linking them to the requesting employee's company. Superusers
also follow the manager-first sequence and cannot approve their own leave.

Missing reporting managers must be configured in employee work information.
Changes to leave dates, duration, type, employee, or reporting manager require
a fresh manager review. Existing approved requests are not changed.

The current local Q4 testing period has a five-question questionnaire and 32
employee reviews. All current leave types require approval. Administrators
should retain this setting rather than enable legacy automatic approval.

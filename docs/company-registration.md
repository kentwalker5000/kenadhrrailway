# Company registration

`/register/` creates a new company, its owner's login, employee profile, work
information and company-specific role in one database transaction. It works
after other companies have registered. The owner signs in using the work email
address entered on the form. No database initialization password is needed.

The welcome page directs owners to the dashboard's existing setup checklist.
Office state, postal code, logo, departments, jobs and shifts can be completed
later. The legacy first-run deployment wizard is disabled once a company has
a recorded owner.

Owners are normal active users, not Django staff or superusers. Each company's
role is separate. Initial permissions cover editing their company and managing
departments, job positions/roles, work types, employee types, shifts, employees,
work information and bank details. They do not include platform configuration,
shared authentication groups or the developer console. Additional module roles
can be granted through the existing company-scoped permission administration.

## Hosting settings

- `KENADHR_COMPANY_REGISTRATION=True` enables the form and its public links;
  `False` closes new registrations without affecting existing accounts.
- `COMPANY_SCOPED_PERMISSIONS=True` and `SINGLE_COMPANY_LOGIN=True` are required;
  the form fails closed if either isolation setting is disabled.
- `KENADHR_REGISTRATION_HOURLY_LIMIT=20` limits submissions per server-observed
  peer IP per hour. Configure shared Redis through `REDIS_URL` for consistent
  limits across workers. Forwarded IP headers are deliberately not trusted;
  behind a proxy the bucket may be shared by multiple visitors. Apply per-client
  limits at the trusted ingress before raising this application's limit.
- Use the real HTTPS hostname in `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.

Registration has CSRF protection, password validation, duplicate email checks,
a bot trap and transaction rollback. Invalid fields are displayed on the form;
passwords are never redisplayed. Email addresses are not ownership-verified by
this flow and no email is sent. Password recovery separately requires working
outbound email and a correct `PASSWORD_RESET_BASE_URL`.

This change tests registration and core company isolation, not an exhaustive
security audit of every module in the application. Test a disposable company
on the hosted deployment before accepting customers. No local employee records
or uploaded documents are transferred by deploying this code.

## Regression tests

```text
python manage.py test base.tests.test_company_registration base.tests.test_single_company_login base.tests.test_initialize_database_guard
```

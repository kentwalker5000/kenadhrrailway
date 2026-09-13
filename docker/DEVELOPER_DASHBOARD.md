# KenadHr developer dashboard

The dashboard at `/developer/` is for the platform developer, not an HR or
company administrator. It shows every registered company, its recorded
registration owner (for future registrations), company administrators, employee
counts and active/archived status. It can edit or archive a company, but it
does not delete companies or cross-assign any employee account.

To enable it, create a dedicated Django superuser that has **no Employee row**
and set its username in the deployment environment:

```sh
python manage.py createsuperuser
# .env
KENADHR_PLATFORM_DEVELOPER_USERNAMES=kenadhr-developer
```

For more than one technical operator, use comma-separated usernames. Restart
or reload the web process after changing the environment. Never put a company
HR/employee username in this setting: the application rejects that account as a
platform developer, preserving one employee account per company.

Existing companies are not backfilled with a guessed registration owner. The
dashboard honestly shows them as unrecorded where historical data did not
exist. New first-run company registrations record the onboarding administrator.

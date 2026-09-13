# KenadHr employee password reset

The intended production address is **https://www.kenadhr.com**. On 2026-09-13,
the hostname did not resolve from the development machine. Setting an email
URL does not register a domain, create DNS records, deploy the app or install
an HTTPS certificate. Those steps must be completed before public reset links
can work.

Local development deliberately uses `http://localhost:8000`; those links are
only usable on the computer running KenadHr. The old Django Site value
`example.com` is no longer used to construct credential links.

## Production configuration

After the domain points to the HTTPS app, put these values in the deployment's
environment, retaining any additional trusted hosts/origins the deployment needs:

```dotenv
PASSWORD_RESET_BASE_URL=https://www.kenadhr.com
PASSWORD_RESET_TIMEOUT=3600
ALLOWED_HOSTS=www.kenadhr.com
CSRF_TRUSTED_ORIGINS=https://www.kenadhr.com
```

The production Compose overlay reads `.env`; recreate its web service after
changing deployment environment values. In local Compose, Django can also read
the bind-mounted `.env` after a worker reload, but existing container environment
values take precedence. Do not point local accounts at a different production
database: a reset token belongs to the issuing installation's user and secret.

## Employee and HR workflow

- Employees choose **Forgot password** and enter their username. Recovery goes
  only to the registered work email, or personal email if work email is blank.
  The public response does not reveal whether the username exists.
- HR uses **Employee profile → Send password reset link**. The action enforces
  login, POST/CSRF, same-company membership and the existing HR/manager/self
  permissions on the server. HR sees acceptance/failure feedback without SMTP
  credentials or private server replies.
- Mail uses that employee's company's configured SMTP server and sender, with
  only a deliberately global primary server eligible as a fallback.
- Links are one-use, expire after one hour by default, and become invalid after
  a password, delivery email, company or account-state change. Inactive,
  archived and unusable-password accounts are not eligible. Old links issued
  before this change should be replaced with a new request.
- The confirmation page validates password strength and matching entries,
  offers a new-link action when invalid, then returns the employee to sign in.
  Existing sessions are invalidated by the password change.
- Requests are limited to 5 per username and 20 per source IP per hour using
  the configured shared cache. Forwarded IP headers are not blindly trusted;
  behind a reverse proxy the application may share a source-IP bucket. Retain
  the proxy's own per-client rate limits and configure trusted proxy handling
  before scaling this policy.
- Public mail runs in a short-lived background thread to avoid SMTP/account
  timing differences. It is not a durable job queue; a process interruption can
  drop a request, and the user may request again after waiting. SMTP acceptance
  is not proof of inbox delivery.
- Credential bodies remain redacted in mail logs. Application and Gunicorn
  logs redact reset URLs; the supplied nginx config omits credential-path
  access logs. Apply equivalent redaction to any additional proxy/CDN logs.

## Verification without touching live accounts

```sh
python manage.py test base.tests.test_employee_password_reset base.tests.test_reset_url_logging --keepdb
```

These tests use the separate test database and mocked SMTP. They exercise
request → mail → token → password validation → new-password login, as well as
expired/reused links, account/company isolation, throttles and session revocation.
No real employee password or email is changed by the tests.

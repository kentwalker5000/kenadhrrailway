# KenadHr security hardening

## Access boundaries

- Company HR/owners use their normal company settings and employee pages.
  `/admin/` is reserved for explicitly configured, unassigned platform developers.
- API bulk edits have an explicit field allowlist and validate company membership,
  related records and permissions. Mixed-company batches make no changes.
- Private `/media/` downloads are authorized through their owning records. Being
  signed in, knowing a filename or possessing another company's URL is insufficient.
  Only registered company logo images are public. Unregistered/orphan files and
  backup credentials are not downloadable. Historical uploads must be associated
  with their actual owning record; do not make the entire media directory public.
- PDF generation uses xhtml2pdf with scripts, remote assets, arbitrary local files
  and unauthorized media blocked. The pdfkit dependency has been removed.

## Passwords and verification

New and imported employees no longer receive phone-number passwords. HR should
send the existing **password reset link** action, or employees can use **Forgot
password**. Successful reset activates the account. `PASSWORD_RESET_BASE_URL`
must be the reachable HTTPS address, such as `https://www.kenadhr.com`.

Audit existing phone-number passwords before rolling out the change:

```sh
python manage.py secure_initial_passwords
python manage.py secure_initial_passwords --apply
```

The second command replaces only matching historical phone-number passwords and
requires those employees to reset. It does not send email. Changed passwords
invalidate existing sessions and JWTs; employees need access to their registered
email address. Platform operators should use unique random passwords and replace
temporary credentials immediately at `/change-password/`.

When `TWO_FACTORS_AUTHENTICATION=True`, both web and API require email verification.
The mail service being unavailable never grants access. Configure each company's
SMTP, or a global primary configuration. Developers require a valid account email
and a global primary SMTP configuration.

API clients POST credentials to `/api/v1/auth/login/`. With verification enabled,
the first response is **202** with `requires_otp` and `challenge_id`, not an access
token. POST the same credentials plus `challenge_id` and the six-digit `otp` to
complete login. Codes expire after five minutes, permit at most five wrong
attempts and cannot be reused. Resends are limited. A **503** means mail delivery
is unavailable; **429** means retry later. Clients must support this handshake
before enabling the setting. Tokens without verification are rejected after MFA
is enabled; changes to company assignment or account activation also revoke access.
Existing API tokens without a company claim must sign in again after this upgrade.
The password-change page is standalone so pending accounts do not trigger protected
background navigation or notification requests before completing activation.

## Local versus production

The development stack remains HTTP on **127.0.0.1:8000**, not all network interfaces.
It persists a generated development secret; commands and workers read the same key.
Never expose this DEBUG stack directly to the internet.

Production uses `docker-compose.prod.yml`: no direct application port, HTTP-to-HTTPS
redirect, TLS 1.2/1.3, secure cookies and strict host/secret validation. Set:

- `SECRET_KEY`: unique random value of at least 50 characters.
- `DB_INIT_PASSWORD`: unique random bootstrap secret of at least 20 characters.
- Explicit `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and HTTPS reset origin.
- Strong database/Redis credentials and matching connection URLs.
- `TLS_CERT_DIR`: a directory **outside Git** containing real `fullchain.pem` and
  `privkey.pem` files for your domain. Protect the private key and arrange certificate
  renewal plus an nginx reload. The configuration does not obtain certificates.

After configuring DNS, certificates and secrets:

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py check --deploy
```

Do not switch an existing database's credentials merely by editing Compose:
coordinate the database role password and application connection settings.
Do not rotate Django's signing secret unintentionally: it invalidates sessions
and reset links. No automated certificate setup or public deployment is implied.

Security, dependency, secret scanning and test workflows now include `main`.
Regression tests cover these boundaries, but they are not a substitute for a
deployment review, tested backups, monitoring and an independent security audit.

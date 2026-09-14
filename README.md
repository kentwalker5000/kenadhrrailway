# KenadHr

[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL%20v2.1-blue.svg)](LICENSE)

KenadHr is a human resource management application built on the open-source
[Horilla HRMS](https://github.com/horilla/horilla-hr) project.

Use the `main` branch of **this repository** for KenadHr. The upstream repository
and its prebuilt Docker images do not include this project's changes.

## What is included

- Employee records, recruitment, onboarding, and offboarding.
- Attendance, leave, payroll, and performance management.
- Assets, helpdesk, projects, and reporting.
- One company per user account: signing in determines the account's company.
- A company profile for permitted HR administrators to maintain their own
  company's details, without an account-level company switcher.
- KenadHr product branding, with company names and uploaded company logos kept
  separate from the product identity.

These are application capabilities, not a certification of production readiness.
Test your organization's workflows, permissions, integrations, and deployment
configuration before using real employee data.

## Run locally on Windows without Docker

On a computer with the native setup configured, double-click `Start-KenadHr.cmd`
to start PostgreSQL, KenadHr, and its background scheduler. Open
<http://localhost:8000>. Use `Stop-KenadHr.cmd` to stop them without removing data.

See [Windows native setup](docs/windows-native.md) for VS Code commands,
pgAdmin connection details, backups, and the one-time migration from Docker.
This is a local development setup; hosting still needs production configuration.

## Alternative: run locally with Docker

Install Git, Docker, and Docker Compose. On Windows, run these commands in the
VS Code PowerShell terminal with Docker Desktop running:

```powershell
git clone --branch main https://github.com/aduseimedia-eng/kenadhr.git
cd kenadhr
docker compose up --build -d
docker compose ps
docker compose logs --tail 100 web scheduler
```

Open <http://localhost:8000> when the web service is healthy. First startup applies
database migrations and collects static assets, so it can take a few minutes.
Complete database initialization to set up the initial administrator and company.

If you already have this project open in VS Code, run the Docker commands from
that existing checkout; there is no need to clone it again or rename its folder.

The development Compose file contains local-only credentials and enables debug
mode. Do not expose this configuration to the internet.

### View the existing database in pgAdmin 4

KenadHr already uses PostgreSQL. pgAdmin is a separate database management tool,
not a replacement database. Keep Docker running while using this connection.

After `docker compose up -d`, import [docker/pgadmin-servers.json](docker/pgadmin-servers.json)
through pgAdmin's **Tools > Import/Export Servers**, keeping existing servers.
The new connection appears under **KenadHr > KenadHr Local**. Alternatively,
register a server manually with these development-only settings:

| Setting | Value |
| --- | --- |
| Host | `127.0.0.1` |
| Port | `5434` |
| Maintenance database | `horilla_db` |
| Username | `horilla_user` |
| Password | `horilla_pass` (local development only) |

Server definitions do not include passwords; enter the database password when
pgAdmin asks. An existing pgAdmin **master password** is a separate credential.
Expand **Databases > horilla_db > Schemas > public > Tables** to browse the data.
Avoid editing HR records directly in SQL: that bypasses application validation.

The port is bound to localhost only, and the production overlay removes it.
If port 5434 is occupied, set `KENADHR_DB_PORT` in your ignored `.env` file and
use the same port in pgAdmin. The app still connects internally to `db:5432`.
This setup does not move the database or change any existing employee records.
See [pgAdmin's import instructions](https://www.pgadmin.org/docs/pgadmin4/latest/import_export_servers.html).

### Stop local services

To stop the local stack while preserving its data:

```powershell
docker compose stop
```

Keep the database and media volumes. Do not use `docker compose down -v` unless
you intentionally want to remove local data and have the backups you need.

## Development and checks

Create a feature branch from KenadHr's `main`, keep commits focused, and open pull
requests against `main` in this repository. Upstream branch names such as `2.0`
and `dev/v2.0` are not the target for KenadHr changes.

With the local stack running:

```powershell
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py makemigrations --check --dry-run
docker compose exec -T web python manage.py test base.tests.test_product_branding base.tests.test_single_company_login base.tests.test_company_settings --keepdb
```

These are focused checks, not the full application's test suite. Run the relevant
module and workflow tests for each change. Include tests and documentation with
user-facing changes.

## Branding maintenance

The product name is exactly **KenadHr**, without a space. The editable logo sources
are in `static/images/ui/kenadhr-mark.svg` and
`static/images/ui/kenadhr-wordmark.svg`. To regenerate email-compatible PNGs and
favicon sizes after editing those SVGs:

```powershell
docker compose exec -T web python scripts/render_brand_assets.py
docker compose exec -T web python manage.py collectstatic --noinput
```

The PNG renderer uses PyMuPDF from the application's existing dependencies.
Refresh the browser with **Ctrl + Shift + R** if old assets are cached.

Do not globally replace internal `horilla` module names, database identifiers,
integration headers, or the scheduler's `Horilla Bot` username. They remain for
compatibility; the service account's display name is `KenadHr System`. Preserve
customer-authored content, historical records, and upstream license notices.

## Mail configuration and testing

Open the **Mail Servers** page in Settings with an account permitted to manage mail
settings. Set the SMTP host, port, username, password, and sender address supplied
by your email provider. Keep credentials out of Git and screenshots.

- Match the encryption mode to the server: **Use SSL** starts an encrypted
  connection immediately; **Use TLS** upgrades an SMTP connection with STARTTLS.
  Do not enable both options together.
- Use a practical timeout, such as 30 seconds, and disable **Fail Silently** while
  diagnosing connection or authentication problems.
- Run the server's test-email action with a recipient you control. It uses the
  selected server and does not allow testing another company's configuration.
- Success means the mail server accepted the message, not that it reached the
  inbox. Check the recipient's inbox and spam folder to confirm delivery.

The connection and test-email regression tests do not send real mail:

```powershell
docker compose exec -T web python manage.py test base.tests.test_mail_delivery base.tests.test_email_log_privacy --keepdb
```

## Deployment and support

[The Docker guide](docker/README.md) documents the Compose services, configuration,
backups, and deployment operations. It includes inherited upstream references;
use this repository's `main` source and the clone instructions above for KenadHr.
Do not assume an upstream image or release includes KenadHr's account scoping or
branding changes.

For non-sensitive KenadHr bugs and feature requests, use
[this repository's issue tracker](https://github.com/aduseimedia-eng/kenadhr/issues).
Do not put vulnerabilities, credentials, or employee records in public issues.
Arrange a private reporting channel with the KenadHr repository owner for
KenadHr-specific security findings. [SECURITY.md](SECURITY.md) retains the upstream
Horilla reporting policy; it is not a KenadHr support agreement.

## License and upstream credits

This project is licensed under [LGPL-2.1](LICENSE). KenadHr builds on the work of
the Horilla team and contributors. Existing copyright notices and the
[open-source notices](templates/legal/open_source_notices.html) are retained.

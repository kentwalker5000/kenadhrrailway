# KenadHr on Windows without Docker

This is a **localhost development setup**. It runs PostgreSQL 16, Django's local
web server, and one background scheduler directly on Windows. pgAdmin 4 manages
PostgreSQL; pgAdmin itself is not the database. This is not a Railway deployment
or an internet-facing production configuration.

## Daily use on the configured computer

Double-click `Start-KenadHr.cmd` in the project folder. It starts PostgreSQL,
the app, and the scheduler, then opens <http://localhost:8000>.
Docker Desktop and the pgAdmin window do not need to be running.

Alternatively, use the VS Code PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe .\scripts\native.py start
.\.venv\Scripts\python.exe .\scripts\native.py status
```

Stop with `Stop-KenadHr.cmd`, or:

```powershell
.\.venv\Scripts\python.exe .\scripts\native.py stop
```

Stopping preserves all data. Avoid stopping while a payslip, email, import, or
other background operation is in progress. The supervisor prevents duplicate
native schedulers and stops only its own child processes. PostgreSQL is a
user-owned process started by the launcher, not an automatically starting
Windows service. Start KenadHr again after restarting your computer.

The local app uses Django's in-memory cache instead of Redis. Cache-only state,
including password-reset cooldowns, resets when the web process restarts.
Persistent records and sessions remain in PostgreSQL.

## pgAdmin connection

Import `%LOCALAPPDATA%\KenadHr\native\pgadmin-servers.json` through **Tools >
Import/Export Servers**, with **Remove all existing servers** turned off.
Do not import it repeatedly: that creates duplicate registrations. If it was
imported while pgAdmin was open, reopen pgAdmin to refresh the tree.

Expand **Servers > KenadHr Native (Windows)**. The older **KenadHr > KenadHr
Local** connection points to the stopped Docker database; it is not the active
Windows database.

| Setting | Native connection |
| --- | --- |
| Host | `127.0.0.1` |
| Port | `5435` (unless changed during setup) |
| Database | `kenadhr_db` |
| Username | `kenadhr_user` |
| Password | Generated during migration; see `%LOCALAPPDATA%\KenadHr\native\pgadmin-access.txt` |

After connecting, expand **Databases > kenadhr_db > Schemas > public > Tables**.
The password is not `horilla_pass` or your KenadHr account password. pgAdmin's
master password is also separate. Avoid editing HR records directly with SQL;
that bypasses application validation and audit workflows.

## Configuration, files, and checks

- Python dependencies: the project's ignored `.venv`, using Python 3.12.
- Runtime configuration and credentials: `%LOCALAPPDATA%\KenadHr\native\config.json`.
- Native database files: `%LOCALAPPDATA%\KenadHr\native\postgres-data`.
- Uploaded files: the project's ignored `media` directory.
- Logs: `web.log`, `scheduler.log`, `runner.log`, and `postgres.log` in the native directory.
- Pre-migration backup: `%LOCALAPPDATA%\KenadHr\backups\docker-migration-<timestamp>`.

These private files are intentionally outside Git (or ignored). Never commit or
share `config.json`, database dumps, uploads, or SMTP credentials. Restrict the
KenadHr runtime directory's Windows permissions to your account and system
administrators. PostgreSQL listens on `127.0.0.1` only, with SCRAM password
authentication. Existing PostgreSQL 13/14 installations are left untouched.

Use the runner for management commands so they use the native database and the
preserved signing key, rather than the fallback SQLite configuration:

```powershell
.\.venv\Scripts\python.exe .\scripts\native.py manage check
.\.venv\Scripts\python.exe .\scripts\native.py manage migrate --check
.\.venv\Scripts\python.exe .\scripts\native.py manage run_scheduler --list
.\.venv\Scripts\python.exe -m unittest discover -s scripts/tests -v
```

`manage run_scheduler --list` only lists jobs. Do not launch a second scheduler
while the native runner is active. Restart the app after changing Python code;
automatic reloading is deliberately disabled for the background launcher:

```powershell
.\.venv\Scripts\python.exe .\scripts\native.py restart
```

## One-time migration for another local development checkout

The migration helper is deliberately limited to this repository's development
Docker connection (`127.0.0.1:5434`, `horilla_db`, documented dev credentials).
It is not a production migration or a general-purpose database restore tool.

1. Install Python 3.12 and create `.venv`; install `requirements.txt` in it.
2. Obtain PostgreSQL **16** Windows binaries from the [official download page](https://www.postgresql.org/download/windows/)
   or [EDB's binaries](https://www.enterprisedb.com/download-postgresql-binaries).
   Use a separate directory and free port; do not overwrite other PostgreSQL installations.
3. Restrict `%LOCALAPPDATA%\KenadHr` permissions to your account and system
   administrators before storing any credentials or backups there.
4. Keep the original Docker stack running and stop making changes to its data.
   Run the helper from the project using the new PostgreSQL binary directory:

```powershell
.\.venv\Scripts\python.exe .\scripts\migrate_to_native.py --pg-bin 'C:\path\to\pgsql\bin'
```

The helper creates a new database, pauses Docker web/scheduler, makes a binary
database backup and media copy, restores them, and compares every public table,
sequence, and uploaded file. It retains the original signing key and refuses
to overwrite existing native database files/configuration or differing media.
If copying/verifying fails, it attempts to restart the original Docker writers
and leaves the backup for investigation. An incomplete native setup must be
reviewed before retrying; do not delete files blindly.

After verification, run native checks, confirm no pending migrations, collect
static files, start the app, and test sign-in, company access, documents, PDFs,
mail configuration, and scheduled-job registration. Then stop the remaining
Docker database/Redis services. Never start Docker web/scheduler and the native
app together: they would write to separate copies that diverge.

## Recovery and eventual Railway hosting

The original Docker volumes are retained as a pre-migration fallback. They do
**not** receive new native changes. Once the native app has been used, take a
fresh native database and media backup before any rollback; blindly restarting
the old Docker copy would omit those newer changes.

For Railway, provision PostgreSQL, restore a fresh native backup, configure the
app's `DATABASE_URL`, and move uploaded files to persistent storage. Also set
production secrets, HTTPS/domain settings, a shared cache, and exactly one
scheduler. Account reset links must use the reachable hosted domain, not
localhost. Local PostgreSQL and its files should not be exposed to the internet.

References: [pgAdmin import](https://www.pgadmin.org/docs/pgadmin4/latest/import_export_servers.html),
[PostgreSQL backups](https://www.postgresql.org/docs/16/app-pgdump.html),
[Railway PostgreSQL](https://docs.railway.com/databases/postgresql).

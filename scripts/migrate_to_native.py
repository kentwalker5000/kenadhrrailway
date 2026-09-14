"""One-time, verified copy of the local development Docker data to Windows.

Never drops a database, removes a Docker volume, or overwrites a configured
native installation. Backups contain private HR data and stay outside Git.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

import psycopg2
from psycopg2 import sql

from native import CONFIG, HIDDEN, NATIVE_DIR, ROOT, port_busy, postgres


def snapshot(connection):
    """Compare every public table and sequence without exposing employee data."""
    result = {"tables": {}, "sequences": {}}
    with connection.cursor() as cursor:
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(
                sql.SQL("SELECT row_to_json(t)::text FROM public.{} t").format(
                    sql.Identifier(table)
                )
            )
            rows = sorted(
                hashlib.sha256(row[0].encode()).hexdigest() for row in cursor.fetchall()
            )
            result["tables"][table] = {
                "count": len(rows),
                "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest(),
            }
        cursor.execute(
            "SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename"
        )
        for sequence in [row[0] for row in cursor.fetchall()]:
            cursor.execute(
                sql.SQL("SELECT last_value, is_called FROM public.{}").format(
                    sql.Identifier(sequence)
                )
            )
            result["sequences"][sequence] = list(cursor.fetchone())
    return result


def media_manifest(directory):
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_pgadmin_access(config):
    """Keep human-readable local database credentials outside Git and logs."""
    (NATIVE_DIR / "pgadmin-access.txt").write_text(
        "KenadHr Native (Windows) - LOCAL DATABASE ACCESS\n"
        "Keep this file private. This is not your KenadHr sign-in password.\n\n"
        "Host: 127.0.0.1\n"
        f"Port: {config['pg_port']}\n"
        f"Database: {config['database']}\n"
        f"Username: {config['database_user']}\n"
        f"Password: {config['database_password']}\n",
        encoding="utf-8",
    )


def copy_media(source, destination):
    """Never overwrite a different existing file in the checkout."""
    for name, digest in media_manifest(source).items():
        target = destination / name
        if (
            target.exists()
            and hashlib.sha256(target.read_bytes()).hexdigest() != digest
        ):
            raise RuntimeError(
                f"Existing local media file differs: {name}. No files overwritten."
            )
    shutil.copytree(source, destination, dirs_exist_ok=True)
    actual = media_manifest(destination)
    if any(
        actual.get(name) != digest for name, digest in media_manifest(source).items()
    ):
        raise RuntimeError("Media verification failed.")


def migrate(pg_bin, port):
    if os.name != "nt":
        raise RuntimeError("This migration is for Windows only.")
    if CONFIG.exists() or (NATIVE_DIR / "postgres-data").exists():
        raise RuntimeError(
            "Native configuration/data already exists. Refusing to overwrite or re-import it."
        )
    if port_busy(port):
        raise RuntimeError("The selected native PostgreSQL port is occupied.")
    version = subprocess.check_output(
        [str(pg_bin / "postgres.exe"), "--version"], text=True
    ).strip()
    if " 16." not in version:
        raise RuntimeError("Use PostgreSQL 16 binaries to match the source database.")
    source_kwargs = dict(
        host="127.0.0.1",
        port=5434,
        dbname="horilla_db",
        user="horilla_user",
        password="horilla_pass",
        connect_timeout=5,
    )
    with psycopg2.connect(**source_kwargs) as source:
        if source.server_version // 10000 != 16:
            raise RuntimeError("The source database is not PostgreSQL 16.")
    # Refuse a second copy of application data in the target checkout.
    existing = [name for name in media_manifest(ROOT / "media") if name != ".gitkeep"]
    if existing:
        raise RuntimeError(
            "The checkout already contains media. Back it up and resolve the overlap first."
        )

    NATIVE_DIR.mkdir(parents=True, exist_ok=True)
    backup = (
        NATIVE_DIR.parent
        / "backups"
        / datetime.now().strftime("docker-migration-%Y%m%d-%H%M%S")
    )
    backup.mkdir(parents=True, exist_ok=False)
    app_password, admin_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    config = {
        "project": str(ROOT),
        "pg_bin": str(pg_bin),
        "pg_data": str(NATIVE_DIR / "postgres-data"),
        "pg_port": port,
        "migration_verified": False,
        "backup": str(backup),
        "admin_user": "kenadhr_admin",
        "admin_password": admin_password,
        "database": "kenadhr_db",
        "database_user": "kenadhr_user",
        "database_password": app_password,
        "environment": {
            "DATABASE_URL": f"postgres://kenadhr_user:{app_password}@127.0.0.1:{port}/kenadhr_db",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": str(port),
            "DEBUG": "1",
            "HORILLA_ENV": "development",
            "ALLOWED_HOSTS": "localhost,127.0.0.1",
            "CSRF_TRUSTED_ORIGINS": "http://localhost:8000,http://127.0.0.1:8000",
            "PASSWORD_RESET_BASE_URL": "http://localhost:8000",
            "SECURE_SSL_REDIRECT": "0",
            "REDIS_URL": "",
            "SECRET_KEY_FILE": "",
            "DB_INIT_PASSWORD": secrets.token_urlsafe(32),
            "BACKUP_DIR": str(NATIVE_DIR.parent / "backups" / "scheduled"),
        },
    }
    write_json(CONFIG, config)
    password_file = NATIVE_DIR / "initdb-password.tmp"
    try:
        password_file.write_text(admin_password + "\n", encoding="utf-8")
        subprocess.run(
            [
                str(pg_bin / "initdb.exe"),
                "-D",
                config["pg_data"],
                "-U",
                config["admin_user"],
                "--pwfile",
                str(password_file),
                "--auth=scram-sha-256",
                "--encoding=UTF8",
                "--locale=C",
            ],
            check=True,
            creationflags=HIDDEN,
        )
    finally:
        password_file.unlink(missing_ok=True)
    postgres(config, "start")
    target_admin = dict(
        host="127.0.0.1",
        port=port,
        dbname="postgres",
        user=config["admin_user"],
        password=admin_password,
        connect_timeout=5,
    )
    admin = psycopg2.connect(**target_admin)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            # CREATEDB permits isolated Django test databases in this dedicated
            # local development cluster. This is not a production role template.
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE kenadhr_user LOGIN CREATEDB NOSUPERUSER NOCREATEROLE PASSWORD {}"
                ).format(sql.Literal(app_password))
            )
            cursor.execute(
                "CREATE DATABASE kenadhr_db OWNER kenadhr_user TEMPLATE template0 ENCODING 'UTF8'"
            )
    finally:
        admin.close()

    # Quiesce writers for a consistent database + media copy. The original
    # containers and named volumes remain available throughout and afterwards.
    print("Pausing Docker web/scheduler for the final consistent backup...", flush=True)
    subprocess.run(
        ["docker", "compose", "stop", "web", "scheduler"], cwd=ROOT, check=True
    )
    try:
        subprocess.run(
            ["docker", "compose", "cp", "web:/app/media", str(backup / "media")],
            cwd=ROOT,
            check=True,
        )
        with psycopg2.connect(**source_kwargs) as source:
            before = snapshot(source)
        write_json(backup / "database-manifest.json", before)
        write_json(backup / "media-manifest.json", media_manifest(backup / "media"))
        original_env = ROOT / ".env"
        if original_env.is_file():
            shutil.copy2(original_env, backup / "original.env")
        dump_env = {**os.environ, "PGPASSWORD": source_kwargs["password"]}
        archive = backup / "database.dump"
        subprocess.run(
            [
                str(pg_bin / "pg_dump.exe"),
                "-h",
                "127.0.0.1",
                "-p",
                "5434",
                "-U",
                "horilla_user",
                "-d",
                "horilla_db",
                "-w",
                "-Fc",
                "-f",
                str(archive),
            ],
            env=dump_env,
            check=True,
            creationflags=HIDDEN,
        )
        restore_env = {**os.environ, "PGPASSWORD": app_password}
        subprocess.run(
            [
                str(pg_bin / "pg_restore.exe"),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-U",
                "kenadhr_user",
                "-d",
                "kenadhr_db",
                "-w",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "--single-transaction",
                str(archive),
            ],
            env=restore_env,
            check=True,
            creationflags=HIDDEN,
        )
        with psycopg2.connect(
            host="127.0.0.1",
            port=port,
            dbname="kenadhr_db",
            user="kenadhr_user",
            password=app_password,
        ) as target:
            after = snapshot(target)
        if before != after:
            raise RuntimeError(
                "Restored table/sequence verification failed. Original data is unchanged."
            )
        # Confirm there were no out-of-app SQL writes while the backup was made.
        with psycopg2.connect(**source_kwargs) as source:
            if snapshot(source) != before:
                raise RuntimeError(
                    "Source data changed during migration; refusing cutover."
                )
        copy_media(backup / "media", ROOT / "media")
        key_path = backup / "media" / ".generated_secret_key"
        if not key_path.is_file():
            raise RuntimeError(
                "Persisted signing key missing. Refusing to invalidate credentials silently."
            )
        config["environment"]["SECRET_KEY"] = key_path.read_text().strip()
        write_pgadmin_access(config)
        # Password-free pgAdmin registration. Database credentials stay in the
        # private runtime config; pgAdmin asks the owner for the password.
        write_json(
            NATIVE_DIR / "pgadmin-servers.json",
            {
                "Servers": {
                    "1": {
                        "Name": "KenadHr Native (Windows)",
                        "Group": "Servers",
                        "Host": "127.0.0.1",
                        "Port": port,
                        "MaintenanceDB": "kenadhr_db",
                        "Username": "kenadhr_user",
                        "DBRestriction": "kenadhr_db",
                        "ConnectionParameters": {
                            "sslmode": "prefer",
                            "connect_timeout": 10,
                        },
                        "Comment": "Primary local KenadHr database. Native PostgreSQL; Docker is not required.",
                    }
                }
            },
        )
        # Write the completion marker last: a failed auxiliary file write must
        # not enable the native runner while the Docker fallback is restarted.
        config["migration_verified"] = True
        write_json(CONFIG, config)
        total_rows = sum(item["count"] for item in before["tables"].values())
        print(
            f"Verified {len(before['tables'])} tables, {total_rows} rows, {len(before['sequences'])} sequences."
        )
        print(
            f"Verified {len(media_manifest(backup / 'media'))} media files. Backup: {backup}"
        )
        print(
            "Migration verified. Docker writers remain stopped; run native checks before starting the native app."
        )
    except Exception:
        print(
            "Migration did not complete. Restarting the original Docker web/scheduler; backups retained.",
            flush=True,
        )
        subprocess.run(
            ["docker", "compose", "up", "-d", "web", "scheduler"], cwd=ROOT, check=False
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5435)
    args = parser.parse_args()
    migrate(args.pg_bin.resolve(), args.port)

"""Local Windows runner. No Docker is used by start/stop/status/manage.

Configuration and logs live outside Git in LOCALAPPDATA/KenadHr/native.
This is a localhost development setup, not an internet-facing deployment.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
NATIVE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "KenadHr" / "native"
CONFIG = NATIVE_DIR / "config.json"
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def web_port():
    """Return the localhost port used by the native web service."""
    value = os.environ.get("KENADHR_WEB_PORT", "8001")
    try:
        port = int(value)
    except ValueError as exc:
        raise RuntimeError("KENADHR_WEB_PORT must be a valid TCP port.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("KENADHR_WEB_PORT must be between 1 and 65535.")
    return port


def web_url(port=None):
    return f"http://localhost:{port or web_port()}"


def load_config(path=CONFIG):
    if not path.is_file():
        raise RuntimeError("Native setup is missing. See docs/windows-native.md.")
    config = json.loads(path.read_text(encoding="utf-8"))
    if Path(config["project"]).resolve() != ROOT:
        raise RuntimeError(
            "This configuration belongs to a different project checkout."
        )
    if config.get("migration_verified") is not True:
        raise RuntimeError(
            "Database/media migration has not been verified; refusing to start."
        )
    return config


def app_environment(config):
    env = os.environ.copy()
    env.update(config["environment"])
    env["PATH"] = str(config["pg_bin"]) + os.pathsep + env.get("PATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    port = web_port()
    if port != 8000:
        origins = {
            origin.strip()
            for origin in env.get("CSRF_TRUSTED_ORIGINS", "").split(",")
            if origin.strip()
        }
        origins.update({web_url(port), f"http://127.0.0.1:{port}"})
        env["CSRF_TRUSTED_ORIGINS"] = ",".join(sorted(origins))
        env["PASSWORD_RESET_BASE_URL"] = web_url(port)
    return env


def port_busy(port):
    with socket.socket() as client:
        client.settimeout(1)
        return client.connect_ex(("127.0.0.1", port)) == 0


def postgres(config, action):
    command = [str(Path(config["pg_bin"]) / "pg_ctl.exe"), "-D", config["pg_data"]]
    if action == "status":
        return (
            subprocess.run(
                command + ["status"], capture_output=True, creationflags=HIDDEN
            ).returncode
            == 0
        )
    if action == "start":
        if postgres(config, "status"):
            return
        if port_busy(config["pg_port"]):
            raise RuntimeError("Native PostgreSQL port is occupied by another process.")
        command += [
            "-l",
            str(NATIVE_DIR / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {config['pg_port']}",
            "-w",
            "-t",
            "30",
            "start",
        ]
    elif action == "stop":
        if not postgres(config, "status"):
            return
        command += ["-w", "-t", "30", "-m", "fast", "stop"]
    else:
        raise ValueError(action)
    subprocess.run(command, check=True, creationflags=HIDDEN)


@contextlib.contextmanager
def runner_lock(directory=NATIVE_DIR):
    """OS-released lock prevents duplicate web servers and schedulers, even after a crash."""
    import msvcrt

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "runner.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("The native runner is already running.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def running():
    try:
        with runner_lock():
            return False
    except RuntimeError:
        return True


def ready():
    try:
        with urlopen(f"http://127.0.0.1:{web_port()}/ready/", timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def manage(config, arguments):
    return subprocess.call(
        [sys.executable, str(ROOT / "manage.py"), *arguments],
        cwd=ROOT,
        env=app_environment(config),
    )


def stop_child(child):
    if child.poll() is not None:
        return
    # Windows venv python.exe is a launcher with a real Python child. Killing
    # only the launcher can orphan the web server/scheduler. Target the tree
    # of the live Popen handle we own, never a PID reloaded from a file.
    result = subprocess.run(
        ["taskkill.exe", "/PID", str(child.pid), "/T", "/F"],
        capture_output=True,
        creationflags=HIDDEN,
    )
    if result.returncode and child.poll() is None:
        raise RuntimeError("An owned native service could not be stopped.")
    child.wait(timeout=15)


def serve(config):
    """Supervise exactly two children; never terminate processes from saved PID files."""
    with runner_lock():
        stop_file = NATIVE_DIR / "stop.request"
        stop_file.unlink(missing_ok=True)
        port = web_port()
        if port_busy(port):
            raise RuntimeError(
                f"Port {port} is occupied. Stop the other app instance first."
            )
        postgres(config, "start")
        children = []
        with contextlib.ExitStack() as stack:
            try:
                for name, arguments in (
                    ("web", ["runserver", f"127.0.0.1:{port}", "--noreload"]),
                    ("scheduler", ["run_scheduler"]),
                ):
                    output = stack.enter_context(
                        (NATIVE_DIR / f"{name}.log").open("ab")
                    )
                    child = subprocess.Popen(
                        [sys.executable, str(ROOT / "manage.py"), *arguments],
                        cwd=ROOT,
                        env=app_environment(config),
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        creationflags=HIDDEN,
                    )
                    children.append(child)
                while not stop_file.exists():
                    if any(child.poll() is not None for child in children):
                        raise RuntimeError(
                            "A native service exited. Check web.log and scheduler.log."
                        )
                    time.sleep(0.5)
            finally:
                # Only children created by this supervisor are stopped. Windows
                # closes their DB connections and rolls back unfinished transactions.
                failures = []
                for child in reversed(children):
                    try:
                        stop_child(child)
                    except (RuntimeError, subprocess.SubprocessError) as error:
                        failures.append(error)
                stop_file.unlink(missing_ok=True)
                if failures:
                    raise RuntimeError(
                        "Could not stop every native service; check the runner log."
                    ) from failures[0]


def start(config):
    if running():
        if not ready():
            raise RuntimeError(
                "Native runner is active but not ready. Inspect the native logs."
            )
        print(f"KenadHr is already running: {web_url()}")
        return
    port = web_port()
    if port_busy(port):
        raise RuntimeError(f"Port {port} is occupied. Stop the other app instance first.")
    with (NATIVE_DIR / "runner.log").open("ab") as output:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "serve"],
            cwd=ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=HIDDEN,
        )
    deadline = time.monotonic() + 55
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Native startup failed. See {NATIVE_DIR / 'runner.log'}"
            )
        if running() and ready():
            print(f"KenadHr is running without Docker: {web_url()}")
            return
        time.sleep(1)
    raise RuntimeError(f"Startup is still pending. Check logs in {NATIVE_DIR}.")


def stop_runner():
    if running():
        (NATIVE_DIR / "stop.request").touch()
        deadline = time.monotonic() + 40
        while running() and time.monotonic() < deadline:
            time.sleep(0.5)
        if running():
            raise RuntimeError(
                "Native runner has not stopped; database left running for safety."
            )
    if port_busy(web_port()):
        raise RuntimeError(
            f"Port {web_port()} is still in use; database left running for safety."
        )


def stop(config):
    stop_runner()
    postgres(config, "stop")
    print("KenadHr stopped. Database and uploaded files are preserved.")


def restart(config):
    # Leave PostgreSQL running so maintenance/test connections are unaffected.
    stop_runner()
    start(config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["start", "stop", "restart", "status", "manage", "serve"]
    )
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This runner is for Windows only.")
    config = load_config()
    if args.action == "manage":
        if not args.arguments:
            parser.error("Specify a Django management command after manage.")
        postgres(config, "start")
        return manage(config, args.arguments)
    if args.action == "status":
        print(f"Native runner: {'running' if running() else 'stopped'}")
        print(
            f"Native PostgreSQL: {'running' if postgres(config, 'status') else 'stopped'}"
        )
        print(f"App ready: {running() and ready()}")
        print(f"Logs: {NATIVE_DIR}")
        return 0
    {"start": start, "stop": stop, "restart": restart, "serve": serve}[args.action](
        config
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)

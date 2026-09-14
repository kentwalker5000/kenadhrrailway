"""Safety checks for the native runner and data-copy helpers (no live database)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native
from migrate_to_native import copy_media, media_manifest


class NativeConfigurationTests(unittest.TestCase):
    def config(self):
        return {
            "project": str(native.ROOT),
            "migration_verified": True,
            "pg_bin": "C:/KenadHr/PostgreSQL/bin",
            "pg_data": "C:/KenadHr/data",
            "pg_port": 5435,
            "environment": {
                "DATABASE_URL": "postgres://local-test-only",
                "REDIS_URL": "",
            },
        }

    @patch.object(native.subprocess, "run")
    def test_stop_targets_only_the_live_owned_child_tree(self, run):
        run.return_value.returncode = 0
        child = Mock(pid=12345)
        child.poll.return_value = None
        native.stop_child(child)
        self.assertEqual(
            run.call_args.args[0],
            ["taskkill.exe", "/PID", "12345", "/T", "/F"],
        )
        child.wait.assert_called_once_with(timeout=15)

    @patch.object(native.subprocess, "run")
    def test_stop_does_not_target_exited_child_or_recycled_pid(self, run):
        child = Mock(pid=12345)
        child.poll.return_value = 0
        native.stop_child(child)
        run.assert_not_called()

    def test_refuses_missing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "setup is missing"):
                native.load_config(Path(directory) / "absent.json")

    def test_refuses_unverified_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = self.config()
            config["migration_verified"] = False
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(RuntimeError, "not been verified"):
                native.load_config(path)

    def test_refuses_configuration_for_another_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = self.config()
            config["project"] = directory
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(RuntimeError, "different project"):
                native.load_config(path)

    def test_verified_configuration_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(self.config()))
            self.assertEqual(native.load_config(path), self.config())

    def test_native_environment_overrides_docker_settings_without_mutating_parent(self):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgres://docker", "REDIS_URL": "redis://docker"},
        ):
            environment = native.app_environment(self.config())
            self.assertEqual(environment["DATABASE_URL"], "postgres://local-test-only")
            self.assertEqual(environment["REDIS_URL"], "")
            self.assertTrue(
                environment["PATH"].startswith(self.config()["pg_bin"] + os.pathsep)
            )
            self.assertEqual(os.environ["DATABASE_URL"], "postgres://docker")

    @patch.object(native.subprocess, "call", return_value=0)
    def test_management_commands_use_native_environment_without_cli_password(
        self, call
    ):
        native.manage(self.config(), ["check"])
        command = call.call_args.args[0]
        self.assertEqual(command[-1], "check")
        self.assertNotIn("postgres://local-test-only", command)
        self.assertEqual(
            call.call_args.kwargs["env"]["DATABASE_URL"], "postgres://local-test-only"
        )

    @patch.object(native, "port_busy", return_value=True)
    @patch.object(
        native.subprocess, "run", return_value=subprocess.CompletedProcess([], 3)
    )
    def test_postgres_does_not_take_over_another_listening_port(self, run, port_busy):
        with self.assertRaisesRegex(RuntimeError, "occupied"):
            native.postgres(self.config(), "start")
        self.assertEqual(run.call_count, 1)

    @patch.object(native, "port_busy", return_value=True)
    @patch.object(native, "running", return_value=False)
    @patch.object(native.subprocess, "Popen")
    def test_start_does_not_replace_other_web_server(self, popen, running, port_busy):
        with self.assertRaisesRegex(RuntimeError, "occupied"):
            native.start(self.config())
        popen.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows byte-range locking")
    def test_only_one_runner_can_hold_lock_and_lock_is_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            with native.runner_lock(Path(directory)):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with native.runner_lock(Path(directory)):
                        self.fail("Duplicate runner acquired the lock")
            with native.runner_lock(Path(directory)):
                pass


class NativeMediaCopyTests(unittest.TestCase):
    def test_copy_preserves_bytes_including_hidden_key_and_existing_unrelated_files(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            source.mkdir()
            target.mkdir()
            (source / ".generated_secret_key").write_bytes(b"synthetic-test-key")
            (source / "photo.png").write_bytes(b"\x00\x01\xff")
            (target / ".gitkeep").touch()
            copy_media(source, target)
            for name, digest in media_manifest(source).items():
                self.assertEqual(media_manifest(target)[name], digest)
            self.assertTrue((target / ".gitkeep").is_file())

    def test_collision_is_detected_before_any_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            source.mkdir()
            target.mkdir()
            (source / "a-new.txt").write_text("new")
            (source / "z-existing.txt").write_text("source")
            (target / "z-existing.txt").write_text("user data")
            with self.assertRaisesRegex(RuntimeError, "differs"):
                copy_media(source, target)
            self.assertEqual((target / "z-existing.txt").read_text(), "user data")
            self.assertFalse((target / "a-new.txt").exists())


if __name__ == "__main__":
    unittest.main()

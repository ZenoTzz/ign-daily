from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from snapshot_runtime_to_github import clone_with_retries, copy_runtime_snapshot, snapshot


class RuntimeSnapshotTest(unittest.TestCase):
    def test_only_whitelisted_runtime_content_is_copied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            (source / "2026-07-14" / "translations").mkdir(parents=True)
            (source / "2026-07-14" / "translations" / "01.json").write_text("{}", encoding="utf-8")
            (source / "learning").mkdir()
            (source / "learning" / "active-rules.json").write_text("{}", encoding="utf-8")
            (source / "dict.json").write_text("{}", encoding="utf-8")
            (source / "automation-config.json").write_text("{}", encoding="utf-8")
            (source / "google-polish-config.json").write_text("{}", encoding="utf-8")

            copied = copy_runtime_snapshot(source, destination)

            self.assertIn("2026-07-14/", copied)
            self.assertTrue((destination / "2026-07-14" / "translations" / "01.json").exists())
            self.assertFalse((destination / "learning" / "active-rules.json").exists())
            self.assertTrue((destination / "dict.json").exists())
            self.assertFalse((destination / "automation-config.json").exists())
            self.assertFalse((destination / "google-polish-config.json").exists())

    def test_clone_retries_transient_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "checkout"
            results = [
                type("Result", (), {"returncode": 128})(),
                type("Result", (), {"returncode": 0})(),
            ]
            with patch("snapshot_runtime_to_github.run", side_effect=results) as runner, patch("snapshot_runtime_to_github.time.sleep"):
                clone_with_retries("https://example.invalid/repo.git", "main", checkout)
            self.assertEqual(runner.call_count, 2)

    def test_push_retry_uses_a_fresh_clone_without_pull_rebase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            (app_dir / "data").mkdir(parents=True)
            (app_dir / "data" / "dict.json").write_text("{}", encoding="utf-8")
            env_path = root / ".env"
            env_path.write_text("GITHUB_PAT_IGN_DAILY=test-token\n", encoding="utf-8")
            push_attempts = 0
            commands: list[list[str]] = []

            def fake_run(command, **kwargs):
                nonlocal push_attempts
                commands.append(command)
                returncode = 0
                if "push" in command:
                    push_attempts += 1
                    returncode = 1 if push_attempts == 1 else 0
                return type("Result", (), {"returncode": returncode})()

            changed = type("Result", (), {"returncode": 1})()
            with (
                patch("snapshot_runtime_to_github.env_paths", return_value=[env_path]),
                patch("snapshot_runtime_to_github.git_auth_env", return_value={}),
                patch("snapshot_runtime_to_github.clone_with_retries") as clone,
                patch("snapshot_runtime_to_github.run", side_effect=fake_run),
                patch("snapshot_runtime_to_github.subprocess.run", return_value=changed),
                patch("snapshot_runtime_to_github.time.sleep"),
            ):
                self.assertTrue(snapshot(app_dir))

            self.assertEqual(clone.call_count, 2)
            self.assertEqual(push_attempts, 2)
            self.assertFalse(any("pull" in command for command in commands))
            push_commands = [command for command in commands if "push" in command]
            self.assertTrue(all("HEAD:main" in command for command in push_commands))


if __name__ == "__main__":
    unittest.main()

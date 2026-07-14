from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from snapshot_runtime_to_github import clone_with_retries, copy_runtime_snapshot


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


if __name__ == "__main__":
    unittest.main()

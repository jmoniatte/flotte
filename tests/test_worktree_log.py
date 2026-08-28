import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flotte.services.worktree_log import WorktreeLogStore


class WorktreeLogStoreTests(unittest.TestCase):
    def test_record_and_remove_use_one_directory_per_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("flotte.services.worktree_log.LOG_DIR", Path(directory)):
                store = WorktreeLogStore("ridewithgps")
                store.record(
                    "feature/login", "Cloned volume\n  mysql", 1.2, True
                )
                log_path = store.path_for("feature/login")

                self.assertEqual(
                    log_path,
                    Path(directory) / "ridewithgps" / "feature-login" / "flotte.csv",
                )
                self.assertTrue(log_path.is_file())
                with log_path.open(newline="") as log_file:
                    entries = list(csv.DictReader(log_file))
                self.assertRegex(
                    entries[0]["timestamp"],
                    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                )
                self.assertEqual(entries[0]["action"], "Cloned volume mysql")
                self.assertEqual(entries[0]["status"], "success")
                self.assertEqual(entries[0]["duration_seconds"], "1.200000")
                linked_path = store.linked_path_for("feature/login", "frontend")
                linked_path.write_text("server output\n")

                store.remove("feature/login")
                self.assertFalse(log_path.parent.exists())

    def test_linked_log_paths_share_the_worktree_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WorktreeLogStore("Ride With GPS", Path(directory))

            linked_path = store.linked_path_for("feature/login", "Acme Web")
            linked_path.parent.mkdir(parents=True)
            linked_path.write_text("server output\n")

            self.assertEqual(
                linked_path,
                Path(directory) / "ride-with-gps" / "feature-login" / "acme-web.log",
            )
            store.remove_linked("feature/login", "Acme Web")
            self.assertFalse(linked_path.exists())

    def test_log_write_errors_do_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory) / "logs"
            log_dir.write_text("not a directory")
            with patch("flotte.services.worktree_log.LOG_DIR", log_dir):
                store = WorktreeLogStore("ridewithgps")
                with self.assertLogs("flotte.services.worktree_log", level="WARNING"):
                    store.record("feature", "Created worktree", 1.2, True)
                    store.remove("feature")

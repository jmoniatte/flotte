import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flotte.services.worktree_log import WorktreeLogStore


class WorktreeLogStoreTests(unittest.TestCase):
    def test_record_and_remove_use_one_file_per_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("flotte.services.worktree_log.LOG_DIR", Path(directory)):
                store = WorktreeLogStore("ridewithgps")
                store.record("feature/login", "Clone volume mysql", 1.2, True)
                log_path = store.path_for("feature/login")

                self.assertEqual(log_path.name, "ridewithgps-feature-login.csv")
                self.assertTrue(log_path.is_file())
                with log_path.open(newline="") as log_file:
                    entries = list(csv.DictReader(log_file))
                self.assertEqual(entries[0]["action"], "Clone volume mysql")
                self.assertEqual(entries[0]["status"], "success")
                self.assertEqual(entries[0]["duration_seconds"], "1.200000")

                store.remove("feature/login")
                self.assertFalse(log_path.exists())

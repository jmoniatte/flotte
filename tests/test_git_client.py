import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from flotte.services.git_client import GitClient


class GitClientTests(unittest.TestCase):
    def test_run_scopes_commands_to_the_repository(self) -> None:
        completed = subprocess.CompletedProcess([], 0, b"output", b"")
        with patch("flotte.services._process.subprocess.run", return_value=completed) as run:
            result = GitClient(Path("/tmp/repository")).run("worktree", "list")

        self.assertEqual(result, (0, "output", ""))
        run.assert_called_once_with(
            ("git", "-C", "/tmp/repository", "worktree", "list"),
            cwd=None,
            capture_output=True,
            env={**os.environ, "LC_ALL": "C"},
            timeout=60.0,
            check=False,
        )

    def test_branch_lookup_and_forced_worktree_removal_use_git_commands(self) -> None:
        client = GitClient(Path("/tmp/repository"))
        with patch.object(client, "run", return_value=(0, "", "")) as run:
            self.assertTrue(client.branch_exists("feature/test"))
            self.assertEqual(client.local_branches(), [])
            self.assertEqual(
                client.remove_worktree(Path("/tmp/worktree"), force=True),
                (0, "", ""),
            )

        self.assertEqual(
            [call.args for call in run.call_args_list],
            [
                ("show-ref", "--verify", "--quiet", "refs/heads/feature/test"),
                ("branch", "--format=%(refname:short)"),
                ("worktree", "remove", "--force", "/tmp/worktree"),
            ],
        )

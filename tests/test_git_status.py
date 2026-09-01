import unittest
from pathlib import Path
from unittest.mock import patch

from flotte.models import GitStatus
from flotte.services.git_status import (
    get_git_status_strict_sync,
    get_git_status_sync,
    parse_porcelain,
)


class GitStatusTests(unittest.TestCase):
    def test_parse_porcelain_counts_every_changed_state(self) -> None:
        output = "\n".join(
            (
                "M  staged.py",
                " M modified.py",
                " D deleted.py",
                "R  renamed.py -> moved.py",
                " T type-changed.py",
                "UU conflicted.py",
                "?? untracked.py",
                "!! ignored.py",
            )
        )

        self.assertEqual(
            parse_porcelain(output),
            GitStatus(staged=3, unstaged=4, untracked=1),
        )

    def test_has_changes_ignores_upstream_divergence(self) -> None:
        clean = GitStatus(ahead=2, behind=1)
        changed = GitStatus(unstaged=1, ahead=2)

        self.assertFalse(clean.has_changes)
        self.assertTrue(changed.has_changes)

    def test_status_reads_changes_and_upstream_divergence_through_git_client(self) -> None:
        with patch(
            "flotte.services.git_status.GitClient.run",
            side_effect=((0, " M changed.py\n", ""), (0, "2 3\n", "")),
        ) as run:
            status = get_git_status_sync(Path("/tmp/worktree"))

        self.assertEqual(status, GitStatus(unstaged=1, ahead=3, behind=2))
        self.assertEqual(
            [item.args for item in run.call_args_list],
            [
                ("status", "--porcelain"),
                ("rev-list", "--left-right", "--count", "@{upstream}...HEAD"),
            ],
        )

    def test_strict_status_rejects_a_failed_worktree_inspection(self) -> None:
        with patch(
            "flotte.services.git_status.GitClient.run",
            return_value=(-1, "", "git unavailable"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Could not inspect /tmp/worktree: git unavailable",
            ):
                get_git_status_strict_sync(Path("/tmp/worktree"))

        with patch(
            "flotte.services.git_status.GitClient.run",
            return_value=(-1, "", "git unavailable"),
        ):
            self.assertEqual(
                get_git_status_sync(Path("/tmp/worktree")),
                GitStatus(),
            )

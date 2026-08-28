import unittest
from pathlib import Path

from flotte.models import LinkedWorktree, Worktree
from flotte.widgets.linked_repositories import available_actions


class LinkedRepositoryActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worktree = Worktree("feature", Path("/tmp/feature"), "feature")

    def test_available_actions_follow_link_and_process_state(self) -> None:
        cases = (
            (LinkedWorktree("Frontend"), {"link"}),
            (
                LinkedWorktree("Frontend", path=Path("/tmp/frontend"), can_start=True, process_status="stopped"),
                {"start", "unlink"},
            ),
            (
                LinkedWorktree("Frontend", path=Path("/tmp/frontend"), can_start=True, process_status="running"),
                {"stop", "restart", "unlink"},
            ),
            (
                LinkedWorktree(
                    "Frontend",
                    path=Path("/tmp/frontend"),
                    can_start=True,
                    process_status="running",
                    log_path=Path("/tmp/frontend.log"),
                ),
                {"stop", "restart", "logs", "unlink"},
            ),
            (
                LinkedWorktree("Frontend", path=Path("/tmp/frontend"), can_start=True, process_status="external"),
                {"unlink"},
            ),
        )

        for linked, expected in cases:
            with self.subTest(linked=linked):
                self.assertEqual(available_actions(linked, self.worktree), expected)

    def test_main_worktree_never_exposes_link_or_unlink(self) -> None:
        main = Worktree("main", Path("/tmp/main"), "main", is_main=True)
        linked = LinkedWorktree("Frontend", path=Path("/tmp/frontend"), can_start=True, process_status="stopped")

        self.assertEqual(available_actions(linked, main), {"start"})

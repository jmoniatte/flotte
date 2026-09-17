import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from flotte.models import Worktree
from flotte.services.git_client import GitClient
from flotte.services.worktree_manager import WorktreeManager


class WorktreeManagerTests(unittest.TestCase):
    def test_remove_delegates_to_git_and_prunes_empty_workspace_directories(self) -> None:
        git = Mock(spec=GitClient)
        git.remove_worktree.return_value = (0, "", "")
        manager = WorktreeManager(
            Path("/tmp/main"),
            "/tmp/workspaces/{worktree}/project",
            git=git,
        )
        worktree = Worktree("feature", Path("/tmp/workspaces/feature/project"))
        manager.prune_empty_worktree_parents = Mock()

        self.assertTrue(manager.remove_worktree_sync(worktree))

        git.remove_worktree.assert_called_once_with(worktree.path, force=True)
        manager.prune_empty_worktree_parents.assert_called_once_with(worktree.path)

    def test_remove_remains_deletes_leftovers_and_prunes_git(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspaces = Path(root) / "workspaces"
            git = Mock(spec=GitClient)
            git.prune_worktrees.return_value = (0, "", "")
            manager = WorktreeManager(
                Path(root) / "main",
                f"{workspaces}/{{worktree}}/project",
                git=git,
            )
            worktree = Worktree("feature", workspaces / "feature" / "project")
            (worktree.path / "files").mkdir(parents=True)
            (worktree.path / "files" / "left.txt").write_text("x")
            (worktree.path.parent / "AGENTS.md").symlink_to(Path(root) / "missing.md")

            self.assertTrue(manager.remove_worktree_remains_sync(worktree))

            git.prune_worktrees.assert_called_once_with()
            self.assertFalse(worktree.path.parent.exists())
            self.assertTrue(workspaces.exists())

    def test_create_refuses_a_name_another_branch_already_uses(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspaces = Path(root) / "workspaces"
            existing = workspaces / "feature-login" / "project"
            existing.mkdir(parents=True)
            leftover = workspaces / "feature-signup" / "project"
            leftover.mkdir(parents=True)
            git = Mock(spec=GitClient)
            git.run.return_value = (0, f"{existing}  abc1234 [feature-login]\n", "")
            manager = WorktreeManager(
                Path(root) / "main",
                f"{workspaces}/{{worktree}}/project",
                git=git,
            )

            with self.assertRaisesRegex(RuntimeError, "from branch feature-login"):
                manager.create_worktree_sync("feature/login", "main")
            with self.assertRaisesRegex(RuntimeError, "already has the worktree"):
                manager.create_worktree_sync("feature-login", None)
            with self.assertRaisesRegex(RuntimeError, "is not a worktree"):
                manager.create_worktree_sync("feature/signup", "main")
            git.run.assert_called_with("worktree", "list")

            git.run.side_effect = [(0, "", ""), (0, "", "")]
            created = manager.create_worktree_sync("feature/logout", "main")
            self.assertEqual(created.name, "feature-logout")
            self.assertEqual(created.branch, "feature/logout")

    def test_prune_parents_keeps_directories_holding_real_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspaces = Path(root) / "workspaces"
            manager = WorktreeManager(
                Path(root) / "main",
                f"{workspaces}/{{worktree}}/project",
                git=Mock(spec=GitClient),
            )
            parent = workspaces / "feature"
            parent.mkdir(parents=True)
            (parent / "AGENTS.md").symlink_to(Path(root) / "missing.md")
            (parent / "notes.txt").write_text("keep")

            manager.prune_empty_worktree_parents(parent / "project")

            self.assertTrue((parent / "notes.txt").exists())
            self.assertTrue((parent / "AGENTS.md").is_symlink())

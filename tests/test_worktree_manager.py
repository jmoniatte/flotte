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

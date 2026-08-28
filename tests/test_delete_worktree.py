import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from flotte.models import Worktree
from flotte.screens.delete_worktree import DeleteWorktreeScreen
from flotte.services import LinkedRepositoryController, WorktreeManager


class DeleteWorktreeScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_removes_linked_repositories_through_controller(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        worktree_manager = Mock(spec=WorktreeManager)
        linked_controller = Mock(spec=LinkedRepositoryController)
        linked_controller.remove_all = AsyncMock()
        screen = DeleteWorktreeScreen(
            worktree,
            worktree_manager,
            linked_controller,
        )
        screen._update_status = Mock()
        screen.dismiss = Mock()

        await screen._do_delete()

        worktree_manager.cleanup_docker_sync.assert_called_once_with(worktree)
        linked_controller.remove_all.assert_awaited_once_with(worktree)
        worktree_manager.remove_worktree_sync.assert_called_once_with(worktree)
        result = screen.dismiss.call_args.args[0]
        self.assertTrue(result.success)
        self.assertEqual(result.worktree_name, "feature")

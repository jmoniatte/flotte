import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from flotte.models import GitStatus, Worktree
from flotte.screens.delete_worktree import DeleteStage, DeleteWorktreeScreen
from flotte.services import WorkspaceManager, WorktreeDeletionInspection


class DeleteWorktreeScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_clean_worktree_advances_to_delete_confirmation(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        workspace_manager = Mock(spec=WorkspaceManager)
        workspace_manager.inspect_deletion = AsyncMock(
            return_value=WorktreeDeletionInspection(GitStatus())
        )
        screen = DeleteWorktreeScreen(worktree, workspace_manager)
        screen._show_delete_confirmation = Mock()

        await screen._inspect_worktree()

        screen._show_delete_confirmation.assert_called_once_with()

    async def test_changed_worktree_offers_commit_or_delete_without_it(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        workspace_manager = Mock(spec=WorkspaceManager)
        workspace_manager.inspect_deletion = AsyncMock(
            return_value=WorktreeDeletionInspection(
                GitStatus(staged=1, unstaged=2, untracked=3)
            )
        )
        screen = DeleteWorktreeScreen(worktree, workspace_manager)
        screen._show_prompt = Mock()

        await screen._inspect_worktree()

        screen._show_prompt.assert_called_once_with(
            "1 staged, 2 unstaged, 3 untracked in [bold]feature[/bold].",
            "Commit these changes before deleting the worktree?",
            actions=("cancel", "discard", "commit"),
        )

    async def test_changed_linked_repository_blocks_deletion(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        workspace_manager = Mock(spec=WorkspaceManager)
        workspace_manager.inspect_deletion = AsyncMock(
            return_value=WorktreeDeletionInspection(
                GitStatus(),
                ("frontend",),
            )
        )
        screen = DeleteWorktreeScreen(worktree, workspace_manager)
        screen.notify = Mock()
        screen.dismiss = Mock()

        await screen._inspect_worktree()

        screen.notify.assert_called_once_with(
            "Clean linked worktrees before deleting: frontend",
            severity="warning",
        )
        screen.dismiss.assert_called_once_with(None)

    async def test_commit_advances_to_delete_confirmation(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        workspace_manager = Mock(spec=WorkspaceManager)
        workspace_manager.commit = AsyncMock()
        screen = DeleteWorktreeScreen(worktree, workspace_manager)
        screen._show_delete_confirmation = Mock()

        await screen._commit_changes()

        workspace_manager.commit.assert_awaited_once_with(
            worktree,
            "Commit before worktree delete",
        )
        screen._show_delete_confirmation.assert_called_once_with()

    async def test_final_recheck_returns_to_changes_when_worktree_became_dirty(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        workspace_manager = Mock(spec=WorkspaceManager)
        workspace_manager.inspect_deletion = AsyncMock(
            return_value=WorktreeDeletionInspection(GitStatus(unstaged=1))
        )
        screen = DeleteWorktreeScreen(worktree, workspace_manager)
        screen._show_changes_prompt = Mock()
        screen._do_delete = AsyncMock()

        await screen._revalidate_and_delete()

        screen._show_changes_prompt.assert_called_once_with(["1 unstaged"])
        screen._do_delete.assert_not_awaited()

    async def test_final_recheck_honors_explicit_delete_without_commit(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        workspace_manager = Mock(spec=WorkspaceManager)
        workspace_manager.inspect_deletion = AsyncMock(
            return_value=WorktreeDeletionInspection(GitStatus(untracked=1))
        )
        screen = DeleteWorktreeScreen(worktree, workspace_manager)
        screen._allow_dirty_delete = True
        screen._show_status = Mock()
        screen._do_delete = AsyncMock()

        await screen._revalidate_and_delete()

        self.assertEqual(screen._stage, DeleteStage.DELETING)
        screen._show_status.assert_called_once_with("Deleting...")
        screen._do_delete.assert_awaited_once_with()

    async def test_delete_removes_linked_repositories_through_controller(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        workspace_manager = Mock(spec=WorkspaceManager)
        workspace_manager.delete = AsyncMock()
        screen = DeleteWorktreeScreen(
            worktree,
            workspace_manager,
        )
        screen._update_status = Mock()
        screen.dismiss = Mock()

        await screen._do_delete()

        workspace_manager.delete.assert_awaited_once_with(
            worktree,
            on_progress=screen._update_status,
        )
        result = screen.dismiss.call_args.args[0]
        self.assertTrue(result.success)
        self.assertEqual(result.worktree_name, "feature")

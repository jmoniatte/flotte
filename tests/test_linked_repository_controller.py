import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call

from flotte.models import GitStatus, LinkedWorktree, Worktree
from flotte.services.linked_repository_controller import LinkedRepositoryController
from flotte.services.linked_worktree_manager import LinkedWorktreeManager
from flotte.services.worktree_log import WorktreeLogStore


class LinkedRepositoryControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = Mock(spec=LinkedWorktreeManager)
        self.log_store = Mock(spec=WorktreeLogStore)
        self.controller = LinkedRepositoryController(self.manager, self.log_store)
        self.worktree = Worktree("feature", Path("/tmp/feature"))

    async def test_link_normalizes_and_logs_manager_results(self) -> None:
        self.manager.create_link = AsyncMock(
            return_value=LinkedWorktree("rwgps-ui", state="linked")
        )

        success = await self.controller.link(self.worktree, "rwgps-ui")

        self.assertTrue(success.succeeded)
        self.assertEqual(success.message, "Linked rwgps-ui")
        log = self.log_store.record_elapsed.call_args.args
        self.assertEqual((log[0], log[1], log[3]), ("feature", "Linked rwgps-ui", True))

        self.log_store.reset_mock()
        self.manager.create_link.return_value = LinkedWorktree(
            "rwgps-ui",
            state="error",
            error="branch unavailable",
        )

        failure = await self.controller.link(self.worktree, "rwgps-ui")

        self.assertFalse(failure.succeeded)
        self.assertEqual(failure.message, "Link setup failed: branch unavailable")
        self.assertFalse(self.log_store.record_elapsed.call_args.args[3])

    async def test_lifecycle_logs_the_process_id_and_failures(self) -> None:
        self.manager.start_link = AsyncMock(return_value=Mock(pid=12345))
        self.manager.stop_link = AsyncMock(side_effect=RuntimeError("stop failed"))

        started = await self.controller.run_lifecycle(
            self.worktree, "rwgps-ui", "start"
        )

        self.assertTrue(started.succeeded)
        self.assertEqual(started.message, "Started rwgps-ui")
        log = self.log_store.record_elapsed.call_args.args
        self.assertEqual(log[1], "Started rwgps-ui (PID: 12345)")
        self.assertTrue(log[3])

        self.log_store.reset_mock()
        stopped = await self.controller.run_lifecycle(
            self.worktree, "rwgps-ui", "stop"
        )

        self.assertFalse(stopped.succeeded)
        self.assertEqual(stopped.message, "Failed to stop rwgps-ui: stop failed")
        log = self.log_store.record_elapsed.call_args.args
        self.assertEqual(log[1], "Stopped rwgps-ui")
        self.assertFalse(log[3])

    async def test_unlink_refreshes_links_and_reports_dirty_repositories(self) -> None:
        self.manager.remove_link = AsyncMock()
        self.manager.remove_links = AsyncMock()
        self.manager.linked_statuses = AsyncMock(
            return_value={
                "rwgps-ui": GitStatus(unstaged=1),
                "docs": GitStatus(),
            }
        )

        outcome = await self.controller.unlink(self.worktree, "rwgps-ui")
        await self.controller.remove_all(self.worktree)
        has_changes = await self.controller.has_changes(self.worktree, "rwgps-ui")
        changed = await self.controller.changed_repositories(self.worktree)

        self.assertTrue(outcome.succeeded)
        self.assertEqual(outcome.message, "Unlinked rwgps-ui")
        self.manager.attach.assert_called_once_with(self.worktree)
        self.manager.remove_links.assert_awaited_once_with(self.worktree)
        log = self.log_store.record_elapsed.call_args.args
        self.assertEqual((log[1], log[3]), ("Unlinked rwgps-ui", True))
        self.assertTrue(has_changes)
        self.assertEqual(changed, ["rwgps-ui"])
        self.assertEqual(
            self.manager.linked_statuses.await_args_list,
            [
                call(self.worktree, strict=False),
                call(self.worktree, strict=True),
            ],
        )

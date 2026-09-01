import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

from flotte.models import GitStatus, Worktree
from flotte.services.environment_manager import EnvironmentManager
from flotte.services.environment_manager import (
    EnvironmentOperationResult,
    START_ENVIRONMENT,
)
from flotte.services.linked_repository_controller import (
    LinkedOperationOutcome,
    LinkedRepositoryController,
)
from flotte.services.workspace_manager import WorkspaceManager
from flotte.services.worktree_log import WorktreeLogStore
from flotte.services.worktree_manager import WorktreeManager


class WorkspaceManagerTests(unittest.TestCase):
    def test_operations_lock_only_the_target_worktree(self) -> None:
        first = Worktree("first", Path("/tmp/first"))
        second = Worktree("second", Path("/tmp/second"))
        worktrees = Mock(spec=WorktreeManager)
        environment = Mock(spec=EnvironmentManager)
        environment.perform = AsyncMock(
            return_value=EnvironmentOperationResult(True)
        )
        manager = WorkspaceManager(
            worktrees,
            environment,
            Mock(spec=WorktreeLogStore),
        )

        async def exercise() -> None:
            first_task = manager.run_environment(first, START_ENVIRONMENT)
            second_task = manager.run_environment(second, START_ENVIRONMENT)

            self.assertIsNotNone(first_task)
            self.assertIsNotNone(second_task)
            self.assertIsNone(manager.run_environment(first, START_ENVIRONMENT))
            self.assertTrue(manager.has_active_operations())
            await asyncio.gather(first_task, second_task)
            self.assertFalse(manager.has_active_operations())

        asyncio.run(exercise())

    def test_linked_operations_share_the_workspace_lock(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        linked = Mock(spec=LinkedRepositoryController)
        linked.run_lifecycle = AsyncMock(
            return_value=LinkedOperationOutcome(True, "Started frontend")
        )
        manager = WorkspaceManager(
            Mock(spec=WorktreeManager),
            Mock(spec=EnvironmentManager),
            Mock(spec=WorktreeLogStore),
            linked,
        )

        async def exercise() -> None:
            task = manager.run_linked(worktree, "frontend", "start")

            self.assertIsNotNone(task)
            self.assertIsNone(manager.run_linked(worktree, "frontend", "stop"))
            result = await task
            self.assertEqual(result.message, "Started frontend")

        asyncio.run(exercise())
        linked.run_lifecycle.assert_awaited_once_with(
            worktree,
            "frontend",
            "start",
        )
        self.assertFalse(manager.is_busy(worktree.name))

    def test_linked_operation_requires_a_configured_controller(self) -> None:
        manager = WorkspaceManager(
            Mock(spec=WorktreeManager),
            Mock(spec=EnvironmentManager),
            Mock(spec=WorktreeLogStore),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Linked repositories are not configured",
        ):
            manager.run_linked(
                Worktree("feature", Path("/tmp/feature")),
                "frontend",
                "start",
            )

    def test_discover_attaches_environment_and_linked_repositories(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        worktrees = Mock(spec=WorktreeManager)
        worktrees.discover_worktrees = AsyncMock(return_value=[worktree])
        environment = Mock(spec=EnvironmentManager)
        linked = Mock(spec=LinkedRepositoryController)
        manager = WorkspaceManager(worktrees, environment, Mock(spec=WorktreeLogStore), linked)

        self.assertEqual(asyncio.run(manager.discover()), [worktree])

        environment.attach.assert_called_once_with(worktree)
        linked.attach.assert_called_once_with(worktree)

    def test_delete_sequences_environment_links_and_git_worktree(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        worktrees = Mock(spec=WorktreeManager)
        environment = Mock(spec=EnvironmentManager)
        environment.cleanup = AsyncMock()
        environment.make_worktree_removable = AsyncMock()
        linked = Mock(spec=LinkedRepositoryController)
        linked.remove_all = AsyncMock()
        manager = WorkspaceManager(worktrees, environment, Mock(spec=WorktreeLogStore), linked)
        progress = Mock()

        asyncio.run(manager.delete(worktree, progress))

        environment.cleanup.assert_awaited_once_with(worktree)
        environment.make_worktree_removable.assert_not_awaited()
        linked.remove_all.assert_awaited_once_with(worktree)
        worktrees.remove_worktree_sync.assert_called_once_with(worktree)
        self.assertEqual(
            progress.call_args_list,
            [
                call("Stopping containers..."),
                call("Removing linked worktrees..."),
                call("Removing worktree..."),
            ],
        )

    def test_inspect_deletion_collects_main_and_linked_changes(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        linked = Mock(spec=LinkedRepositoryController)
        linked.changed_repositories = AsyncMock(return_value=["frontend"])
        manager = WorkspaceManager(
            Mock(spec=WorktreeManager),
            Mock(spec=EnvironmentManager),
            Mock(spec=WorktreeLogStore),
            linked,
        )

        with patch(
            "flotte.services.workspace_manager.get_git_status_strict",
            new=AsyncMock(return_value=GitStatus(unstaged=2)),
        ):
            inspection = asyncio.run(manager.inspect_deletion(worktree))

        self.assertEqual(inspection.git_status, GitStatus(unstaged=2))
        self.assertEqual(inspection.changed_linked_repositories, ("frontend",))

    def test_delete_holds_workspace_lock(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        cleanup_started = asyncio.Event()
        allow_cleanup = asyncio.Event()

        async def cleanup(_worktree) -> None:
            cleanup_started.set()
            await allow_cleanup.wait()

        worktrees = Mock(spec=WorktreeManager)
        environment = Mock(spec=EnvironmentManager)
        environment.cleanup = cleanup
        manager = WorkspaceManager(
            worktrees,
            environment,
            Mock(spec=WorktreeLogStore),
        )

        async def exercise() -> None:
            task = asyncio.create_task(manager.delete(worktree))
            await cleanup_started.wait()
            self.assertTrue(manager.is_busy(worktree.name))
            with self.assertRaisesRegex(RuntimeError, "Operation in progress"):
                await manager.commit(worktree, "message")
            allow_cleanup.set()
            await task
            self.assertFalse(manager.is_busy(worktree.name))

        asyncio.run(exercise())

    def test_delete_repairs_permissions_only_after_git_reports_them(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        worktrees = Mock(spec=WorktreeManager)
        worktrees.remove_worktree_sync.side_effect = (
            RuntimeError("failed to delete: Permission denied"),
            True,
        )
        environment = Mock(spec=EnvironmentManager)
        environment.cleanup = AsyncMock()
        environment.make_worktree_removable = AsyncMock()
        manager = WorkspaceManager(
            worktrees,
            environment,
            Mock(spec=WorktreeLogStore),
        )
        progress = Mock()

        asyncio.run(manager.delete(worktree, progress))

        self.assertEqual(worktrees.remove_worktree_sync.call_count, 2)
        environment.make_worktree_removable.assert_awaited_once_with(worktree)
        self.assertIn(
            call("Repairing worktree permissions..."),
            progress.call_args_list,
        )

    def test_delete_does_not_repair_a_non_permission_git_failure(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        worktrees = Mock(spec=WorktreeManager)
        worktrees.remove_worktree_sync.side_effect = RuntimeError(
            "worktree is locked"
        )
        environment = Mock(spec=EnvironmentManager)
        environment.cleanup = AsyncMock()
        environment.make_worktree_removable = AsyncMock()
        manager = WorkspaceManager(
            worktrees,
            environment,
            Mock(spec=WorktreeLogStore),
        )

        with self.assertRaisesRegex(RuntimeError, "worktree is locked"):
            asyncio.run(manager.delete(worktree))

        environment.make_worktree_removable.assert_not_awaited()
        self.assertFalse(manager.is_busy(worktree.name))

    def test_status_callback_failure_releases_operation_lock(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        manager = WorkspaceManager(
            Mock(spec=WorktreeManager),
            Mock(spec=EnvironmentManager),
            Mock(spec=WorktreeLogStore),
        )

        with self.assertRaisesRegex(RuntimeError, "view unmounted"):
            manager.run_environment(
                worktree,
                START_ENVIRONMENT,
                Mock(side_effect=RuntimeError("view unmounted")),
            )

        self.assertFalse(manager.is_busy(worktree.name))

    def test_started_operation_finishes_when_caller_drops_the_task(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        environment = Mock(spec=EnvironmentManager)
        environment.perform = AsyncMock(
            return_value=EnvironmentOperationResult(True)
        )
        manager = WorkspaceManager(
            Mock(spec=WorktreeManager),
            environment,
            Mock(spec=WorktreeLogStore),
        )

        async def exercise() -> None:
            manager.run_environment(worktree, START_ENVIRONMENT)
            self.assertTrue(manager.is_busy(worktree.name))
            await asyncio.sleep(0)
            self.assertFalse(manager.is_busy(worktree.name))

        asyncio.run(exercise())

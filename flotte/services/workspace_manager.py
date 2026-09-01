"""Coordinate worktrees, runnable environments, and linked repositories."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from ..models import GitStatus, Worktree
from .environment_manager import (
    EnvironmentManager,
    EnvironmentOperation,
    EnvironmentOperationResult,
)
from .linked_repository_controller import (
    LinkedOperationOutcome,
    LinkedRepositoryController,
)
from .worktree_creator import (
    ProgressCallback,
    WorktreeCreationResult,
    WorktreeCreator,
)
from .worktree_log import WorktreeLogStore
from .worktree_manager import WorktreeManager
from .git_status import get_git_status_strict

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class WorktreeDeletionInspection:
    git_status: GitStatus
    changed_linked_repositories: tuple[str, ...] = ()


class WorkspaceManager:
    def __init__(
        self,
        worktrees: WorktreeManager,
        environment: EnvironmentManager,
        log_store: WorktreeLogStore,
        linked_repositories: LinkedRepositoryController | None = None,
    ) -> None:
        self.worktrees = worktrees
        self.environment = environment
        self.linked_repositories = linked_repositories
        self.creator = WorktreeCreator(worktrees, environment, log_store)
        self._operations: dict[str, str] = {}

    def is_busy(self, worktree_name: str | None) -> bool:
        return worktree_name is not None and worktree_name in self._operations

    def has_active_operations(self) -> bool:
        return bool(self._operations)

    def run_environment(
        self,
        worktree: Worktree,
        operation: EnvironmentOperation,
        on_status_changed: Callable[[], None] | None = None,
    ) -> asyncio.Task[EnvironmentOperationResult] | None:
        return self._start_operation(
            worktree,
            operation.name,
            lambda: self.environment.perform(
                worktree,
                operation,
                on_status_changed,
            ),
            on_status_changed,
        )

    def run_linked(
        self,
        worktree: Worktree,
        repository_name: str,
        action: str,
        on_status_changed: Callable[[], None] | None = None,
    ) -> asyncio.Task[LinkedOperationOutcome] | None:
        if self.linked_repositories is None:
            raise RuntimeError("Linked repositories are not configured")
        operation_name = "link" if action == "link" else f"{action}-linked"
        return self._start_operation(
            worktree,
            operation_name,
            lambda: self._run_linked(worktree, repository_name, action),
            on_status_changed,
        )

    async def _run_linked(
        self,
        worktree: Worktree,
        repository_name: str,
        action: str,
    ) -> LinkedOperationOutcome:
        assert self.linked_repositories is not None
        if action == "link":
            return await self.linked_repositories.link(worktree, repository_name)
        if action == "unlink":
            return await self.linked_repositories.unlink(worktree, repository_name)
        return await self.linked_repositories.run_lifecycle(
            worktree,
            repository_name,
            action,
        )

    def _start_operation(
        self,
        worktree: Worktree,
        operation_name: str,
        run: Callable[[], Awaitable[T]],
        on_status_changed: Callable[[], None] | None,
    ) -> asyncio.Task[T] | None:
        if self.is_busy(worktree.name):
            return None
        self._operations[worktree.name] = operation_name
        try:
            if on_status_changed:
                on_status_changed()
        except Exception:
            self._operations.pop(worktree.name, None)
            raise
        return asyncio.create_task(
            self._run_operation(worktree.name, run, on_status_changed)
        )

    async def _run_operation(
        self,
        worktree_name: str,
        run: Callable[[], Awaitable[T]],
        on_status_changed: Callable[[], None] | None,
    ) -> T:
        try:
            return await run()
        finally:
            self._operations.pop(worktree_name, None)
            if on_status_changed:
                on_status_changed()

    async def discover(self) -> list[Worktree]:
        worktrees = await self.worktrees.discover_worktrees()
        for worktree in worktrees:
            self.environment.attach(worktree)
            if self.linked_repositories:
                self.linked_repositories.attach(worktree)
        return worktrees

    async def branches(self) -> list[str]:
        return await self.worktrees.branches()

    async def create(
        self,
        branch_name: str,
        base_branch: str | None,
        *,
        clone_data: bool,
        on_progress: ProgressCallback | None = None,
    ) -> WorktreeCreationResult:
        return await self.creator.create(
            branch_name,
            base_branch,
            clone_data=clone_data,
            on_progress=on_progress,
        )

    async def delete(
        self,
        worktree: Worktree,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._claim_operation(worktree, "delete")
        try:
            self._report(on_progress, "Stopping containers...")
            await self.environment.cleanup(worktree)
            if self.linked_repositories:
                self._report(on_progress, "Removing linked worktrees...")
                await self.linked_repositories.remove_all(worktree)
            self._report(on_progress, "Removing worktree...")
            try:
                await asyncio.to_thread(
                    self.worktrees.remove_worktree_sync,
                    worktree,
                )
            except RuntimeError as error:
                if not self._is_permission_error(error):
                    raise
                self._report(on_progress, "Repairing worktree permissions...")
                await self.environment.make_worktree_removable(worktree)
                await asyncio.to_thread(
                    self.worktrees.remove_worktree_sync,
                    worktree,
                )
        finally:
            self._operations.pop(worktree.name, None)

    async def inspect_deletion(
        self, worktree: Worktree
    ) -> WorktreeDeletionInspection:
        if self.is_busy(worktree.name):
            raise RuntimeError("Operation in progress")
        git_status, changed_linked_repositories = await asyncio.gather(
            get_git_status_strict(worktree.path),
            self.linked_repositories.changed_repositories(worktree)
            if self.linked_repositories
            else self._no_changed_repositories(),
        )
        if self.is_busy(worktree.name):
            raise RuntimeError("Operation in progress")
        return WorktreeDeletionInspection(
            git_status,
            tuple(changed_linked_repositories),
        )

    async def commit(self, worktree: Worktree, message: str) -> None:
        self._claim_operation(worktree, "commit")
        try:
            await self.worktrees.commit_all_changes(worktree, message)
        finally:
            self._operations.pop(worktree.name, None)

    def _claim_operation(self, worktree: Worktree, operation_name: str) -> None:
        if self.is_busy(worktree.name):
            raise RuntimeError("Operation in progress")
        self._operations[worktree.name] = operation_name

    @staticmethod
    async def _no_changed_repositories() -> list[str]:
        return []

    @staticmethod
    def _is_permission_error(error: Exception) -> bool:
        message = str(error).lower()
        return "permission denied" in message or "operation not permitted" in message

    @staticmethod
    def _report(callback: ProgressCallback | None, message: str) -> None:
        if callback:
            callback(message)

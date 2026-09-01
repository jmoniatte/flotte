"""Orchestrate creation of a configured worktree environment."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from ..models import Worktree
from .environment_manager import EnvironmentManager
from .worktree_log import WorktreeLogStore
from .worktree_manager import WorktreeManager

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class WorktreeCreationResult:
    worktree: Worktree
    warnings: tuple[str, ...]


class WorktreeCreator:
    """Create a worktree and prepare its Docker-backed environment."""

    def __init__(
        self,
        manager: WorktreeManager,
        environment: EnvironmentManager,
        log_store: WorktreeLogStore,
    ) -> None:
        self.manager = manager
        self.environment = environment
        self.log_store = log_store

    async def create(
        self,
        branch_name: str,
        base_branch: str | None,
        *,
        clone_data: bool,
        on_progress: ProgressCallback | None = None,
    ) -> WorktreeCreationResult:
        self._report(on_progress, "Creating git worktree...")
        started_at = perf_counter()
        worktree = await self.manager.create_worktree(branch_name, base_branch)
        existing_worktrees = await self.manager.discover_worktrees()
        await asyncio.to_thread(
            self.environment.configure,
            worktree,
            existing_worktrees,
        )
        self.log_store.record_elapsed(
            worktree.name,
            "Created worktree",
            started_at,
            True,
        )

        warnings = await self.environment.provision(
            worktree,
            clone_data=clone_data,
            on_progress=on_progress,
        )
        return WorktreeCreationResult(worktree, warnings)

    @staticmethod
    def _report(callback: ProgressCallback | None, message: str) -> None:
        if callback:
            callback(message)

"""Orchestrate creation of a configured worktree environment."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from ..models import Worktree
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
        log_store: WorktreeLogStore,
    ) -> None:
        self.manager = manager
        self.log_store = log_store

    async def create(
        self,
        branch_name: str,
        base_branch: str | None,
        *,
        clone_data: bool,
        on_progress: ProgressCallback | None = None,
    ) -> WorktreeCreationResult:
        warnings: list[str] = []
        self._report(on_progress, "Creating git worktree...")
        started_at = perf_counter()
        worktree = await self.manager.create_worktree(branch_name, base_branch)
        self.log_store.record_elapsed(
            worktree.name,
            "Created worktree",
            started_at,
            True,
        )

        if clone_data:
            await self._clone_environment_data(worktree, warnings, on_progress)
        await self._run_post_create_commands(worktree, warnings, on_progress)
        return WorktreeCreationResult(worktree, tuple(warnings))

    async def _clone_environment_data(
        self,
        worktree: Worktree,
        warnings: list[str],
        on_progress: ProgressCallback | None,
    ) -> None:
        source_project = self.manager.get_compose_project_prefix()
        volumes = await self.manager.get_volumes()
        for index, volume in enumerate(volumes, start=1):
            self._report(
                on_progress,
                f"Cloning volume {index}/{len(volumes)}: {volume}...",
            )
            started_at = perf_counter()
            success, error = await asyncio.to_thread(
                self.manager.clone_volume_sync,
                source_project,
                worktree.compose_project_name,
                volume,
            )
            self.log_store.record_elapsed(
                worktree.name,
                f"Cloned volume {volume}",
                started_at,
                success,
            )
            if not success:
                warnings.append(f"Failed to clone volume {volume}: {error}")

        self._report(on_progress, "Tagging Docker images...")
        built_services = await asyncio.to_thread(self.manager.get_built_services_sync)
        if built_services:
            started_at = perf_counter()
            failures = await asyncio.to_thread(
                self.manager.tag_images_sync,
                source_project,
                worktree.compose_project_name,
                built_services,
            )
            self.log_store.record_elapsed(
                worktree.name,
                "Tagged images",
                started_at,
                not failures,
            )
            warnings.extend(
                f"Failed to tag image for {service}: {error}"
                for service, error in failures
            )

        bind_mounts = await self.manager.get_gitignored_bind_mounts()
        existing_mounts = [
            path
            for path in bind_mounts
            if (self.manager.main_repo_path / path).exists()
        ]
        await self._copy_paths(
            worktree,
            existing_mounts,
            description="bind mount",
            warnings=warnings,
            on_progress=on_progress,
        )

        copied = set(existing_mounts)
        clone_paths = [
            path
            for path in dict.fromkeys(self.manager.get_all_clone_paths())
            if path not in copied
        ]
        await self._copy_paths(
            worktree,
            clone_paths,
            description="extra path",
            warnings=warnings,
            on_progress=on_progress,
        )

    async def _copy_paths(
        self,
        worktree: Worktree,
        paths: list[str],
        *,
        description: str,
        warnings: list[str],
        on_progress: ProgressCallback | None,
    ) -> None:
        for index, relative_path in enumerate(paths, start=1):
            self._report(
                on_progress,
                f"Copying {description} {index}/{len(paths)}: {relative_path}...",
            )
            started_at = perf_counter()
            success, error = await asyncio.to_thread(
                self.manager.clone_path_sync,
                self.manager.main_repo_path / relative_path,
                worktree.path / relative_path,
            )
            self.log_store.record_elapsed(
                worktree.name,
                f"Copied {description} {relative_path}",
                started_at,
                success,
            )
            if not success:
                warnings.append(f"Failed to copy {relative_path}: {error}")

    async def _run_post_create_commands(
        self,
        worktree: Worktree,
        warnings: list[str],
        on_progress: ProgressCallback | None,
    ) -> None:
        commands = self.manager.post_create_commands
        for index, command in enumerate(commands, start=1):
            self._report(
                on_progress,
                f"Running command {index}/{len(commands)}: {command}...",
            )
            started_at = perf_counter()
            success, error = await asyncio.to_thread(
                self.manager.run_post_create_command_sync,
                command,
                worktree,
            )
            self.log_store.record_elapsed(
                worktree.name,
                f"Ran post-create command: {command}",
                started_at,
                success,
            )
            if not success:
                warnings.append(f"Command failed: {command}: {error}")

    @staticmethod
    def _report(callback: ProgressCallback | None, message: str) -> None:
        if callback:
            callback(message)

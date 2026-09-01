"""Provision Docker-backed data and setup hooks for a new environment."""

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from ..models import Worktree
from ._process import run_command
from .docker_manager import DockerManager
from .git_client import GitClient
from .worktree_log import WorktreeLogStore


class EnvironmentProvisioner:
    def __init__(
        self,
        main_repo_path: Path,
        source_project: str,
        clone_paths: tuple[str, ...],
        post_create_commands: tuple[str, ...],
        log_store: WorktreeLogStore | None,
    ) -> None:
        self.main_repo_path = main_repo_path
        self.clone_paths = clone_paths
        self.post_create_commands = post_create_commands
        self.log_store = log_store
        self.git = GitClient(main_repo_path)
        self.docker = DockerManager(main_repo_path, source_project)

    async def provision(
        self,
        worktree: Worktree,
        *,
        clone_data: bool,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if clone_data:
            await self._clone_data(worktree, warnings, on_progress)
        await self._run_post_create_commands(worktree, warnings, on_progress)
        return tuple(warnings)

    async def _clone_data(
        self,
        worktree: Worktree,
        warnings: list[str],
        on_progress: Callable[[str], None] | None,
    ) -> None:
        volumes = await self.docker.get_volumes()
        for index, volume in enumerate(volumes, start=1):
            self._report(
                on_progress,
                f"Cloning volume {index}/{len(volumes)}: {volume}...",
            )
            started_at = perf_counter()
            success, error = await asyncio.to_thread(
                self.docker.clone_volume_sync,
                worktree.compose_project_name,
                volume,
            )
            self._record_step(
                worktree,
                f"Cloned volume {volume}",
                started_at,
                success,
            )
            if not success:
                warnings.append(f"Failed to clone volume {volume}: {error}")

        self._report(on_progress, "Tagging Docker images...")
        built_services = await asyncio.to_thread(
            self.docker.get_built_services_sync
        )
        if built_services:
            started_at = perf_counter()
            failures = await asyncio.to_thread(
                self.docker.tag_images_sync,
                worktree.compose_project_name,
                built_services,
            )
            self._record_step(
                worktree,
                "Tagged images",
                started_at,
                not failures,
            )
            warnings.extend(
                f"Failed to tag image for {service}: {error}"
                for service, error in failures
            )

        bind_mounts = await self._get_gitignored_bind_mounts()
        existing_mounts = [
            path
            for path in bind_mounts
            if (self.main_repo_path / path).exists()
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
            for path in dict.fromkeys(self.clone_paths)
            if path not in copied and (self.main_repo_path / path).exists()
        ]
        await self._copy_paths(
            worktree,
            clone_paths,
            description="extra path",
            warnings=warnings,
            on_progress=on_progress,
        )

    async def _get_gitignored_bind_mounts(self) -> list[str]:
        bind_mounts = await asyncio.to_thread(self.docker.get_bind_mounts_sync)
        if not bind_mounts:
            return []
        returncode, stdout, _ = await asyncio.to_thread(
            self.git.run,
            "check-ignore",
            *bind_mounts,
        )
        return stdout.strip().splitlines() if returncode == 0 else []

    async def _copy_paths(
        self,
        worktree: Worktree,
        paths: list[str],
        *,
        description: str,
        warnings: list[str],
        on_progress: Callable[[str], None] | None,
    ) -> None:
        for index, relative_path in enumerate(paths, start=1):
            self._report(
                on_progress,
                f"Copying {description} {index}/{len(paths)}: {relative_path}...",
            )
            started_at = perf_counter()
            success, error = await asyncio.to_thread(
                self.docker.clone_path_sync,
                self.main_repo_path / relative_path,
                worktree.path / relative_path,
            )
            self._record_step(
                worktree,
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
        on_progress: Callable[[str], None] | None,
    ) -> None:
        for index, command in enumerate(self.post_create_commands, start=1):
            self._report(
                on_progress,
                f"Running command {index}/{len(self.post_create_commands)}: {command}...",
            )
            started_at = perf_counter()
            success, error = await asyncio.to_thread(
                self._run_post_create_command_sync,
                command,
                worktree,
            )
            self._record_step(
                worktree,
                f"Ran post-create command: {command}",
                started_at,
                success,
            )
            if not success:
                warnings.append(f"Command failed: {command}: {error}")

    def _run_post_create_command_sync(
        self,
        command: str,
        worktree: Worktree,
        timeout: float = 300.0,
    ) -> tuple[bool, str]:
        env = {
            **os.environ,
            "PROJECT_PATH": str(worktree.path),
            "PROJECT_NAME": worktree.name,
            "MAIN_REPO_PATH": str(self.main_repo_path),
        }
        returncode, _, error = run_command(
            ("sh", "-c", command),
            cwd=worktree.path,
            env=env,
            timeout=timeout,
        )
        if returncode == 0:
            return True, ""
        error = error.strip()
        if len(error) > 300:
            error = "..." + error[-300:]
        return False, error or f"exited with code {returncode}"

    def _record_step(
        self,
        worktree: Worktree,
        action: str,
        started_at: float,
        succeeded: bool,
    ) -> None:
        if self.log_store:
            self.log_store.record_elapsed(
                worktree.name,
                action,
                started_at,
                succeeded,
            )

    @staticmethod
    def _report(
        callback: Callable[[str], None] | None,
        message: str,
    ) -> None:
        if callback:
            callback(message)

"""Lifecycle management for non-Docker worktrees linked to a primary worktree."""

import asyncio
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import LinkedRepository
from ..models import GitStatus, LinkedWorktree, Worktree
from .git_status import get_git_status, get_git_status_strict
from .link_state_store import LinkStateStore
from .process_identity import capture_process_identity, matches_process_identity
from .worktree_manager import WorktreeManager
from .worktree_log import WorktreeLogStore


@dataclass(frozen=True, slots=True)
class LinkedProcessResult:
    worktree: LinkedWorktree
    pid: int


class LinkedWorktreeManager:
    """Create, discover, configure, and remove configured companion worktrees."""

    def __init__(
        self,
        repositories: tuple[LinkedRepository, ...],
        log_store: WorktreeLogStore,
    ):
        self.repositories = repositories
        self.log_store = log_store
        self.link_state = LinkStateStore()
        self.managers = {
            repository.name: WorktreeManager(
                main_repo_path=Path(repository.repository_path),
                worktree_path_template=repository.worktree_path,
            )
            for repository in repositories
        }
        self._processes: dict[str, subprocess.Popen] = {}

    @staticmethod
    def _key(primary: Worktree, repository: LinkedRepository) -> str:
        return f"{primary.path.resolve()}::{repository.name}"

    def attach(self, primary: Worktree) -> None:
        """Attach known links to a discovered primary worktree without mutating repos."""
        primary.linked_worktrees = []
        for repository in self.repositories:
            record = self.link_state.get_record(self._key(primary, repository))
            path_value = record.get("path")
            path = Path(path_value) if path_value else None
            if path and path.exists():
                ports = {name: int(port) for name, port in record.get("ports", {}).items()}
                ports.update(self._status_port(repository, path))
                process_status = self._process_status(record, bool(repository.start_command))
                log_path = self.log_store.linked_path_for(primary.name, repository.name)
                primary.linked_worktrees.append(LinkedWorktree(
                    repository_name=repository.name,
                    path=path,
                    branch=str(record.get("branch", primary.branch)),
                    ports=ports,
                    state=str(record.get("state", "linked")),
                    error=str(record.get("error", "")),
                    open_url_path=self._open_url_path(repository, ports),
                    can_start=bool(repository.start_command),
                    process_status=process_status,
                    log_path=log_path if log_path.exists() else None,
                    process_pid=int(record["pid"]) if process_status == "running" else None,
                ))
            elif primary.is_main:
                path = Path(repository.repository_path)
                if path.exists():
                    ports = self._status_port(repository, path)
                    process_status = "stopped" if repository.start_command else "external"
                    log_path = self.log_store.linked_path_for(primary.name, repository.name)
                    primary.linked_worktrees.append(LinkedWorktree(
                        repository_name=repository.name,
                        path=path,
                        branch=primary.branch,
                        ports=ports,
                        state="linked",
                        open_url_path=self._open_url_path(repository, ports),
                        can_start=bool(repository.start_command),
                        process_status=process_status,
                        log_path=log_path if log_path.exists() else None,
                    ))
            else:
                primary.linked_worktrees.append(LinkedWorktree(repository.name))

    async def create_link(self, primary: Worktree, repository_name: str) -> LinkedWorktree:
        """Create or retry one configured companion worktree."""
        repository = next(
            (item for item in self.repositories if item.name == repository_name), None
        )
        if repository is None:
            raise RuntimeError(f"Unknown linked repository: {repository_name}")
        result = await asyncio.to_thread(self._create_link_sync, primary, repository)
        self.attach(primary)
        return result

    def _create_link_sync(self, primary: Worktree, repository: LinkedRepository) -> LinkedWorktree:
        if not primary.branch:
            return LinkedWorktree(repository.name, state="error", error="Primary worktree has no branch")

        manager = self.managers[repository.name]
        key = self._key(primary, repository)
        ranges = {port.name: (port.start, port.end) for port in repository.ports}
        ports: dict[str, int] = {}
        try:
            ports = self.link_state.allocate(key, ranges) if ranges else {}
            record = self.link_state.get_record(key)
            existing_path = Path(record["path"]) if record.get("path") else None
            if existing_path and existing_path.exists():
                linked_path = existing_path
            else:
                exists = manager.git.branch_exists(primary.branch)
                linked_path = manager.create_worktree_sync(
                    primary.branch,
                    base_branch=None if exists else "HEAD",
                ).path
            self.link_state.update_record(
                key,
                path=str(linked_path),
                branch=primary.branch,
                state="linked",
                error="",
            )
            self._run_commands(repository.post_create_commands, primary, linked_path, ports)
            ports.update(self._status_port(repository, linked_path))
            process_status = self._process_status(
                self.link_state.get_record(key), bool(repository.start_command)
            )
            return LinkedWorktree(
                repository.name,
                linked_path,
                primary.branch,
                ports,
                "linked",
                open_url_path=self._open_url_path(repository, ports),
                can_start=bool(repository.start_command),
                process_status=process_status,
            )
        except Exception as error:
            self.link_state.update_record(key, state="error", error=str(error))
            return LinkedWorktree(repository.name, ports=ports, state="error", error=str(error))

    def _command_env(
        self,
        primary: Worktree,
        linked_path: Path,
        ports: dict[str, int],
    ) -> dict[str, str]:
        env = {
            **os.environ,
            "FLOTTE_PRIMARY_PATH": str(primary.path),
            "FLOTTE_LINKED_PATH": str(linked_path),
            "FLOTTE_WORKTREE_NAME": primary.name,
            "FLOTTE_BRANCH": primary.branch,
        }
        env.update({f"FLOTTE_PORT_{name.upper()}": str(port) for name, port in ports.items()})
        return env

    def _start_process(
        self,
        primary: Worktree,
        repository: LinkedRepository,
        linked_path: Path,
        ports: dict[str, int],
        key: str,
    ) -> int | None:
        if not repository.start_command:
            return None
        record = self.link_state.get_record(key)
        if self._is_managed_process_running(record):
            return int(record["pid"])
        if self._is_process_running(record.get("pid")):
            raise RuntimeError(f"{repository.name} is externally managed")
        self._run_commands(repository.pre_start_commands, primary, linked_path, ports)
        log_path = self.log_store.linked_path_for(primary.name, repository.name)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("wb", buffering=0) as log_file:
            process = subprocess.Popen(
                ["sh", "-c", repository.start_command],
                cwd=linked_path,
                env=self._command_env(primary, linked_path, ports),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        identity = capture_process_identity(process.pid)
        if identity is None:
            process.terminate()
            process.wait()
            raise RuntimeError(f"Could not verify the {repository.name} process identity")
        self._processes[key] = process
        self.link_state.update_record(
            key,
            pid=process.pid,
            process_identity=identity,
        )
        return process.pid

    @staticmethod
    def _is_process_running(pid: object) -> bool:
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _process_status(self, record: dict, can_start: bool) -> str:
        """Classify a persisted process without trusting a PID by itself."""
        pid = record.get("pid")
        if not self._is_process_running(pid):
            return "stopped" if can_start else "external"
        return "running" if matches_process_identity(record.get("process_identity")) else "external"

    def _is_managed_process_running(self, record: dict) -> bool:
        return self._is_process_running(record.get("pid")) and matches_process_identity(
            record.get("process_identity")
        )

    def _stop_process(self, key: str, record: dict) -> None:
        pid = record.get("pid")
        process = self._processes.pop(key, None)
        if not self._is_process_running(pid):
            if process is not None:
                process.wait()
            return
        if not matches_process_identity(record.get("process_identity")):
            raise RuntimeError("Linked process identity cannot be verified")
        try:
            os.killpg(int(record["process_identity"]["process_group"]), signal.SIGTERM)
        except ProcessLookupError:
            return
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(int(record["process_identity"]["process_group"]), signal.SIGKILL)
                process.wait()

    async def start_link(
        self,
        primary: Worktree,
        repository_name: str,
    ) -> LinkedProcessResult:
        """Start the configured development command for an existing linked worktree."""
        repository = next(
            (item for item in self.repositories if item.name == repository_name), None
        )
        if repository is None or not repository.start_command:
            raise RuntimeError(f"{repository_name} has no start command")
        key = self._key(primary, repository)
        record = self.link_state.get_record(key)
        path_value = record.get("path")
        path = Path(path_value) if path_value else None
        if primary.is_main:
            path = Path(repository.repository_path)
            if not path.exists():
                raise RuntimeError(f"Main checkout does not exist for {repository_name}")
            self.link_state.update_record(
                key,
                path=str(path),
                branch=primary.branch,
                state="main",
                error="",
            )
            record = self.link_state.get_record(key)
        if path is None or not path.exists():
            raise RuntimeError(f"No linked worktree exists for {repository_name}")
        ports = {name: int(port) for name, port in record.get("ports", {}).items()}
        ports.update(self._status_port(repository, path))
        pid = await asyncio.to_thread(
            self._start_process,
            primary,
            repository,
            path,
            ports,
            key,
        )
        if pid is None:
            raise RuntimeError(f"{repository_name} did not start a process")
        self.attach(primary)
        worktree = next(
            link
            for link in primary.linked_worktrees
            if link.repository_name == repository_name
        )
        return LinkedProcessResult(worktree, pid)

    async def restart_link(
        self,
        primary: Worktree,
        repository_name: str,
    ) -> LinkedProcessResult:
        """Restart a development process that Flotte previously started."""
        repository = next(
            (item for item in self.repositories if item.name == repository_name), None
        )
        if repository is None or not repository.start_command:
            raise RuntimeError(f"{repository_name} has no development command")
        key = self._key(primary, repository)
        record = self.link_state.get_record(key)
        if not self._is_managed_process_running(record):
            raise RuntimeError(f"{repository_name} is externally managed")
        await asyncio.to_thread(self._stop_process, key, record)
        return await self.start_link(primary, repository_name)

    async def stop_link(
        self,
        primary: Worktree,
        repository_name: str,
    ) -> LinkedProcessResult:
        """Stop a development process that Flotte previously started."""
        repository = next(
            (item for item in self.repositories if item.name == repository_name), None
        )
        if repository is None or not repository.start_command:
            raise RuntimeError(f"{repository_name} has no development command")
        key = self._key(primary, repository)
        record = self.link_state.get_record(key)
        if not self._is_managed_process_running(record):
            raise RuntimeError(f"{repository_name} is externally managed")
        pid = int(record["pid"])
        await asyncio.to_thread(self._stop_process, key, record)
        self.log_store.remove_linked(primary.name, repository.name)
        self.attach(primary)
        worktree = next(
            link
            for link in primary.linked_worktrees
            if link.repository_name == repository_name
        )
        return LinkedProcessResult(worktree, pid)

    @staticmethod
    def _status_port(repository: LinkedRepository, linked_path: Path) -> dict[str, int]:
        """Read one configured display port from the linked worktree's env file."""
        if not repository.status_port_env:
            return {}
        env_file = linked_path / repository.status_port_file
        try:
            for line in env_file.read_text().splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() == repository.status_port_env:
                    return {repository.status_port_label: int(value.strip())}
        except (OSError, ValueError):
            pass
        return {}

    @staticmethod
    def _open_url_path(repository: LinkedRepository, ports: dict[str, int]) -> str:
        """Resolve the optional status-port placeholder in an open URL path."""
        path = repository.open_url_path
        if "{port}" not in path:
            return path
        port = ports.get(repository.status_port_label)
        return path.replace("{port}", str(port)) if port is not None else ""

    def _run_commands(
        self,
        commands: tuple[str, ...],
        primary: Worktree,
        linked_path: Path,
        ports: dict[str, int],
    ) -> None:
        env = self._command_env(primary, linked_path, ports)
        for command in commands:
            result = subprocess.run(
                ["sh", "-c", command], cwd=linked_path, env=env,
                capture_output=True, timeout=300.0,
            )
            if result.returncode != 0:
                message = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(message or f"Link command failed: {command}")

    async def linked_statuses(
        self,
        primary: Worktree,
        *,
        strict: bool = False,
    ) -> dict[str, GitStatus]:
        """Return git status keyed by linked repository name for delete preflight."""
        status_requests: list[tuple[str, Path]] = []
        for linked in primary.linked_worktrees:
            if linked.path is None or not linked.path.exists():
                continue
            if linked.repository_name in self.managers:
                status_requests.append((linked.repository_name, linked.path))

        read_status = get_git_status_strict if strict else get_git_status
        statuses = await asyncio.gather(
            *(read_status(path) for _, path in status_requests)
        )
        return {
            repository_name: status
            for (repository_name, _), status in zip(status_requests, statuses)
        }

    async def remove_links(self, primary: Worktree) -> None:
        for repository in self.repositories:
            await self.remove_link(primary, repository.name)

    async def remove_link(self, primary: Worktree, repository_name: str) -> None:
        """Run unlink hooks and remove one companion worktree and its port record."""
        repository = next(
            (item for item in self.repositories if item.name == repository_name), None
        )
        if repository is None:
            raise RuntimeError(f"Unknown linked repository: {repository_name}")
        key = self._key(primary, repository)
        record = self.link_state.get_record(key)
        await asyncio.to_thread(self._stop_process, key, record)
        if primary.is_main:
            self.link_state.release(key)
            self.log_store.remove_linked(primary.name, repository.name)
            return
        path_value = record.get("path")
        if path_value:
            path = Path(path_value)
            if path.exists():
                ports = {name: int(port) for name, port in record.get("ports", {}).items()}
                await asyncio.to_thread(
                    self._run_commands,
                    repository.post_delete_commands,
                    primary,
                    path,
                    ports,
                )
                returncode, _, error = await asyncio.to_thread(
                    self.managers[repository.name].git.remove_worktree,
                    path,
                    force=True,
                )
                if returncode != 0:
                    raise RuntimeError(f"Failed to remove {repository.name} worktree: {error}")
                self.managers[repository.name].prune_empty_worktree_parents(path)
        self.link_state.release(key)
        self.log_store.remove_linked(primary.name, repository.name)

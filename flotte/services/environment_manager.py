"""Configure the runnable environment associated with a worktree."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from ..models import Worktree
from ..models.container import Container
from ..models.worktree import WorktreeStatus
from .docker_manager import DockerManager, get_all_containers_by_project
from .environment_provisioner import EnvironmentProvisioner
from .worktree_log import WorktreeLogStore

PORT_OFFSET_INCREMENT = 100


@dataclass(frozen=True, slots=True)
class EnvironmentPhase:
    command: str
    pending: WorktreeStatus
    settled: WorktreeStatus | None


@dataclass(frozen=True, slots=True)
class EnvironmentOperation:
    name: str
    log_action: str
    phases: tuple[EnvironmentPhase, ...]


@dataclass(frozen=True, slots=True)
class EnvironmentOperationResult:
    succeeded: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EnvironmentReconciliation:
    worktree: Worktree
    changed: bool
    completed_operation: WorktreeStatus | None


_START_PHASE = EnvironmentPhase(
    "start",
    WorktreeStatus.STARTING,
    WorktreeStatus.RUNNING,
)
_STOP_PHASE = EnvironmentPhase(
    "stop",
    WorktreeStatus.STOPPING,
    WorktreeStatus.STOPPED,
)
_RESTART_STOP_PHASE = EnvironmentPhase("stop", WorktreeStatus.STOPPING, None)

START_ENVIRONMENT = EnvironmentOperation(
    "start",
    "Started containers",
    (_START_PHASE,),
)
STOP_ENVIRONMENT = EnvironmentOperation(
    "stop",
    "Stopped containers",
    (_STOP_PHASE,),
)
RESTART_ENVIRONMENT = EnvironmentOperation(
    "restart",
    "Restarted containers",
    (_RESTART_STOP_PHASE, _START_PHASE),
)


class EnvironmentManager:
    def __init__(
        self,
        main_repo_path: Path,
        env_file: str = ".env",
        clone_paths: tuple[str, ...] = (),
        post_create_commands: tuple[str, ...] = (),
        log_store: WorktreeLogStore | None = None,
    ) -> None:
        self.main_repo_path = main_repo_path.resolve()
        self.env_file = env_file
        self.log_store = log_store
        self.provisioner = EnvironmentProvisioner(
            self.main_repo_path,
            self.compose_project_prefix(),
            clone_paths,
            post_create_commands,
            log_store,
        )
        self._service_cache: dict[Path, tuple[float, list[str]]] = {}

    def attach(self, worktree: Worktree) -> None:
        env = self._read_env(worktree.path)
        worktree.compose_project_name = env.get(
            "COMPOSE_PROJECT_NAME",
            worktree.path.name,
        )

    def configure(
        self,
        worktree: Worktree,
        existing_worktrees: list[Worktree],
    ) -> None:
        offset = self._next_port_offset(existing_worktrees)
        project_name = f"{self.compose_project_prefix()}-{worktree.name}"
        self._write_env(worktree.path, project_name, offset)
        worktree.compose_project_name = project_name

    def compose_project_prefix(self) -> str:
        main_env = self._read_env(self.main_repo_path)
        return main_env.get("COMPOSE_PROJECT_NAME", self.main_repo_path.name)

    async def provision(
        self,
        worktree: Worktree,
        *,
        clone_data: bool,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[str, ...]:
        return await self.provisioner.provision(
            worktree,
            clone_data=clone_data,
            on_progress=on_progress,
        )

    async def cleanup(self, worktree: Worktree) -> None:
        docker = DockerManager(worktree.path, worktree.compose_project_name)
        await asyncio.to_thread(docker.cleanup_sync)
        self._service_cache.pop(worktree.path, None)

    async def make_worktree_removable(self, worktree: Worktree) -> None:
        docker = DockerManager(worktree.path, worktree.compose_project_name)
        await asyncio.to_thread(docker.make_worktree_removable_sync)

    async def perform(
        self,
        worktree: Worktree,
        operation: EnvironmentOperation,
        on_status_changed: Callable[[], None] | None = None,
    ) -> EnvironmentOperationResult:
        started_at = perf_counter()
        docker = DockerManager(worktree.path, worktree.compose_project_name)
        try:
            for phase in operation.phases:
                worktree.start_operation(phase.pending, phase.settled)
                if on_status_changed:
                    on_status_changed()
                returncode, stdout, stderr = await getattr(
                    docker,
                    phase.command,
                )()
                if returncode != 0:
                    reason = stderr or stdout
                    worktree.clear_operation()
                    self._record_operation(worktree, operation, started_at, False)
                    return EnvironmentOperationResult(False, reason)
        except asyncio.CancelledError:
            worktree.clear_operation()
            raise
        except Exception as error:
            worktree.clear_operation()
            self._record_operation(worktree, operation, started_at, False)
            return EnvironmentOperationResult(False, str(error))

        self._record_operation(worktree, operation, started_at, True)
        return EnvironmentOperationResult(True)

    async def reconcile(
        self,
        worktrees: list[Worktree],
    ) -> list[EnvironmentReconciliation]:
        containers_by_project = await get_all_containers_by_project()
        results = await asyncio.gather(
            *(
                self._reconcile_worktree(
                    worktree,
                    containers_by_project.get(worktree.compose_project_name, []),
                )
                for worktree in worktrees
            )
        )
        return [
            EnvironmentReconciliation(worktree, changed, completed)
            for worktree, (changed, completed) in zip(worktrees, results)
        ]

    async def _reconcile_worktree(
        self,
        worktree: Worktree,
        container_data: list[dict],
    ) -> tuple[bool, WorktreeStatus | None]:
        before = self._snapshot(worktree)
        seen_services: set[str] = set()
        for data in container_data:
            service = data.get("Service", "")
            if not service:
                continue
            container = worktree.containers.setdefault(service, Container(service))
            container.update_from_docker(data)
            seen_services.add(service)

        for service in set(worktree.containers) - seen_services:
            del worktree.containers[service]

        for service in await self._services_for(worktree):
            if service not in worktree.containers:
                container = worktree.containers.setdefault(service, Container(service))
                container.mark_exited()

        worktree.has_polled = True
        completed = worktree.clear_completed_operation()
        return self._snapshot(worktree) != before, completed

    @staticmethod
    def _snapshot(worktree: Worktree) -> tuple:
        return (
            worktree.status,
            tuple(
                (container.service, container.state, container.status, tuple(container.ports))
                for container in worktree.container_list
            ),
        )

    async def _services_for(self, worktree: Worktree) -> list[str]:
        compose_file = worktree.path / "docker-compose.yml"
        try:
            mtime = compose_file.stat().st_mtime
        except OSError:
            self._service_cache.pop(worktree.path, None)
            return []

        cached = self._service_cache.get(worktree.path)
        cached_services = cached[1] if cached else []
        if cached is None or mtime != cached[0]:
            docker = DockerManager(worktree.path, worktree.compose_project_name)
            services = await docker.get_services()
            if services:
                self._service_cache[worktree.path] = (mtime, services)
                return services
        return cached_services

    def _record_operation(
        self,
        worktree: Worktree,
        operation: EnvironmentOperation,
        started_at: float,
        succeeded: bool,
    ) -> None:
        if self.log_store:
            self.log_store.record_elapsed(
                worktree.name,
                operation.log_action,
                started_at,
                succeeded,
            )

    def _next_port_offset(self, worktrees: list[Worktree]) -> int:
        used_offsets = {
            offset
            for worktree in worktrees
            if not worktree.is_main
            if (offset := self._port_offset(self._read_env(worktree.path))) > 0
        }
        candidate = PORT_OFFSET_INCREMENT
        while candidate in used_offsets:
            candidate += PORT_OFFSET_INCREMENT
        return candidate

    def _port_offset(self, env: dict[str, str]) -> int:
        main_env = self._read_env(self.main_repo_path)
        for key, value in env.items():
            if not key.endswith("_PORT") or key not in main_env:
                continue
            try:
                return int(value) - int(main_env[key])
            except ValueError:
                continue
        return 0

    def _read_env(self, path: Path) -> dict[str, str]:
        env_path = path / self.env_file
        if not env_path.exists():
            return {}

        env: dict[str, str] = {}
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
        except OSError:
            return {}
        return env

    def _write_env(self, worktree_path: Path, project_name: str, offset: int) -> None:
        lines = [f"COMPOSE_PROJECT_NAME={project_name}"]
        for key, value in self._read_env(self.main_repo_path).items():
            if key == "COMPOSE_PROJECT_NAME":
                continue
            if key.endswith("_PORT"):
                try:
                    value = str(int(value) + offset)
                except ValueError:
                    pass
            lines.append(f"{key}={value}")

        env_path = worktree_path / self.env_file
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(lines) + "\n")

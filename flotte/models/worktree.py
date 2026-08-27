from __future__ import annotations

import time
from enum import Enum
from pathlib import Path

from .container import Container, ContainerState
from .git_status import GitStatus
from .linked_worktree import LinkedWorktree

TRANSIENT_POLL_MAX_SECONDS = 60.0


class WorktreeStatus(Enum):
    """Aggregate status of all containers in a worktree."""

    RUNNING = "running"  # All containers healthy
    STARTING = "starting"  # Containers are starting up
    STOPPING = "stopping"  # Containers are shutting down
    STOPPED = "stopped"  # No containers running
    UNKNOWN = "unknown"  # Status not yet polled


class Worktree:
    """Worktree with integrated state management.

    Owns its containers (keyed by service name) and manages transient
    operation states for flash-free status display.
    """

    def __init__(
        self,
        name: str,
        path: Path,
        branch: str = "",
        compose_project_name: str = "",
        is_main: bool = False,
    ):
        """Create worktree.

        Args:
            name: Sanitized name (e.g., 'feature-xyz')
            path: Absolute path to worktree
            branch: Git branch name
            compose_project_name: Docker Compose project name
            is_main: True only for main repo (cannot delete)
        """
        self.name = name
        self.path = path
        self.branch = branch
        self.compose_project_name = compose_project_name
        self.is_main = is_main
        self.linked_worktrees: list[LinkedWorktree] = []
        self.git_status: GitStatus | None = None

        # Containers keyed by service name (persist across polls)
        self.containers: dict[str, Container] = {}

        # Simple transient state management (instance-level)
        self._transient: WorktreeStatus | None = None
        self._target: WorktreeStatus | None = None
        self._transient_since: float | None = None

        self._services: list[str] = []
        self._services_mtime: float | None = None
        self.has_polled = False

    def get_or_create_container(self, service: str) -> Container:
        """Get existing container or create new one.

        Args:
            service: Service name from docker-compose.yml

        Returns:
            Existing or newly created Container
        """
        if service not in self.containers:
            self.containers[service] = Container(service)
        return self.containers[service]

    @property
    def actual_status(self) -> WorktreeStatus:
        """Compute status from container states."""
        if not self.containers:
            return WorktreeStatus.STOPPED

        containers = list(self.containers.values())
        running = sum(1 for c in containers if c.state == ContainerState.RUNNING)
        starting = sum(
            1 for c in containers
            if c.state in (ContainerState.CREATED, ContainerState.RESTARTING)
        )

        if running == len(self.containers):
            return WorktreeStatus.RUNNING
        elif starting > 0:
            # Some containers are still starting up
            return WorktreeStatus.STARTING
        elif running > 0:
            # Some running (others may be exited) - normal running state
            # Some containers like 'assets' are meant to exit after completing
            return WorktreeStatus.RUNNING
        else:
            return WorktreeStatus.STOPPED

    @property
    def status(self) -> WorktreeStatus:
        """Effective status: transient overrides actual."""
        if self._transient is not None:
            return self._transient
        return self.actual_status

    @property
    def in_transient_operation(self) -> bool:
        """True while an operation still deserves fast reconciliation polling."""
        # A crash-looping container never reaches its target; don't fast-poll forever
        return (
            self._transient is not None
            and self._transient_since is not None
            and time.monotonic() - self._transient_since < TRANSIENT_POLL_MAX_SECONDS
        )

    def start_operation(
        self,
        transient: WorktreeStatus,
        target: WorktreeStatus | None = None,
    ) -> None:
        """Begin operation with transient status.

        Args:
            transient: Status to show during operation (STOPPING, STARTING, etc.)
            target: Status that clears the transient when reached (STOPPED, RUNNING).
                    If None, transient must be cleared manually.
        """
        self._transient = transient
        self._target = target
        self._transient_since = time.monotonic()

    def clear_operation(self) -> WorktreeStatus | None:
        """Clear transient status (operation completed or failed).

        Returns:
            The transient status that was cleared, or None if no transient was set.
        """
        cleared = self._transient
        self._transient = None
        self._target = None
        self._transient_since = None
        return cleared

    async def poll(
        self, container_data: list[dict]
    ) -> tuple[bool, WorktreeStatus | None]:
        """Update container state from a docker ps snapshot.

        Args:
            container_data: This worktree's container dicts from the shared
                docker ps call (see get_all_containers_by_project).

        Returns:
            Tuple of:
            - True if visible state changed since the last poll
            - The transient status that was cleared if target was reached
        """
        before = self._snapshot()

        # Update containers from poll data
        seen_services: set[str] = set()

        for data in container_data:
            service = data.get("Service", "")
            if service:
                container = self.get_or_create_container(service)
                container.update_from_docker(data)
                seen_services.add(service)

        # Remove containers for services no longer present
        for service in list(self.containers.keys()):
            if service not in seen_services:
                del self.containers[service]

        # Add placeholders for services without containers
        for service in await self._get_services():
            if service not in self.containers:
                container = self.get_or_create_container(service)
                container.mark_exited()

        self.has_polled = True

        # Auto-clear transient if target status reached
        cleared = None
        if self._target is not None and self.actual_status == self._target:
            cleared = self.clear_operation()

        return (self._snapshot() != before, cleared)

    def _snapshot(self) -> tuple:
        return (
            self.status,
            tuple(
                (c.service, c.state, c.status, tuple(c.ports))
                for c in self.container_list
            ),
        )

    async def _get_services(self) -> list[str]:
        """Service names from the compose file, cached until the file changes."""
        from ..services.docker_manager import DockerManager

        compose_file = self.path / "docker-compose.yml"
        try:
            mtime = compose_file.stat().st_mtime
        except OSError:
            self._services = []
            self._services_mtime = None
            return self._services

        if mtime != self._services_mtime:
            docker_mgr = DockerManager(self.path, self.compose_project_name)
            services = await docker_mgr.get_services()
            # Failure also returns [] - retry next poll rather than caching it
            if services:
                self._services = services
                self._services_mtime = mtime
        return self._services

    @property
    def web_url(self) -> str | None:
        """Get URL for web server container if present."""
        WEB_SERVERS = ("nginx", "apache", "caddy")
        for container in self.containers.values():
            if any(ws in container.service.lower() for ws in WEB_SERVERS):
                if container.ports:
                    return f"http://localhost:{container.ports[0]}"
        return None

    # Backwards compatibility: expose containers as list for widgets
    @property
    def container_list(self) -> list[Container]:
        """Get containers as sorted list (for table display)."""
        return sorted(self.containers.values(), key=lambda c: c.service)

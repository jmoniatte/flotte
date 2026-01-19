from __future__ import annotations

from enum import Enum
from pathlib import Path

from .container import Container, ContainerState

# Polling intervals
POLL_INTERVAL_NORMAL = 5.0  # seconds
POLL_INTERVAL_FAST = 1.0  # seconds during transient operations


class WorktreeStatus(Enum):
    """Aggregate status of all containers in a worktree."""

    RUNNING = "running"  # All containers healthy
    STARTING = "starting"  # Containers are starting up
    STOPPING = "stopping"  # Containers are shutting down
    STOPPED = "stopped"  # No containers running
    CREATING = "creating"  # Git worktree add + ride init in progress
    DELETING = "deleting"  # Cleanup + git worktree remove in progress
    ERROR = "error"  # Error state detected
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

        # Containers keyed by service name (persist across polls)
        self.containers: dict[str, Container] = {}

        # Simple transient state management (instance-level)
        self._transient: WorktreeStatus | None = None
        self._target: WorktreeStatus | None = None

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
    def poll_interval(self) -> float:
        """Return appropriate poll interval based on transient state."""
        if self._transient is not None:
            return POLL_INTERVAL_FAST
        return POLL_INTERVAL_NORMAL

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

    def clear_operation(self) -> None:
        """Clear transient status (operation completed or failed)."""
        self._transient = None
        self._target = None

    async def poll(self) -> None:
        """Poll container status from Docker."""
        from ..services.docker_manager import DockerManager

        docker_mgr = DockerManager(self.path, self.compose_project_name)
        container_data, all_services = await docker_mgr.get_container_data()

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
        for service in all_services:
            if service not in self.containers:
                container = self.get_or_create_container(service)
                container.mark_exited()

        # Auto-clear transient if target status reached
        if self._target is not None and self.actual_status == self._target:
            self.clear_operation()

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

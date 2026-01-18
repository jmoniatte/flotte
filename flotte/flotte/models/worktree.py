from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from .container import Container, ContainerState

if TYPE_CHECKING:
    from ..services.transient_state import TransientStateManager


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

    Transient state is stored centrally by name (not on object instances)
    to survive object replacement during polling.
    """

    # Class-level transient state manager (set by app on startup)
    _transient_manager: TransientStateManager | None = None

    @classmethod
    def set_transient_manager(cls, manager: TransientStateManager) -> None:
        """Set the class-level transient state manager."""
        cls._transient_manager = manager

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
        if self._transient_manager:
            transient = self._transient_manager.get_transient(self.name)
            if transient is not None:
                return transient
        return self.actual_status

    def start_operation(
        self,
        transient: WorktreeStatus,
        expected: WorktreeStatus | None = None,
    ) -> None:
        """Begin operation with transient status.

        Args:
            transient: Status to show during operation (STOPPING, STARTING, etc.)
            expected: Status that clears the transient when reached (STOPPED, RUNNING).
                      If None, transient must be cleared manually.
        """
        if self._transient_manager:
            self._transient_manager.start_operation(self.name, transient, expected)

    def clear_operation(self) -> None:
        """Clear transient status (operation completed or failed)."""
        if self._transient_manager:
            self._transient_manager.clear_operation(self.name)

    @property
    def is_operation_pending(self) -> bool:
        """True if an operation is in progress."""
        if self._transient_manager:
            return self._transient_manager.is_operation_pending(self.name)
        return False

    def update_from_poll(self, docker_data: list[dict]) -> None:
        """Update containers from docker compose ps output.

        Args:
            docker_data: List of dicts from docker compose ps --format json
        """
        seen_services: set[str] = set()

        for data in docker_data:
            service = data.get("Service", "")
            if service:
                container = self.get_or_create_container(service)
                container.update_from_docker(data)
                seen_services.add(service)

        # Remove containers for services no longer present
        for service in list(self.containers.keys()):
            if service not in seen_services:
                del self.containers[service]

        # Auto-clear transient if expected status reached
        if self._transient_manager:
            self._transient_manager.check_and_clear(self.name, self.actual_status)

    def add_missing_services(self, all_services: list[str]) -> None:
        """Add placeholder containers for services without actual containers.

        Args:
            all_services: List of all service names from docker compose config
        """
        for service in all_services:
            if service not in self.containers:
                container = self.get_or_create_container(service)
                container.mark_exited()

    # Backwards compatibility: expose containers as list for widgets
    @property
    def container_list(self) -> list[Container]:
        """Get containers as sorted list (for table display)."""
        return sorted(self.containers.values(), key=lambda c: c.service)

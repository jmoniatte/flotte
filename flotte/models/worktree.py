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

        self.has_polled = False

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

    def clear_completed_operation(self) -> WorktreeStatus | None:
        if self._target is None or self.actual_status != self._target:
            return None
        return self.clear_operation()

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

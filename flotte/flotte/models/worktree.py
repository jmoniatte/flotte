from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .container import Container, ContainerState


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


@dataclass
class Worktree:
    """Represents a git worktree with its Docker environment."""

    name: str  # Sanitized name (e.g., 'feature-xyz')
    path: Path  # Absolute path to worktree
    branch: str  # Git branch name
    compose_project_name: str  # Docker Compose project name
    # NOTE: The status field is deprecated for display purposes.
    # Use app.get_worktree_status(wt.name) instead, which handles
    # operation state for flash-free status display.
    # This field is kept for backwards compatibility and internal use.
    status: WorktreeStatus = WorktreeStatus.UNKNOWN
    is_main: bool = False  # True only for main repo (cannot delete)
    containers: list[Container] = field(default_factory=list)

    def calculate_status(self) -> WorktreeStatus:
        """Calculate aggregate status from container states."""
        if not self.containers:
            return WorktreeStatus.STOPPED

        running = sum(1 for c in self.containers if c.state == ContainerState.RUNNING)
        starting = sum(
            1 for c in self.containers
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

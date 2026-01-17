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
class PortConfig:
    """Port configuration for a worktree based on offset from base ports."""

    offset: int

    # Base ports (offset 0 = main repo)
    BASE_NGINX = 3000
    BASE_RAILS = 3001
    BASE_MYSQL = 3306
    BASE_MONGO = 27017
    BASE_REDIS = 6379
    BASE_ELASTICSEARCH = 9200
    BASE_VITE = 27182

    @property
    def nginx_port(self) -> int:
        return self.BASE_NGINX + self.offset

    @property
    def rails_port(self) -> int:
        return self.BASE_RAILS + self.offset

    @property
    def mysql_port(self) -> int:
        return self.BASE_MYSQL + self.offset

    @property
    def mongo_port(self) -> int:
        return self.BASE_MONGO + self.offset

    @property
    def redis_port(self) -> int:
        return self.BASE_REDIS + self.offset

    @property
    def elasticsearch_port(self) -> int:
        return self.BASE_ELASTICSEARCH + self.offset

    @property
    def vite_port(self) -> int:
        return self.BASE_VITE + self.offset

    @classmethod
    def from_offset(cls, offset: int) -> "PortConfig":
        return cls(offset=offset)

    @classmethod
    def default(cls) -> "PortConfig":
        return cls(offset=0)


@dataclass
class Worktree:
    """Represents a git worktree with its Docker environment."""

    name: str  # Sanitized name (e.g., 'feature-xyz')
    path: Path  # Absolute path to worktree
    branch: str  # Git branch name
    compose_project_name: str  # Docker Compose project name
    port_config: PortConfig
    # NOTE: The status field is deprecated for display purposes.
    # Use app.get_worktree_status(wt.name) instead, which handles
    # operation state and grace period for flash-free status display.
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

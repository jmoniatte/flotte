"""State management for Flotte application.

Tracks transient statuses during operations to prevent status flashing.
The state machine is repo-agnostic - it doesn't know about service names.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .models.worktree import WorktreeStatus
from .models.container import ContainerState

if TYPE_CHECKING:
    from .models.container import Container


def calculate_status_from_containers(containers: "list[Container]") -> WorktreeStatus:
    """Calculate aggregate status from container states.

    Mirrors Worktree.calculate_status() logic.
    """
    if not containers:
        return WorktreeStatus.STOPPED

    running = sum(1 for c in containers if c.state == ContainerState.RUNNING)
    starting = sum(
        1 for c in containers
        if c.state in (ContainerState.CREATED, ContainerState.RESTARTING)
    )

    if running == len(containers):
        return WorktreeStatus.RUNNING
    elif starting > 0:
        return WorktreeStatus.STARTING
    elif running > 0:
        return WorktreeStatus.RUNNING
    else:
        return WorktreeStatus.STOPPED


@dataclass
class WorktreeState:
    """State for a worktree.

    Tracks transient status during operations (STOPPING, STARTING, etc.)
    and clears it when the actual container status matches the expected outcome.
    """

    name: str
    _transient: WorktreeStatus | None = None
    _expected: WorktreeStatus | None = None
    _last_actual: WorktreeStatus = WorktreeStatus.UNKNOWN

    def start_operation(self, transient: WorktreeStatus, expected: WorktreeStatus | None = None) -> None:
        """Begin an operation.

        Args:
            transient: Status to show during operation (STOPPING, STARTING, etc.)
            expected: Status that clears the transient when reached (STOPPED, RUNNING, etc.)
                     If None, transient must be cleared manually.
        """
        self._transient = transient
        self._expected = expected

    def clear_operation(self) -> None:
        """Clear transient status (operation completed or failed)."""
        self._transient = None
        self._expected = None

    def update_from_poll(self, containers: "list[Container]") -> None:
        """Update state from polled containers.

        Computes actual status and clears transient if it matches expected.
        """
        self._last_actual = calculate_status_from_containers(containers)

        # Auto-clear transient when actual matches expected
        if self._expected is not None and self._last_actual == self._expected:
            self.clear_operation()

    @property
    def status(self) -> WorktreeStatus:
        """Get effective status (transient if set, else actual)."""
        if self._transient is not None:
            return self._transient
        return self._last_actual

    @property
    def is_operation_pending(self) -> bool:
        """True if an operation is in progress."""
        return self._transient is not None


@dataclass
class ProjectState:
    """State for a single project."""

    name: str
    worktrees: dict[str, WorktreeState] = field(default_factory=dict)

    def get_or_create_worktree(self, name: str) -> WorktreeState:
        """Get existing worktree state or create new one."""
        if name not in self.worktrees:
            self.worktrees[name] = WorktreeState(name=name)
        return self.worktrees[name]

    def remove_worktree(self, name: str) -> None:
        """Remove worktree state when worktree is deleted."""
        self.worktrees.pop(name, None)


class AppState:
    """Singleton state manager for the application."""

    _instance: "AppState | None" = None

    def __new__(cls) -> "AppState":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._projects: dict[str, ProjectState] = {}
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def get_or_create_project(self, name: str) -> ProjectState:
        """Get existing project state or create new one."""
        if name not in self._projects:
            self._projects[name] = ProjectState(name=name)
        return self._projects[name]

    def get_worktree_state(self, project: str, worktree: str) -> WorktreeState:
        """Get worktree state, creating project and worktree if needed."""
        return self.get_or_create_project(project).get_or_create_worktree(worktree)

    def remove_worktree(self, project: str, worktree: str) -> None:
        """Remove worktree state when worktree is deleted."""
        if project in self._projects:
            self._projects[project].remove_worktree(worktree)

    def clear_project(self, name: str) -> None:
        """Clear all state for a project."""
        self._projects.pop(name, None)
